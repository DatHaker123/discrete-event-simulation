from abc import ABC, abstractmethod
from typing import Any, Callable

from engine import Engine
from events import Event
from logger import get_logger
from utils import Distribution


class Component(ABC):
    """
    Component is the base class for all components.
    It is responsible for handling events and connecting/disconnecting components.
    """
    def __init__(self, component_id: str, type: str):
        self.component_id = component_id
        self.outputs = []
        self.inputs = []
        self.type = type
        self.log = get_logger(f"{type}_{component_id}")
        self.handleable_events = {}

    @abstractmethod
    def output_to(self, other: "Component") -> None:
        # Connect this component's output to the other component's input
        pass

    @abstractmethod
    def disconnect_output_to(self, other: "Component") -> None:
        # Disconnect this component's output from the other component's input
        pass

    def set_handleable_event(self, event_type: str, handler: Callable[[Engine, Event], None]) -> None:
        self.handleable_events[event_type] = handler
        self.log.info(f"Component {self.component_id} set handleable event {event_type}")

    def handle_event(self, engine: Engine, event: Event) -> None:
        try:
            self.handleable_events[event.type](engine, event)
        except KeyError:
            raise ValueError(f"Component {self.component_id} has no handler for event type: {event.type}")
        self.log.info(f"Component {self.component_id} handled event {event.type}")


class SingleIOComponent(Component):
    """
    SingleIOComponent is a component that has one input and one output.
    It is responsible for connecting/disconnecting components and handling events.
    """
    def output_to(self, other: "Component") -> None:
        if len(self.outputs) > 0:
            raise ValueError(f"Component {self.component_id} is already connected to {self.outputs[0].component_id}")
        self.outputs.append(other)
        other.inputs.append(self)
        self.log.info(f"Component {self.component_id} connected to {other.component_id}")
    
    def disconnect_output_to(self, other: "Component") -> None:
        if other not in self.outputs:
            raise ValueError(f"Component {self.component_id} is not connected to {other.component_id}")
        self.outputs.remove(other)
        other.inputs.remove(self)
        self.log.info(f"Component {self.component_id} disconnected from {other.component_id}")

    @property
    def output(self) -> "Component":
        # Return the first connected component that is an output
        if len(self.outputs) == 0:
            raise ValueError(f"Component {self.component_id} has no outputs")
        return self.outputs[0]

    @property
    def input(self) -> "Component":
        # Return the first connected component that is an input
        if len(self.inputs) == 0:
            raise ValueError(f"Component {self.component_id} has no inputs")
        return self.inputs[0]
    
    def _default_handle_departure(self, engine: Engine, event: Event) -> None:
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

    entity_generator is called on each Generate (with the engine) and must return
    the entity to emit. The entity field on the Generate event is ignored.

    Event flow:
    self Generate -> self Departure -> output Arrival (entity on Departure is forwarded)
    Source components are driven by Generate; Departure completes the handoff to the output.
    """
    def __init__(
        self,
        component_id: str,
        entity_generator: Callable[[Engine], Any],
        interval: Distribution | None = None,
    ):
        super().__init__(component_id, "Source")
        self.interval = interval
        self.entity_generator = entity_generator

        self.set_handleable_event("Generate", self._default_handle_generate)
        self.set_handleable_event("Departure", self._default_handle_departure)

    @property
    def input(self) -> "Component":
        raise ValueError(f"Source component {self.component_id} cannot have an input")

    def _default_handle_generate(self, engine: Engine, _event: Event) -> None:
        current_time = engine.get_current_time()
        self.log.info("Default Generate event received", extra={"sim_time": current_time})
        entity = self.entity_generator(engine)

        if entity is None:
            raise ValueError(f"Source component {self.component_id} entity_generator returned None")

        if self.interval is not None:
            next_time = current_time + self.interval.sample()
            next_generate_event = Event(next_time, self.component_id, "Generate", None, {})
            engine.add_event(next_generate_event)

        departure_event = Event(current_time, self.component_id, "Departure", entity, {})
        engine.add_event(departure_event)


class SinkComponent(SingleIOComponent):
    """
    SinkComponent is a component that receives arrivals and adds them to the records.
    It is responsible for receiving arrivals and adding them to the records as tuples (time, entity).

    Sink components should only be controlled by the Arrival event.
    """
    def __init__(self, component_id: str):
        super().__init__(component_id, "Sink")
        self.records = []

        self.set_handleable_event("Arrival", self._sink_handle_arrival)

    @property
    def output(self) -> "Component":
        raise ValueError(f"Sink component {self.component_id} cannot have an output")

    def _sink_handle_arrival(self, engine: Engine, event: Event) -> None:
        current_time = engine.get_current_time()
        self.log.info("Arrival event received, adding to records", extra={"sim_time": current_time})
        self.records.append((current_time, event.entity))


class DelayComponent(SingleIOComponent):
    """
    DelayComponent is a component that delays arrivals and sends them to the output.
    It is responsible for delaying arrivals and sending them to the output.

    Delay components should only be controlled by the Arrival event.
    """
    def __init__(self, component_id: str, delay_interval: Distribution, capacity: int = 1):
        super().__init__(component_id, "Delay")
        self.delay_interval = delay_interval
        self.capacity = capacity
        self.content = []

        self.set_handleable_event("Arrival", self._handle_arrival)
        self.set_handleable_event("Departure", self._handle_departure_delay)

    @property
    def count(self) -> int:
        return len(self.content)

    def _handle_arrival(self, engine: Engine, event: Event) -> None:
        current_time = engine.get_current_time()

        if self.count >= self.capacity:
            raise ValueError(f"Delay component {self.component_id} is full")

        delay = self.delay_interval.sample()
        self.log.info("Arrival event received", extra={"sim_time": current_time, "delay": delay, "count": self.count})

        next_time = current_time + delay
        self.content.append((next_time, event.entity))
        next_departure_event = Event(next_time, self.component_id, "Departure", event.entity, {})
        engine.add_event(next_departure_event)

    def _handle_departure_delay(self, engine: Engine, event: Event) -> None:
        current_time = engine.get_current_time()
        try:
            self.content.remove((current_time, event.entity))
        except ValueError:
            raise ValueError(f"Element {event.entity} unable to leave delay component {self.component_id} at time {current_time}")
        self._default_handle_departure(engine, event)


class AssertComponent(SingleIOComponent):
    """
    AssertComponent is a component that drops arrivals that do not satisfy the condition.
    It is responsible for dropping arrivals that do not satisfy the condition.

    Assert components should only be controlled by the Arrival event.

    condition is a function that takes an Engine and an Event and returns a boolean.

    fail_handler is a function that is called when the condition fails.
    Assert component provides two default fail handlers: assert_fail_drop and assert_fail_error.
    assert_fail_drop records the failure and does not emit anything downstream (true drop).
    assert_fail_error raises a ValueError.
    """
    def assert_fail_drop(self, engine: Engine, event: Event) -> None:
        self.dropped_elements.append((engine.get_current_time(), event.entity))

    def assert_fail_error(self, _, event: Event) -> None:
        raise ValueError(f"Assert component {self.component_id} failed, entity: {event.entity}, condition: {self.condition}")

    def __init__(
        self,
        component_id: str,
        condition: Callable[[Engine, Event], bool],
        fail_handler: Callable[[Engine, Event], None] | None = None,
    ):
        super().__init__(component_id, "Assert")
        self.condition = condition
        self.fail_handler = fail_handler if fail_handler is not None else self.assert_fail_drop
        self.dropped_elements = []
        self.set_handleable_event("Arrival", self._assert_handle_arrival)
        self.set_handleable_event("Departure", self._default_handle_departure)

    def _assert_handle_arrival(self, engine: Engine, event: Event) -> None:
        current_time = engine.get_current_time()
        if not self.condition(engine, event):
            self.log.info(
                f"Assert component {self.component_id} failed, calling fail handler",
                extra={"sim_time": current_time},
            )
            self.fail_handler(engine, event)
        else:
            arrival_event = Event(current_time, self.output.component_id, "Arrival", event.entity, {})
            engine.add_event(arrival_event)


class TransformerComponent(SingleIOComponent):
    """
    TransformerComponent is a component that transforms events from one type to another.
    It is responsible for transforming events from one type to another.
    """
    def __init__(self, component_id: str, transform_function: Callable[[Engine, Event], Any]):
        super().__init__(component_id, "Transformer")
        self.transform_function = transform_function

        self.set_handleable_event("Arrival", self._transformer_handle_arrival)
        self.set_handleable_event("Departure", self._default_handle_departure)

    def _transformer_handle_arrival(self, engine: Engine, event: Event) -> None:
        current_time = engine.get_current_time()
        transformed_entity = self.transform_function(engine, event)
        departure_event = Event(current_time, self.component_id, "Departure", transformed_entity, {})
        engine.add_event(departure_event)

