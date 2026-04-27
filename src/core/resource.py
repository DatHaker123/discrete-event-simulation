from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, TypeAlias

from .components import Entity, Event, SingleIOComponent
from .context import SimulationContext
from .queue import QueueComponent

ResourceData: TypeAlias = dict[str, Any]
ResourceGenerator: TypeAlias = Callable[[], ResourceData]


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


class ResourcePool:
    """
    Collection of same-type reusable resources with deterministic first-available allocation.

    The pool is defined by:
    - ``resource_type``: logical resource type (e.g. ``"truck"``)
    - ``resource_generator``: callable returning per-resource data dict
    - ``capacity``: number of identical resources to create

    Each resource is stored as a dict with auto-generated IDs:
    ``{id, type, data, allocated_to, allocated_at, released_at}``
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

        self.resources: dict[str, dict[str, Any]] = {}
        for index in range(self.capacity):
            resource_id = f"{self.resource_type}_{index + 1}"
            self.resources[resource_id] = {
                "id": resource_id,
                "type": self.resource_type,
                "data": deepcopy(self.resource_generator()),
                "allocated_to": None,
                "allocated_at": None,
                "released_at": None,
            }

    @property
    def total_count(self) -> int:
        return len(self.resources)

    @property
    def available_count(self) -> int:
        return sum(1 for r in self.resources.values() if r["allocated_to"] is None)

    @property
    def allocated_count(self) -> int:
        return self.total_count - self.available_count

    def get_resource(self, resource_id: str) -> dict[str, Any]:
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
            if resource["allocated_to"] is not None:
                continue
            resource["allocated_to"] = holder_id
            resource["allocated_at"] = float(at_time)
            return str(resource["id"])
        return None

    def release(self, resource_id: str, at_time: float) -> None:
        if resource_id not in self.resources:
            raise ValueError(
                f"Resource '{resource_id}' not found in pool '{self.pool_id}'"
            )
        resource = self.resources[resource_id]
        if resource["allocated_to"] is None:
            raise ValueError(f"Resource '{resource_id}' is not allocated")
        resource["allocated_to"] = None
        resource["released_at"] = float(at_time)


class RequestResourceComponent(QueueComponent):
    """
    Queue-derived component that acquires one resource per dispatched entity.

    Event flow:
    - ``Arrival``: enqueue entity request, then attempt dispatch if resource is available
      (inherits queue buffering/dispatch order)
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
        self.set_handleable_event("ResourceReleased", self.requestresource_handle_resourcereleased)

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
        resource_id = self.resource_pool.acquire(holder_id=self.component_id, at_time=now)
        if resource_id is None:
            return None

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
        return departure_entity, event_kwargs


class FreeResourceComponent(SingleIOComponent):
    """
    Single-IO component that releases one resource token from entity kwargs.

    On ``Arrival``:
    - Pop one ``resource_id`` from ``kwargs["resources"][pool_id]``
    - Release it to ``resource_pool``
    - Notify configured request-resource components using ``ResourceReleased``
    - Forward entity downstream as standard ``Departure`` -> ``Arrival``
    """

    def __init__(
        self,
        component_id: str,
        resource_pool: ResourcePool,
        *,
        request_component_ids: list[str] | None = None,
        track_state: bool = False,
    ):
        super().__init__(component_id, "FreeResource", track_state=track_state)
        self.resource_pool = resource_pool
        self.request_component_ids = list(request_component_ids or [])
        self.set_handleable_event("Arrival", self.freeresource_handle_arrival)
        self.set_handleable_event("Departure", self.singleio_handle_departure)

    def freeresource_handle_arrival(self, ctx: SimulationContext) -> None:
        now = ctx.engine.get_current_time()
        event_kwargs = deepcopy(ctx.event.kwargs)
        resource_id = _pop_stamped_resource(event_kwargs, self.resource_pool.pool_id)
        self.resource_pool.release(resource_id=resource_id, at_time=now)

        for request_component_id in self.request_component_ids:
            ctx.engine.add_event(
                Event(
                    now,
                    request_component_id,
                    "ResourceReleased",
                    {
                        "pool_id": self.resource_pool.pool_id,
                        "resource_id": resource_id,
                        "released_by": self.component_id,
                    },
                    {},
                )
            )

        ctx.engine.add_event(Event(now, self.component_id, "Departure", ctx.event.entity, event_kwargs))

