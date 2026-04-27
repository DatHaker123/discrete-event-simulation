from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, TypeAlias

from .components import Entity, Event, SingleIOComponent, SinkComponent, SourceComponent
from .context import SimulationContext
from .queue import QueueComponent

ResourceData: TypeAlias = dict[str, Any]


@dataclass(slots=True)
class Resource:
    """
    First-class resource payload similar to an Entity, with pool linkage metadata.

    - ``data``: user-defined resource fields (entity-like dict payload)
    - ``id`` / ``pool_id`` / ``resource_type``: assigned by ``ResourcePool`` at creation
    - allocation fields are maintained by ``ResourcePool.acquire`` / ``release``
    """

    data: ResourceData = field(default_factory=dict)
    id: str = ""
    pool_id: str = ""
    resource_type: str = ""
    allocated_to: str | None = None
    allocated_at: float | None = None
    released_at: float | None = None


ResourceGenerator: TypeAlias = Callable[[], Resource]
ResourcePayloadMap: TypeAlias = dict[str, dict[str, dict[str, Any]]]


def _stamp_resource(kwargs: dict[str, Any], pool_id: str, resource_id: str) -> dict[str, Any]:
    resources = kwargs.setdefault("resources", {})
    if not isinstance(resources, dict):
        raise ValueError("event kwargs 'resources' must be a dict: pool_id -> list[resource_id]")
    pool_resources = resources.setdefault(pool_id, [])
    if not isinstance(pool_resources, list):
        raise ValueError(
            f"event kwargs resources['{pool_id}'] must be a list of resource ids"
        )
    pool_resources.append(resource_id)
    return kwargs


def _pop_stamped_resource(kwargs: dict[str, Any], pool_id: str) -> str:
    resources = kwargs.get("resources")
    if not isinstance(resources, dict):
        raise ValueError("event kwargs must contain resources dict to release a resource")
    pool_resources = resources.get(pool_id)
    if not isinstance(pool_resources, list):
        raise ValueError(
            f"event kwargs resources must contain list for pool '{pool_id}' to release a resource"
        )
    if not pool_resources:
        raise ValueError(f"event kwargs resources['{pool_id}'] is empty; nothing to release")
    resource_id = str(pool_resources.pop())
    if not pool_resources:
        resources.pop(pool_id, None)
    if not resources:
        kwargs.pop("resources", None)
    return resource_id


def _set_resource_payload(
    kwargs: dict[str, Any],
    *,
    pool_id: str,
    resource_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    payloads = kwargs.setdefault("resource_payloads", {})
    if not isinstance(payloads, dict):
        raise ValueError("event kwargs 'resource_payloads' must be a dict")
    pool_payloads = payloads.setdefault(pool_id, {})
    if not isinstance(pool_payloads, dict):
        raise ValueError(f"event kwargs resource_payloads['{pool_id}'] must be a dict")
    pool_payloads[resource_id] = deepcopy(payload)
    return kwargs


def _get_resource_payload(
    kwargs: dict[str, Any],
    *,
    pool_id: str,
    resource_id: str,
) -> dict[str, Any] | None:
    payloads = kwargs.get("resource_payloads")
    if not isinstance(payloads, dict):
        return None
    pool_payloads = payloads.get(pool_id)
    if not isinstance(pool_payloads, dict):
        return None
    payload = pool_payloads.get(resource_id)
    if not isinstance(payload, dict):
        return None
    return deepcopy(payload)


class ResourcePool:
    """
    Collection of same-type reusable resources with deterministic first-available allocation.

    The pool is defined by:
    - ``resource_type``: logical resource type (e.g. ``"truck"``)
    - ``resource_generator``: callable returning a ``Resource`` template object
    - ``capacity``: number of identical resources to create

    The pool injects/overrides linkage fields on creation:
    ``id``, ``pool_id``, ``resource_type``.
    """

    def __init__(
        self,
        pool_id: str,
        resource_type: str,
        resource_generator: ResourceGenerator,
        capacity: int,
    ):
        if capacity <= 0:
            raise ValueError(f"ResourcePool '{pool_id}' capacity must be >= 1, got {capacity}")
        self.pool_id = pool_id
        self.resource_type = str(resource_type)
        self.resource_generator = resource_generator
        self.capacity = int(capacity)

        self.resources: dict[str, Resource] = {}
        for index in range(self.capacity):
            resource_id = f"{self.resource_type}_{index + 1}"
            resource = deepcopy(self.resource_generator())
            if not isinstance(resource, Resource):
                raise ValueError(
                    "resource_generator must return a Resource instance"
                )
            resource.id = resource_id
            resource.pool_id = self.pool_id
            resource.resource_type = self.resource_type
            resource.allocated_to = None
            resource.allocated_at = None
            resource.released_at = None
            self.resources[resource_id] = resource

    @property
    def total_count(self) -> int:
        return len(self.resources)

    @property
    def available_count(self) -> int:
        return sum(1 for r in self.resources.values() if r.allocated_to is None)

    @property
    def allocated_count(self) -> int:
        return self.total_count - self.available_count

    def get_resource(self, resource_id: str) -> Resource:
        try:
            return deepcopy(self.resources[resource_id])
        except KeyError as exc:
            raise ValueError(
                f"Resource '{resource_id}' not found in pool '{self.pool_id}'"
            ) from exc

    def acquire(
        self,
        holder_id: str,
        at_time: float,
    ) -> str | None:
        """
        Acquire first available resource.

        Returns allocated resource_id or None if none are available.
        """
        for resource in self.resources.values():
            if resource.allocated_to is not None:
                continue
            resource.allocated_to = holder_id
            resource.allocated_at = float(at_time)
            return str(resource.id)
        return None

    def release(self, resource_id: str, at_time: float) -> None:
        if resource_id not in self.resources:
            raise ValueError(
                f"Resource '{resource_id}' not found in pool '{self.pool_id}'"
            )
        resource = self.resources[resource_id]
        if resource.allocated_to is None:
            raise ValueError(f"Resource '{resource_id}' is not allocated")
        resource.allocated_to = None
        resource.released_at = float(at_time)


class RequestResourceComponent(QueueComponent):
    """
    Queue-derived component that acquires one resource per dispatched entity.

    Event flow:
    - ``Arrival``: enqueue entity request, then attempt dispatch if resource is available
      (inherits queue buffering/dispatch order)
    - ``PreAcquireComplete``: marks pre-acquire side-flow completion for reserved resource
    - ``ResourceReleased``: retry dispatch from waiting buffer
    - ``Departure``: inherited queue departure forwarding

    On successful allocation, component stamps allocation metadata into event kwargs:
    - ``resources`` (dict)
    - ``resources[pool_id]`` is a list of allocated ``resource_id`` values
    """

    def __init__(
        self,
        component_id: str,
        resource_pool: ResourcePool,
        *,
        max_length: int | None = None,
        track_state: bool = False,
    ):
        super().__init__(
            component_id,
            max_length=max_length,
            credits_required=lambda _ctx: 1,
            track_state=track_state,
        )
        self.type = "RequestResource"
        self.resource_pool = resource_pool
        # Resource requests are not queue-credit gated; resources themselves are the gate.
        self.ready_credits = 10**12
        self.pre_acquire_source_component_id: str | None = None
        self._free_component: FreeResourceComponent | None = None
        self._pre_acquire_inflight: bool = False
        self._pre_acquire_reserved_resource_id: str | None = None
        self._pre_acquire_ready_payload: dict[str, Any] | None = None
        self.set_handleable_event("PreAcquireComplete", self.requestresource_handle_preacquirecomplete)
        self.set_handleable_event("ResourceReleased", self.requestresource_handle_resourcereleased)

    def link_pre_acquire_source(self, pre_source: "PreAcquireSourceComponent") -> None:
        """
        Couple pre-acquire trigger to a pre-source using Generate semantics.

        The user does not need to provide a custom generate function; RequestResource
        injects an identity generator that forwards the Generate event entity.
        """
        self.pre_acquire_source_component_id = pre_source.component_id
        pre_source.set_generate_function(lambda ctx: ctx.entity)

    def set_free_component(self, free_component: "FreeResourceComponent | None") -> None:
        self._free_component = free_component

    def requestresource_handle_preacquirecomplete(self, ctx: SimulationContext) -> None:
        if self._pre_acquire_reserved_resource_id is None:
            raise ValueError(
                f"RequestResource component {self.component_id} received PreAcquireComplete without reservation"
            )
        entity = ctx.entity
        if not isinstance(entity, dict):
            raise ValueError("PreAcquireComplete entity must be a dict resource payload")
        entity_resource_id = str(entity.get("id", ""))
        entity_pool_id = str(entity.get("pool_id", ""))
        if entity_resource_id != self._pre_acquire_reserved_resource_id:
            raise ValueError(
                f"PreAcquireComplete resource id mismatch: expected "
                f"{self._pre_acquire_reserved_resource_id}, got {entity_resource_id}"
            )
        if entity_pool_id != self.resource_pool.pool_id:
            raise ValueError(
                f"PreAcquireComplete pool_id mismatch: expected {self.resource_pool.pool_id}, got {entity_pool_id}"
            )
        self._pre_acquire_ready_payload = deepcopy(entity)
        self._pre_acquire_inflight = False
        self._attempt_dispatch(ctx)

    def requestresource_handle_resourcereleased(self, ctx: SimulationContext) -> None:
        _ = ctx.event
        self._attempt_dispatch(ctx)

    def queue_prepare_departure(
        self,
        ctx: SimulationContext,
        *,
        head_entity: Entity,
        required_credits: int,
        now: float,
    ) -> tuple[Entity, dict[str, Any]] | None:
        if self.pre_acquire_source_component_id is not None:
            if self._pre_acquire_ready_payload is None:
                if not self._pre_acquire_inflight:
                    resource_id = self.resource_pool.acquire(holder_id=self.component_id, at_time=now)
                    if resource_id is None:
                        return None
                    self._pre_acquire_inflight = True
                    self._pre_acquire_reserved_resource_id = resource_id
                    resource_snapshot = self.resource_pool.get_resource(resource_id)
                    resource_payload = {
                        **deepcopy(resource_snapshot.data),
                        "id": resource_snapshot.id,
                        "pool_id": resource_snapshot.pool_id,
                        "resource_type": resource_snapshot.resource_type,
                    }
                    ctx.engine.add_event(
                        Event(
                            now,
                            self.pre_acquire_source_component_id,
                            "PreAcquireStart",
                            resource_payload,
                            {
                                "__expected_resource_id": resource_id,
                                "__expected_pool_id": self.resource_pool.pool_id,
                            },
                        )
                    )
                return None
            resource_id = self._pre_acquire_reserved_resource_id
            if resource_id is None:
                raise ValueError("Pre-acquire ready payload set but no reserved resource id found")
            resource_payload = deepcopy(self._pre_acquire_ready_payload)
            self._pre_acquire_ready_payload = None
            self._pre_acquire_reserved_resource_id = None
        else:
            resource_id = self.resource_pool.acquire(holder_id=self.component_id, at_time=now)
            if resource_id is None:
                return None
            resource_snapshot = self.resource_pool.get_resource(resource_id)
            resource_payload = {
                **deepcopy(resource_snapshot.data),
                "id": resource_snapshot.id,
                "pool_id": resource_snapshot.pool_id,
                "resource_type": resource_snapshot.resource_type,
            }

        prepared = super().queue_prepare_departure(
            ctx,
            head_entity=head_entity,
            required_credits=required_credits,
            now=now,
        )
        if prepared is None:
            return None
        departure_entity, event_kwargs = prepared
        event_kwargs = deepcopy(event_kwargs)
        _stamp_resource(event_kwargs, self.resource_pool.pool_id, resource_id)
        _set_resource_payload(
            event_kwargs,
            pool_id=self.resource_pool.pool_id,
            resource_id=resource_id,
            payload=resource_payload,
        )
        if self._free_component is not None:
            self._free_component.register_resource_usage(resource_id, self.component_id)
        return departure_entity, event_kwargs


class FreeResourceComponent(SingleIOComponent):
    """
    Single-IO component that releases one resource token from entity kwargs.

    On ``Arrival``:
    - Pop one ``resource_id`` from ``kwargs["resources"][pool_id]``
    - Optionally run blocking post-release side-flow (``PostReleaseStart`` -> ``PostReleaseComplete``)
    - Release it to ``resource_pool``
    - Notify configured request-resource components using ``ResourceReleased``
    - Forward entity downstream as standard ``Departure`` -> ``Arrival``
    """

    def __init__(
        self,
        component_id: str,
        resource_pool: ResourcePool,
        *,
        track_state: bool = False,
    ):
        super().__init__(component_id, "FreeResource", track_state=track_state)
        self.resource_pool = resource_pool
        self.post_release_source_component_id: str | None = None
        self._resource_owner_by_id: dict[str, str] = {}
        self._pending_release_queue: list[tuple[Entity, dict[str, Any], str, dict[str, Any]]] = []
        self._post_release_inflight: bool = False
        self.set_handleable_event("Arrival", self.freeresource_handle_arrival)
        self.set_handleable_event("PostReleaseComplete", self.freeresource_handle_postreleasecomplete)
        self.set_handleable_event("Departure", self.singleio_handle_departure)

    def register_resource_usage(self, resource_id: str, request_component_id: str) -> None:
        self._resource_owner_by_id[str(resource_id)] = str(request_component_id)

    def freeresource_handle_arrival(self, ctx: SimulationContext) -> None:
        event_kwargs = deepcopy(ctx.event.kwargs)
        resources = event_kwargs.get("resources", {})
        resource_ids: list[str] = []
        if isinstance(resources, dict):
            pool_resources = resources.get(self.resource_pool.pool_id, [])
            if isinstance(pool_resources, list):
                while pool_resources:
                    resource_ids.append(str(pool_resources.pop()))
                if not pool_resources:
                    resources.pop(self.resource_pool.pool_id, None)
                if not resources:
                    event_kwargs.pop("resources", None)
        if not resource_ids:
            raise ValueError(
                f"FreeResource component {self.component_id} received Arrival without releasable "
                f"resources for pool '{self.resource_pool.pool_id}'"
            )
        for resource_id in resource_ids:
            if resource_id not in self._resource_owner_by_id:
                # Ignore resources not owned by this Free component to avoid cross-pair conflicts.
                continue
            resource_payload = _get_resource_payload(
                event_kwargs,
                pool_id=self.resource_pool.pool_id,
                resource_id=resource_id,
            )
            if resource_payload is None:
                resource_snapshot = self.resource_pool.get_resource(resource_id)
                resource_payload = {
                    **deepcopy(resource_snapshot.data),
                    "id": resource_snapshot.id,
                    "pool_id": resource_snapshot.pool_id,
                    "resource_type": resource_snapshot.resource_type,
                }
            self._pending_release_queue.append((deepcopy(ctx.entity), event_kwargs, resource_id, resource_payload))
        self._attempt_post_release(ctx)

    def set_post_release_source_component_id(self, component_id: str | None) -> None:
        self.post_release_source_component_id = component_id

    def set_post_release_source_component(self, component: "PostReleaseSourceComponent | None") -> None:
        self.post_release_source_component_id = None if component is None else component.component_id

    def _attempt_post_release(self, ctx: SimulationContext) -> None:
        if not self._pending_release_queue or self._post_release_inflight:
            return
        now = ctx.engine.get_current_time()
        _head_entity, _head_kwargs, _head_resource_id, head_resource_payload = self._pending_release_queue[0]
        if self.post_release_source_component_id is not None:
            self._post_release_inflight = True
            ctx.engine.add_event(
                Event(
                    now,
                    self.post_release_source_component_id,
                    "PostReleaseStart",
                    deepcopy(head_resource_payload),
                    {
                        "__expected_resource_id": _head_resource_id,
                        "__expected_pool_id": self.resource_pool.pool_id,
                    },
                )
            )
            return
        self._complete_release(ctx)

    def freeresource_handle_postreleasecomplete(self, ctx: SimulationContext) -> None:
        _ = ctx.event
        if not self._post_release_inflight:
            return
        if not self._pending_release_queue:
            return
        expected_resource_id = self._pending_release_queue[0][2]
        entity = ctx.entity
        if not isinstance(entity, dict):
            raise ValueError("PostReleaseComplete entity must be a dict resource payload")
        if str(entity.get("id", "")) != expected_resource_id:
            raise ValueError(
                f"PostReleaseComplete resource id mismatch: expected {expected_resource_id}, "
                f"got {entity.get('id', '')}"
            )
        if str(entity.get("pool_id", "")) != self.resource_pool.pool_id:
            raise ValueError(
                f"PostReleaseComplete pool_id mismatch: expected {self.resource_pool.pool_id}, "
                f"got {entity.get('pool_id', '')}"
            )
        head_entity, head_kwargs, head_resource_id, _old_payload = self._pending_release_queue[0]
        self._pending_release_queue[0] = (
            head_entity,
            head_kwargs,
            head_resource_id,
            deepcopy(entity),
        )
        self._post_release_inflight = False
        self._complete_release(ctx)

    def _complete_release(self, ctx: SimulationContext) -> None:
        if not self._pending_release_queue:
            return
        now = ctx.engine.get_current_time()
        entity, event_kwargs, resource_id, _resource_payload = self._pending_release_queue.pop(0)
        self.resource_pool.release(resource_id=resource_id, at_time=now)
        owner_component_id = self._resource_owner_by_id.pop(resource_id, None)
        if owner_component_id is not None:
            ctx.engine.add_event(
                Event(
                    now,
                    owner_component_id,
                    "ResourceReleased",
                    {
                        "pool_id": self.resource_pool.pool_id,
                        "resource_id": resource_id,
                        "released_by": self.component_id,
                    },
                    {},
                )
            )

        ctx.engine.add_event(Event(now, self.component_id, "Departure", entity, event_kwargs))
        self._attempt_post_release(ctx)


class PreAcquireSourceComponent(SourceComponent):
    """
    Entry component for pre-acquire side-flow.

    Receives ``PreAcquireStart`` and forwards generated entity downstream.
    """

    def __init__(self, component_id: str, track_state: bool = False):
        super().__init__(
            component_id,
            entity_generator=lambda ctx: ctx.entity,
            interval=None,
            track_state=track_state,
        )
        self.type = "PreAcquireSource"
        self.set_handleable_event("PreAcquireStart", self.source_handle_generate)

    def set_generate_function(self, generate_function: Callable[[SimulationContext], Entity]) -> None:
        self.entity_generator = generate_function


class PreAcquireSinkComponent(SinkComponent):
    """
    Terminal component for pre-acquire side-flow.

    On ``Arrival``, emits ``PreAcquireComplete`` to configured RequestResource component.
    """

    def __init__(
        self,
        component_id: str,
        *,
        track_state: bool = False,
    ):
        super().__init__(component_id, track_state=track_state)
        self.type = "PreAcquireSink"
        self.request_component: RequestResourceComponent | None = None
        self.set_handleable_event("Arrival", self.preacquiresink_handle_arrival)

    def set_request_component(self, component: RequestResourceComponent) -> None:
        self.request_component = component

    def preacquiresink_handle_arrival(self, ctx: SimulationContext) -> None:
        self.sink_handle_arrival(ctx)
        if self.request_component is None:
            raise ValueError(
                f"PreAcquireSink component {self.component_id} has no request component configured"
            )
        expected_resource_id = str(ctx.event.kwargs.get("__expected_resource_id", ""))
        expected_pool_id = str(ctx.event.kwargs.get("__expected_pool_id", ""))
        if expected_resource_id == "" or expected_pool_id == "":
            raise ValueError(
                f"PreAcquireSink component {self.component_id} missing expected resource identity in kwargs"
            )
        entity = ctx.entity
        if not isinstance(entity, dict):
            raise ValueError("PreAcquireSink arrival entity must be a dict resource payload")
        if str(entity.get("id", "")) != expected_resource_id:
            raise ValueError(
                f"PreAcquireSink resource id mismatch: expected {expected_resource_id}, "
                f"got {entity.get('id', '')}"
            )
        if str(entity.get("pool_id", "")) != expected_pool_id:
            raise ValueError(
                f"PreAcquireSink pool_id mismatch: expected {expected_pool_id}, "
                f"got {entity.get('pool_id', '')}"
            )
        now = ctx.engine.get_current_time()
        ctx.engine.add_event(
            Event(now, self.request_component.component_id, "PreAcquireComplete", ctx.entity, ctx.event.kwargs)
        )


class PostReleaseSourceComponent(SourceComponent):
    """
    Entry component for post-release side-flow.

    Receives ``PostReleaseStart`` and forwards generated entity downstream.
    """

    def __init__(self, component_id: str, track_state: bool = False):
        super().__init__(
            component_id,
            entity_generator=lambda ctx: ctx.entity,
            interval=None,
            track_state=track_state,
        )
        self.type = "PostReleaseSource"
        self.set_handleable_event("PostReleaseStart", self.source_handle_generate)


class PostReleaseSinkComponent(SinkComponent):
    """
    Terminal component for post-release side-flow.

    On ``Arrival``, emits ``PostReleaseComplete`` to configured FreeResource component.
    """

    def __init__(
        self,
        component_id: str,
        *,
        track_state: bool = False,
    ):
        super().__init__(component_id, track_state=track_state)
        self.type = "PostReleaseSink"
        self.free_component: FreeResourceComponent | None = None
        self.set_handleable_event("Arrival", self.postreleasesink_handle_arrival)

    def set_free_component(self, component: FreeResourceComponent) -> None:
        self.free_component = component

    def postreleasesink_handle_arrival(self, ctx: SimulationContext) -> None:
        self.sink_handle_arrival(ctx)
        if self.free_component is None:
            raise ValueError(
                f"PostReleaseSink component {self.component_id} has no free component configured"
            )
        expected_resource_id = str(ctx.event.kwargs.get("__expected_resource_id", ""))
        expected_pool_id = str(ctx.event.kwargs.get("__expected_pool_id", ""))
        if expected_resource_id == "" or expected_pool_id == "":
            raise ValueError(
                f"PostReleaseSink component {self.component_id} missing expected resource identity in kwargs"
            )
        entity = ctx.entity
        if not isinstance(entity, dict):
            raise ValueError("PostReleaseSink arrival entity must be a dict resource payload")
        if str(entity.get("id", "")) != expected_resource_id:
            raise ValueError(
                f"PostReleaseSink resource id mismatch: expected {expected_resource_id}, "
                f"got {entity.get('id', '')}"
            )
        if str(entity.get("pool_id", "")) != expected_pool_id:
            raise ValueError(
                f"PostReleaseSink pool_id mismatch: expected {expected_pool_id}, "
                f"got {entity.get('pool_id', '')}"
            )
        now = ctx.engine.get_current_time()
        ctx.engine.add_event(
            Event(now, self.free_component.component_id, "PostReleaseComplete", ctx.entity, ctx.event.kwargs)
        )

