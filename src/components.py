from abc import ABC, abstractmethod
from typing import Callable
from .engine import Engine, Event
from .utils import Distribution
from .logging import get_logger


class Component(ABC):
    def __init__(self, component_id: str, type: str):
        self.component_id = component_id
        self.outputs = []
        self.type = type

    def connect(self, other: "Component") -> None:
        self.outputs.append(other)

    def disconnect(self, other: "Component") -> None:
        self.outputs.remove(other)

    @abstractmethod
    def handle_event(self, engine: "Engine", event: Event) -> None:
        pass


class SourceComponent(Component):
    def __init__(self, component_id: str, interval: Distribution):
        super().__init__(component_id, "Source")
        self.interval = interval

    def handle_event(self, engine: Engine, event: Event) -> None:
        current_time = engine.get_current_time()
        
        if event.type == "Generate":
            next_time = current_time + self.interval.sample()
            next_event = Event(next_time, self.component_id, "Generate", (), {})
            engine.add_event(next_event)

            departure_event = Event(event.time, self.outputs[0].component_id, "Arrival", (), {})
            engine.add_event(departure_event)
        else:
            raise ValueError(f"Invalid event type: {event.type}")

class SinkComponent(Component):
    def __init__(self, component_id: str):
        super().__init__(component_id, "Sink")

    def handle_event(self, engine: Engine, event: Event) -> None:
        log = get_logger(self.component_id)
        if event.type == "Arrival":
            log.info("Arrival event received", extra={"sim_time": engine.get_current_time()})
        else:
            raise ValueError(f"Invalid event type: {event.type}")

class DelayComponent(Component):
    def __init__(self, component_id: str, delay: Distribution):
        super().__init__(component_id, "Delay")
        self.delay = delay

    def handle_event(self, engine: Engine, event: Event) -> None:
        if event.type == "Arrival":
            delay = self.delay.sample()
            next_time = event.time + delay
            next_departure_event = Event(next_time, self.outputs[0].component_id, "Departure", (), {})
            engine.add_event(next_departure_event)
        elif event.type == "Departure":
            get_logger(self.component_id).info(
                "Departure event received", extra={"sim_time": engine.get_current_time()}
            )
        else:
            raise ValueError(f"Invalid event type: {event.type}")