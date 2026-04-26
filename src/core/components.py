from __future__ import annotations

from abc import ABC
from typing import Any, Callable

from .context import SimulationContext
from .engine import Engine
from .events import Entity, Event
from ..modules.logger import get_logger
from ..modules.utils import Distribution

# Per-component ``state`` dict type; handlers receive the full ``Component`` (see ``EventHandler`` below).
ComponentState = dict[str, Any]
EventHandler = Callable[[SimulationContext], None]


class Component(ABC):
    """
    Abstract base for every simulation component.

    Subclasses register handlers by event type.
    Topology is engine-owned: only ``Engine.connect`` / ``Engine.disconnect`` mutate links.
    Components expose read-only ``inputs`` / ``outputs`` views backed by private lists.
    Every component exposes mutable ``state`` and optional ``state_history`` snapshots.
    When ``track_state`` is enabled, ``handle_event`` records a shallow copy of
    ``state`` after each successful handler call.

    Each component has a monotonic ``version`` used with ``Event.version``: ``add_event``
    stamps incoming events with the **target** component's version at enqueue time; if you call
    ``advance_version()`` on that component, already-queued events for it become stale and
    ``Engine.run`` skips them. Purely discrete-event models often never bump the version.
    """

    def __init__(self, component_id: str, type: str, track_state: bool = False):
        self.component_id = component_id
        # Topology is stored locally for fast reads, but must only be mutated by Engine.
        self._outputs: list[Component] = []
        self._inputs: list[Component] = []
        self.type = type
        self.track_state = track_state
        self.state: ComponentState = {}
        self.state_history: list[tuple[float, ComponentState]] = []
        self.log = get_logger(f"{type}_{component_id}")
        self.handleable_events = {}
        #: Epoch for this block only; ``Engine.add_event`` copies it onto each event targeting this
        #: component. Bump with ``advance_version()`` to invalidate queued events for this handler.
        self._version: int = 0

    @property
    def version(self) -> int:
        return self._version

    def advance_version(self) -> int:
        """Invalidate queued events targeting this component (those with older ``event.version``)."""
        self._version += 1
        return self._version

    def _record_snapshot(self, engine: Engine) -> None:
        if not self.track_state:
            return
        t = engine.get_current_time()
        self.state_history.append((t, dict(self.state)))

    def _engine_add_output(self, other: "Component") -> None:
        # Topology is engine-owned, use engine.connect to add a link.
        self._outputs.append(other)

    def _engine_remove_output(self, other: "Component") -> None:
        # Topology is engine-owned, use engine.disconnect to remove a link.
        self._outputs.remove(other)

    def _engine_add_input(self, other: "Component") -> None:
        # Topology is engine-owned, use engine.connect to add a link.
        self._inputs.append(other)

    def _engine_remove_input(self, other: "Component") -> None:
        # Topology is engine-owned, use engine.disconnect to remove a link.
        self._inputs.remove(other)

    @property
    def outputs(self) -> tuple["Component", ...]:
        """Read-only downstream view. Mutations must go through ``Engine.connect``."""
        return tuple(self._outputs)

    @property
    def inputs(self) -> tuple["Component", ...]:
        """Read-only upstream view. Mutations must go through ``Engine.connect``."""
        return tuple(self._inputs)

    def set_handleable_event(self, event_type: str, handler: EventHandler) -> None:
        self.handleable_events[event_type] = handler
        self.log.info(f"Component {self.component_id} set handleable event {event_type}")

    def handle_event(self, engine: Engine, event: Event) -> None:
        try:
            self.handleable_events[event.type](SimulationContext(engine=engine, event=event, component=self))
        except KeyError:
            raise ValueError(f"Component {self.component_id} has no handler for event type: {event.type}")
        self._record_snapshot(engine)
        self.log.info(f"Component {self.component_id} handled event {event.type}")


class SingleIOComponent(Component):
    """
    Base class for linear-flow components with one logical upstream and downstream.

    Provides single-output wiring helpers and a shared ``default_handle_departure``
    that forwards ``event.entity`` to the connected output as an ``Arrival``.
    """

    @property
    def output(self) -> "Component":
        # Return the first connected component that is an output
        outputs = self.outputs
        if len(outputs) == 0:
            raise ValueError(f"Component {self.component_id} has no outputs")
        if len(outputs) > 1:
            raise ValueError(f"Component {self.component_id} expects a single output but has {len(outputs)}")
        return outputs[0]

    @property
    def input(self) -> "Component":
        # Return the first connected component that is an input
        inputs = self.inputs
        if len(inputs) == 0:
            raise ValueError(f"Component {self.component_id} has no inputs")
        if len(inputs) > 1:
            raise ValueError(f"Component {self.component_id} expects a single input but has {len(inputs)}")
        return inputs[0]

    def default_handle_departure(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        event = ctx.event
        current_time = engine.get_current_time()
        self.log.info("Default Departure event received", extra={"sim_time": current_time})
        arrival_event = Event(current_time, self.output.component_id, "Arrival", event.entity, {})
        engine.add_event(arrival_event)


class SourceComponent(SingleIOComponent):
    """
    SourceComponent is a component that generates arrivals.
    It is responsible for generating arrivals and sending them to the output.

    If interval is provided, it will generate arrivals at the interval.
    If interval is not provided, only the first Generate (or manual Arrivals
    emitted by other logic) will drive output; schedule further Generate events
    yourself if needed.

    entity_generator is called as ``(ctx)`` and must return an ``Entity`` to emit.
    The entity field on the Generate event is ignored. Use ``component.state`` / ``component.output`` as needed.

    Event flow:
    self Generate -> self Departure -> output Arrival (entity on Departure is forwarded)
    Source components are driven by Generate; Departure completes the handoff to the output.
    """

    def __init__(
        self,
        component_id: str,
        entity_generator: Callable[[SimulationContext], Entity],
        interval: Distribution | None = None,
        track_state: bool = False,
    ):
        super().__init__(component_id, "Source", track_state=track_state)
        self.interval = interval
        self.entity_generator = entity_generator

        self.set_handleable_event("Generate", self.default_handle_generate)
        self.set_handleable_event("Departure", self.default_handle_departure)

    @property
    def input(self) -> "Component":
        raise ValueError(f"Source component {self.component_id} cannot have an input")

    def default_handle_generate(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        current_time = engine.get_current_time()
        self.log.info("Default Generate event received", extra={"sim_time": current_time})
        entity = self.entity_generator(ctx)

        if entity is None:
            raise ValueError(f"Source component {self.component_id} entity_generator returned None")

        if self.interval is not None:
            next_time = current_time + self.interval.sample()
            next_generate_event = Event(next_time, self.component_id, "Generate", {}, {})
            engine.add_event(next_generate_event)

        departure_event = Event(current_time, self.component_id, "Departure", entity, {})
        engine.add_event(departure_event)


class SinkComponent(SingleIOComponent):
    """
    SinkComponent is a component that receives arrivals and adds them to the records.
    It is responsible for receiving arrivals and adding them to the records as tuples (time, entity).

    Sink components should only be controlled by the Arrival event.
    """

    def __init__(self, component_id: str, track_state: bool = False):
        super().__init__(component_id, "Sink", track_state=track_state)
        self.records = []

        self.set_handleable_event("Arrival", self.sink_handle_arrival)

    @property
    def output(self) -> "Component":
        raise ValueError(f"Sink component {self.component_id} cannot have an output")

    def sink_handle_arrival(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        event = ctx.event
        current_time = engine.get_current_time()
        self.log.info("Arrival event received, adding to records", extra={"sim_time": current_time})
        self.records.append((current_time, event.entity))


class DelayComponent(SingleIOComponent):
    """
    DelayComponent is a component that delays arrivals and sends them to the output.
    It is responsible for delaying arrivals and sending them to the output.

    Delay components should only be controlled by the Arrival event.
    """

    def __init__(
        self,
        component_id: str,
        delay_interval: Distribution,
        capacity: int = 1,
        track_state: bool = False,
    ):
        super().__init__(component_id, "Delay", track_state=track_state)
        self.delay_interval = delay_interval
        self.capacity = capacity
        self.content = []

        self.set_handleable_event("Arrival", self.handle_arrival)
        self.set_handleable_event("Departure", self.handle_departure_delay)

    @property
    def count(self) -> int:
        return len(self.content)

    def handle_arrival(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        event = ctx.event
        current_time = engine.get_current_time()

        if self.count >= self.capacity:
            raise ValueError(f"Delay component {self.component_id} is full")

        delay = self.delay_interval.sample()
        self.log.info("Arrival event received", extra={"sim_time": current_time, "delay": delay, "count": self.count})

        next_time = current_time + delay
        delayed_entity = event.entity
        self.content.append((next_time, delayed_entity))
        next_departure_event = Event(next_time, self.component_id, "Departure", delayed_entity, {})
        engine.add_event(next_departure_event)

    def handle_departure_delay(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        event = ctx.event
        current_time = engine.get_current_time()
        try:
            self.content.remove((current_time, event.entity))
        except ValueError:
            raise ValueError(f"Element {event.entity} unable to leave delay component {self.component_id} at time {current_time}")
        self.default_handle_departure(ctx)


class AssertComponent(SingleIOComponent):
    """
    AssertComponent is a component that drops arrivals that do not satisfy the condition.
    It is responsible for dropping arrivals that do not satisfy the condition.

    Assert components should only be controlled by the Arrival event.

    condition is a function ``(ctx) -> bool``.

    fail_handler is a function that is called when the condition fails.
    Assert component provides two default fail handlers: assert_fail_drop and assert_fail_error.
    assert_fail_drop records the failure and does not emit anything downstream (true drop).
    assert_fail_error raises a ValueError.
    """

    def assert_fail_drop(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        event = ctx.event
        self.dropped_elements.append((engine.get_current_time(), event.entity))

    def assert_fail_error(self, ctx: SimulationContext) -> None:
        event = ctx.event
        raise ValueError(f"Assert component {self.component_id} failed, entity: {event.entity}, condition: {self.condition}")

    def __init__(
        self,
        component_id: str,
        condition: Callable[[SimulationContext], bool],
        fail_handler: Callable[[SimulationContext], None] | None = None,
        track_state: bool = False,
    ):
        super().__init__(component_id, "Assert", track_state=track_state)
        self.condition = condition
        self.fail_handler = fail_handler if fail_handler is not None else self.assert_fail_drop
        self.dropped_elements = []
        self.set_handleable_event("Arrival", self.assert_handle_arrival)
        self.set_handleable_event("Departure", self.default_handle_departure)

    def assert_handle_arrival(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        event = ctx.event
        current_time = engine.get_current_time()
        if not self.condition(ctx):
            self.log.info(
                f"Assert component {self.component_id} failed, calling fail handler",
                extra={"sim_time": current_time},
            )
            self.fail_handler(ctx)
        else:
            arrival_event = Event(current_time, self.output.component_id, "Arrival", event.entity, {})
            engine.add_event(arrival_event)


class TransformerComponent(SingleIOComponent):
    """
    Maps each incoming entity to a new entity for downstream delivery.

    ``transform_function`` receives ``(ctx)`` and returns an
    ``Entity`` (same as ``event.entity`` on ``Event``): a ``dict[str, Any]`` payload.
    """

    def __init__(
        self,
        component_id: str,
        transform_function: Callable[[SimulationContext], Entity],
        track_state: bool = False,
    ):
        super().__init__(component_id, "Transformer", track_state=track_state)
        self.transform_function = transform_function

        self.set_handleable_event("Arrival", self.transformer_handle_arrival)
        self.set_handleable_event("Departure", self.default_handle_departure)

    def transformer_handle_arrival(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        current_time = engine.get_current_time()
        transformed_entity = self.transform_function(ctx)
        departure_event = Event(current_time, self.component_id, "Departure", transformed_entity, {})
        engine.add_event(departure_event)


class ConvergerComponent(Component):
    """
    Minimal converger for DES flows.

    Accepts arrivals from many upstream components and forwards entities directly to a
    single downstream output at the same simulation time.
    """

    def __init__(self, component_id: str, track_state: bool = False):
        super().__init__(component_id, "Converger", track_state=track_state)
        self.set_handleable_event("Arrival", self.handle_arrival)

    @property
    def output(self) -> "Component":
        outputs = self.outputs
        if len(outputs) == 0:
            raise ValueError(f"Component {self.component_id} has no outputs")
        if len(outputs) > 1:
            raise ValueError(f"Converger component {self.component_id} expects a single output but has {len(outputs)}")
        return outputs[0]

    def handle_arrival(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        event = ctx.event
        current_time = engine.get_current_time()
        forwarded = event.entity
        engine.add_event(Event(current_time, self.output.component_id, "Arrival", forwarded, {}))


class SplitterComponent(Component):
    """
    Fan-out DES component similar to Transformer, but one input to many outputs.

    ``splitter_function`` receives ``(ctx)`` and must return
    ``dict[str, Entity]`` keyed by downstream ``component_id``.
    Omitted downstream IDs emit nothing for that branch.
    """

    def __init__(
        self,
        component_id: str,
        splitter_function: Callable[[SimulationContext], dict[str, Entity]],
        track_state: bool = False,
    ):
        super().__init__(component_id, "Splitter", track_state=track_state)
        self.splitter_function = splitter_function
        self.set_handleable_event("Arrival", self.handle_arrival)

    @property
    def input(self) -> "Component":
        if len(self.inputs) == 0:
            raise ValueError(f"Component {self.component_id} has no inputs")
        if len(self.inputs) > 1:
            raise ValueError(f"Splitter component {self.component_id} expects a single input but has {len(self.inputs)}")
        return self.inputs[0]

    def handle_arrival(self, ctx: SimulationContext) -> None:
        engine = ctx.engine
        current_time = engine.get_current_time()
        outputs = list(self.outputs)
        if not outputs:
            raise ValueError(f"Splitter component {self.component_id} has no outputs")

        split_result = self.splitter_function(ctx)
        if not isinstance(split_result, dict):
            raise ValueError(
                f"Splitter component {self.component_id} expected dict[str, Entity] from splitter_function, got {type(split_result)}"
            )
        output_ids = {out.component_id for out in outputs}
        result_ids = set(split_result.keys())
        unknown = result_ids - output_ids
        if unknown:
            raise ValueError(
                f"Splitter component {self.component_id} mapping mismatch: unknown keys={sorted(unknown)}"
            )
        for out in outputs:
            if out.component_id not in split_result:
                continue
            engine.add_event(Event(current_time, out.component_id, "Arrival", split_result[out.component_id], {}))
