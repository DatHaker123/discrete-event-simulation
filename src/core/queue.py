from __future__ import annotations

from typing import Any, Callable, TypeVar

from .components import Component, Entity, Event, SingleIOComponent
from .context import SimulationContext

QUEUE_CREDIT_EVENT_TYPE = "QueueCredit"


def _queue_credit_cost_key(queue_component_id: str) -> str:
    return f"__queue_credit_cost__{queue_component_id}"


class HasQueue:
    """
    Mixin for components that explicitly handshake with an upstream queue.

    Intended usage via multiple inheritance with a SingleIOComponent subclass.
    Components using this mixin should send ``QueueCredit`` to the configured queue
    when service capacity is released (typically on Departure).
    """

    def __init__(self) -> None:
        if not isinstance(self, SingleIOComponent):
            raise TypeError("HasQueue must be mixed into a SingleIOComponent subclass")
        self.queue_component_id: str | None = None
        self._initial_queue_credits_policy: Callable[[SimulationContext], int] = self._default_initial_queue_credits

    def set_queue_component_id(self, queue_component_id: str) -> None:
        self.queue_component_id = queue_component_id

    def _default_initial_queue_credits(self, _ctx: SimulationContext) -> int:
        # If server exposes capacity (e.g., Delay), bootstrap queue credits to capacity.
        return int(getattr(self, "capacity", 1))

    def set_initial_queue_credits_policy(self, policy: Callable[[SimulationContext], int]) -> None:
        self._initial_queue_credits_policy = policy

    def get_initial_queue_credits(self, ctx: SimulationContext) -> int:
        return int(self._initial_queue_credits_policy(ctx))

    def notify_queue_credit(self, ctx: SimulationContext, credits: int = 1) -> None:
        if self.queue_component_id is None:
            raise ValueError(f"Component {self.component_id} has no queue_component_id configured")
        if credits <= 0:
            return
        now = ctx.engine.get_current_time()
        ctx.engine.add_event(
            Event(
                now,
                self.queue_component_id,
                QUEUE_CREDIT_EVENT_TYPE,
                {"server_id": self.component_id, "credits": int(credits)},
                {},
            )
        )


TComponent = TypeVar("TComponent", bound=Component)


def with_queue(base_cls: type[TComponent]) -> type[TComponent]:
    """
    Build a component class that mixes ``HasQueue`` into ``base_cls``.

    Example:
    ``DelayWithQueue = with_queue(DelayComponent)``
    """

    if not issubclass(base_cls, SingleIOComponent):
        raise TypeError("with_queue requires a SingleIOComponent subclass")

    class ComponentWithQueue(base_cls, HasQueue):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            base_cls.__init__(self, *args, **kwargs)
            HasQueue.__init__(self)
            self._queue_base_departure_handler = self.handleable_events.get("Departure")
            # If base class did not register Departure during init, wrap now.
            if self._queue_base_departure_handler is not None and self.handleable_events.get("Departure") is not None:
                # No-op when already wrapped by set_handleable_event path.
                pass

        def _wrap_departure_handler(self) -> None:
            base_handler = self._queue_base_departure_handler
            if base_handler is None:
                return

            def _departure_with_credit(ctx: SimulationContext) -> None:
                credits = 1
                if self.queue_component_id is not None:
                    stamp_key = _queue_credit_cost_key(self.queue_component_id)
                    credits = int(ctx.event.kwargs.pop(stamp_key, 1))
                base_handler(ctx)
                self.notify_queue_credit(ctx, credits=credits)

            self.handleable_events["Departure"] = _departure_with_credit
            self.log.info(f"Component {self.component_id} set handleable event Departure")

        def set_handleable_event(self, event_type: str, handler: Callable[[SimulationContext], None]) -> None:
            # Keep same base behavior and auto-wrap Departure for queue credit signaling.
            self.handleable_events[event_type] = handler
            self.log.info(f"Component {self.component_id} set handleable event {event_type}")
            if event_type == "Departure":
                self._queue_base_departure_handler = handler
                self._wrap_departure_handler()

    ComponentWithQueue.__name__ = f"{base_cls.__name__}WithQueue"
    return ComponentWithQueue  # type: ignore[return-value]


class QueueComponent(SingleIOComponent):
    """
    FIFO queue with explicit pull/credit handshake from downstream server.

    Event flow:
    - ``Arrival`` from upstream: enqueue entity, then attempt dispatch
    - ``QueueCredit`` from downstream server: add one credit, then attempt dispatch
    - ``Departure``: standard SingleIO forward to output as ``Arrival``

    ``credits_required(ctx) -> int`` determines how many credits the queue-head entity
    needs before dispatch. The queue is FIFO and non-skipping: if the head requires more
    credits than currently available, dispatch waits even if later entities would require less.
    """

    def __init__(
        self,
        component_id: str,
        *,
        max_length: int | None = None,
        credits_required: Callable[[SimulationContext], int] | None = None,
        track_state: bool = False,
    ):
        super().__init__(component_id, "Queue", track_state=track_state)
        self.max_length = max_length
        self.credits_required = credits_required or (lambda _ctx: 1)
        self.buffer: list[Entity] = []
        self.ready_credits: int = 0
        self._pending_departures: int = 0

        self.set_handleable_event("Arrival", self.queue_handle_arrival)
        self.set_handleable_event(QUEUE_CREDIT_EVENT_TYPE, self.queue_handle_queuecredit)
        self.set_handleable_event("Departure", self.queue_handle_departure)

    def queue_prepare_departure(
        self,
        ctx: SimulationContext,
        *,
        head_entity: Entity,
        required_credits: int,
        now: float,
    ) -> tuple[Entity, dict[str, Any]] | None:
        """
        Build the self-Departure payload/kwargs for one reserved dispatch.

        Subclasses can override this to attach extra reservation metadata while
        preserving core queue scheduling semantics.
        """
        _ = (ctx, head_entity, now)
        event_kwargs: dict[str, Any] = {_queue_credit_cost_key(self.component_id): required_credits}
        return {}, event_kwargs

    def queue_pop_departure_entity(self, _ctx: SimulationContext) -> Entity:
        """
        Pop and return the head entity when handling a reserved Departure.

        Subclasses can override this to customize dequeue/finalization behavior.
        """
        if not self.buffer:
            raise ValueError(f"Queue component {self.component_id} has no buffered entity for Departure")
        entity = self.buffer.pop(0)
        self._pending_departures = max(0, self._pending_departures - 1)
        return entity

    def _attempt_dispatch(self, ctx: SimulationContext) -> None:
        now = ctx.engine.get_current_time()
        while self._pending_departures < len(self.buffer):
            head_entity = self.buffer[self._pending_departures]
            temp_ctx = SimulationContext(
                engine=ctx.engine,
                event=Event(now, self.component_id, "Peek", head_entity, {}),
                component=self,
            )
            required = int(self.credits_required(temp_ctx))
            if required <= 0:
                raise ValueError(
                    f"Queue component {self.component_id} credits_required must return >= 1, got {required}"
                )
            if self.ready_credits < required:
                break
            prepared_departure = self.queue_prepare_departure(
                ctx,
                head_entity=head_entity,
                required_credits=required,
                now=now,
            )
            if prepared_departure is None:
                break
            departure_entity, event_kwargs = prepared_departure
            self.ready_credits -= required
            self._pending_departures += 1
            ctx.engine.add_event(Event(now, self.component_id, "Departure", departure_entity, event_kwargs))

    def queue_handle_arrival(self, ctx: SimulationContext) -> None:
        if self.max_length is not None and len(self.buffer) >= self.max_length:
            raise ValueError(f"Queue component {self.component_id} is full (max_length={self.max_length})")
        self.buffer.append(ctx.entity)
        self._attempt_dispatch(ctx)

    def queue_handle_queuecredit(self, ctx: SimulationContext) -> None:
        credits = int(ctx.entity.get("credits", 1))
        if credits <= 0:
            return
        self.ready_credits += credits
        self._attempt_dispatch(ctx)

    def queue_handle_departure(self, ctx: SimulationContext) -> None:
        entity = self.queue_pop_departure_entity(ctx)
        now = ctx.engine.get_current_time()
        ctx.engine.add_event(Event(now, self.output.component_id, "Arrival", entity, ctx.event.kwargs))
        self._attempt_dispatch(ctx)
