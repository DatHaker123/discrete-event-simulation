from abc import ABC, abstractmethod
from typing import Callable
from .engine import Engine, Event
from .utils import Distribution


class Component(ABC):
    def __init__(self, component_id: str):
        self.component_id = component_id
        self.outputs = []

    def connect(self, other: "Component") -> None:
        self.outputs.append(other)

    def disconnect(self, other: "Component") -> None:
        self.outputs.remove(other)

    @abstractmethod
    def handle_event(self, engine: "Engine", event: Event) -> None:
        pass


class SourceComponent(Component):
    def __init__(self, component_id: str, interval: Distribution):
        super().__init__(component_id)
        self.interval = interval
        self.type = "Source"

    def handle_event(self, engine: Engine, event: Event) -> None:
        if event.type == "Generate":
            next_time = self.interval.sample()
            next_generate_event = Event(next_time, self.component_id, "Generate", (), {})
            next_output_event = Event(next_time, self.outputs[0].component_id, "Output", (), {})
            
            engine.add_event(next_generate_event)
            engine.add_event(next_output_event)

        else:
            raise ValueError(f"Invalid event type: {event.type}")

class SinkComponent(Component):
    def __init__(self, component_id: str):
        super().__init__(component_id)

    def handle_event(self, engine: Engine, event: Event) -> None:
        pass