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
        self.inputs = []
        self.type = type
        self.log = get_logger(f"{type}_{component_id}")
        self.handleable_events = {}

    def probe_next_free_time(self, engine: Engine, rank: int = 0) -> float:
        return engine.get_current_time()

    def connect(self, other: "Component") -> None:
        self._outputs.append(other)
        other.inputs.append(self)

    def disconnect(self, other: "Component") -> None:
        self._outputs.remove(other)
        other.inputs.remove(self)

    def set_handleable_event(self, event_type: str, handler: Callable[[Engine, Event], None]) -> None:
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
        self.set_handleable_event("Departure", self._default_handle_departure)

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

    def _default_handle_departure(self, engine: Engine, _) -> None:
        current_time = engine.get_current_time()
        self.log.info("Departure event received (default handler)", extra={"sim_time": current_time})
        arrival_event = Event(current_time, self.output.component_id, "Arrival", (), {})
        engine.add_event(arrival_event)


class SourceComponent(SingleOutputComponent):
    def __init__(self, component_id: str, interval: Distribution):
        super().__init__(component_id, "Source")
        self.interval = interval
        self.set_handleable_event("Generate", self._handle_generate)

    def _handle_generate(self, engine: Engine, _) -> None:
        current_time = engine.get_current_time()
        self.log.info("Generate event received", extra={"sim_time": current_time})

        next_time = current_time + self.interval.sample()
        next_event = Event(next_time, self.component_id, "Generate", (), {})
        engine.add_event(next_event)

        arrival_event = Event(current_time, self.output.component_id, "Arrival", (), {})
        engine.add_event(arrival_event)



class SinkComponent(Component):
    def __init__(self, component_id: str):
        super().__init__(component_id, "Sink")
        self.records = []
        self.set_handleable_event("Arrival", self._handle_arrival)

    def _handle_arrival(self, engine: Engine, _: Event) -> None:
        current_time = engine.get_current_time()

        self.log.info("Arrival event received, adding to records", extra={"sim_time": current_time})
        self.records.append(current_time)



class DelayComponent(SingleOutputComponent):
    def __init__(self, component_id: str, delay_interval: Distribution, capacity: int = 1):
        super().__init__(component_id, "Delay")
        self.delay_interval = delay_interval
        self.capacity = capacity
        self.content = []
        self.set_handleable_event("Arrival", self._handle_arrival)
        self.set_handleable_event("Departure", self._handle_departure_delay)

    @property
    def size(self) -> int:
        return len(self.content)

    def probe_next_free_time(self, engine: Engine, rank: int = 0) -> float:
        current_time = engine.get_current_time()
        if rank >= len(self.content):
            return current_time
        return sorted(self.content)[rank]

    def _handle_arrival(self, engine: Engine, _: Event) -> None:
        current_time = engine.get_current_time()

        if self.size >= self.capacity:
            raise ValueError(f"Delay component {self.component_id} is full")

        delay = self.delay_interval.sample()
        self.log.info("Arrival event received", extra={"sim_time": current_time, "delay": delay, "size": self.size})

        next_time = current_time + delay
        self.content.append(next_time)
        next_departure_event = Event(next_time, self.component_id, "Departure", (), {})
        engine.add_event(next_departure_event)

    def _handle_departure_delay(self, engine: Engine, _: Event) -> None:
        current_time = engine.get_current_time()
        try:
            self.content.remove(current_time)
        except ValueError:
            raise ValueError(f"Element unable to leave delay component {self.component_id} at time {current_time}")
        self._default_handle_departure(engine, _)


class QueueComponent(SingleOutputComponent):
    """Single-server queue: Arrival enqueues; Departure serves one and sends to output. Uses probe_next_free_time for scheduling."""

    def __init__(self, component_id: str, service_distribution: Distribution, capacity: int = 1):
        super().__init__(component_id, "Queue")
        self.service_distribution = service_distribution
        self.capacity = capacity
        self.content: list[float] = []  # scheduled departure time for each item in the queue
        self.set_handleable_event("Arrival", self._handle_arrival)
        self.set_handleable_event("Departure", self._handle_departure_queue)

    @property
    def size(self) -> int:
        return len(self.content)

    def probe_next_free_time(self, engine: Engine, rank: int = 0) -> float:
        """When will the item at position rank (0=next to leave) finish service?"""
        if rank < len(self.content):
            return sorted(self.content)[rank]
        if self.content:
            return max(self.content)
        return engine.get_current_time()

    def _handle_arrival(self, engine: Engine, _: Event) -> None:
        current_time = engine.get_current_time()
        if self.size >= self.capacity:
            raise ValueError(f"Queue component {self.component_id} is full (capacity {self.capacity})")
        if self.size == 0:
            dep_time = current_time + self.service_distribution.sample()
            self.content.append(dep_time)
            engine.add_event(Event(dep_time, self.component_id, "Departure", (), {}))
            self.log.info("Arrival (queue was empty), scheduled departure", extra={"sim_time": current_time, "dep_time": dep_time})
        else:
            next_free = self.probe_next_free_time(engine, rank=len(self.content) - 1)
            if len(self.content) > 0:
                next_free = max(self.content)
            dep_time = next_free + self.service_distribution.sample()
            self.content.append(dep_time)
            self.log.info("Arrival (queue had items), appended departure", extra={"sim_time": current_time, "dep_time": dep_time})

    def _handle_departure_queue(self, engine: Engine, _: Event) -> None:
        current_time = engine.get_current_time()
        try:
            self.content.remove(current_time)
        except ValueError:
            raise ValueError(f"Queue component {self.component_id}: no departure at time {current_time}")
        self._default_handle_departure(engine, _)
        if self.content:
            next_dep = min(self.content)
            engine.add_event(Event(next_dep, self.component_id, "Departure", (), {}))
            self.log.info("Departure, scheduled next", extra={"sim_time": current_time, "next_dep": next_dep, "remaining": self.size})

