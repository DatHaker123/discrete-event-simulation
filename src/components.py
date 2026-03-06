from abc import ABC, abstractmethod
from typing import Callable

from engine import Engine
from events import Event
from logger import get_logger
from utils import Distribution


class Component(ABC):
    def __init__(self, component_id: str, type: str):
        self.component_id = component_id
        self._outputs = []
        self.type = type
        self.log = get_logger(f"{type}_{component_id}")
        self.handleable_events = {}

    def connect(self, other: "Component") -> None:
        self._outputs.append(other)

    def disconnect(self, other: "Component") -> None:
        self._outputs.remove(other)

    def add_handleable_event(self, event_type: str, handler: Callable[[Engine, Event], None]) -> None:
        self.handleable_events[event_type] = handler

    def handle_event(self, engine: Engine, event: Event) -> None:
        try:
            self.handleable_events[event.type](engine, event)
        except KeyError:
            raise ValueError(f"Invalid event type: {event.type}")

class SingleOutputComponent(Component):
    def __init__(self, component_id: str, type: str):
        super().__init__(component_id, type)
        self.output = None
        self.add_handleable_event("Departure", self._handle_departure)

    def connect(self, other: "Component") -> None:
        if self.output is not None:
            raise ValueError("Component already connected")
        self.output = other
        super().connect(other)
    
    def disconnect(self, other: "Component") -> None:
        if self.output is not other:
            raise ValueError("Component not connected")
        self.output = None
        super().disconnect(other)

    def _handle_departure(self, engine: Engine, _) -> None:
        current_time = engine.get_current_time()
        self.log.info("Departure event received", extra={"sim_time": current_time})
        arrival_event = Event(current_time, self.output.component_id, "Arrival", (), {})
        engine.add_event(arrival_event)


class SourceComponent(SingleOutputComponent):
    def __init__(self, component_id: str, interval: Distribution):
        super().__init__(component_id, "Source")
        self.interval = interval
        self.add_handleable_event("Generate", self._handle_generate)

    def _handle_generate(self, engine: Engine, _) -> None:
        current_time = engine.get_current_time()
        self.log.info("Generate event received", extra={"sim_time": current_time})

        next_time = current_time + self.interval.sample()
        next_event = Event(next_time, self.component_id, "Generate", (), {})
        engine.add_event(next_event)

        departure_event = Event(current_time, self.component_id, "Departure", (), {})
        engine.add_event(departure_event)



class SinkComponent(Component):
    def __init__(self, component_id: str):
        super().__init__(component_id, "Sink")
        self.records = []
        self.add_handleable_event("Arrival", self._handle_arrival)

    def _handle_arrival(self, engine: Engine, event: Event) -> None:
        current_time = engine.get_current_time()

        self.log.info("Arrival event received", extra={"sim_time": current_time})
        self.records.append(event.time)



class DelayComponent(SingleOutputComponent):
    def __init__(self, component_id: str, delay_interval: Distribution):
        super().__init__(component_id, "Delay")
        self.delay_interval = delay_interval
        self.add_handleable_event("Arrival", self._handle_arrival)

    def _handle_arrival(self, engine: Engine, _: Event) -> None:
        current_time = engine.get_current_time()
        delay = self.delay_interval.sample()
        self.log.info("Arrival event received", extra={"sim_time": current_time, "delay": delay})

        next_time = current_time + delay
        next_departure_event = Event(next_time, self.component_id, "Departure", (), {})
        engine.add_event(next_departure_event)