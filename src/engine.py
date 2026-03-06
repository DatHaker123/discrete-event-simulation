from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

from events import Event, priority_for_event_type
from logger import get_logger

if TYPE_CHECKING:
    from .components import Component

class EventQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0  # Used as a secondary tiebreaker

    def push(self, event):
        # Use the custom event type priority as the main tiebreaker,
        # counter as the secondary, event.time as the actual time ordering
        prio = priority_for_event_type(event.type)
        heapq.heappush(self._queue, (event.time, prio, self._counter, event))
        self._counter += 1

    def pop(self):
        if self._queue:
            return heapq.heappop(self._queue)[3]
        raise IndexError("pop from an empty EventQueue")

    def peek(self):
        if self._queue:
            return self._queue[0][3]
        return None

    def is_empty(self):
        return not self._queue

    def __len__(self):
        return len(self._queue)


class Engine:
    def __init__(self):
        self._components = {}
        self._event_queue = EventQueue()
        self._current_time = 0.0
        self.log = get_logger("engine")

    def add_event(self, event: Event):
        self.log.info("Adding event", extra={"sim_time": self._current_time})
        self._event_queue.push(event)

    def pop_event(self):
        return self._event_queue.pop()

    def peek_event(self):
        return self._event_queue.peek()

    def add_component(self, component: "Component"):
        self._components[component.component_id] = component

    def remove_component(self, component: "Component"):
        del self._components[component.component_id]

    def run(self):
        while not self._event_queue.is_empty():
            event = self.pop_event()
            component = self._components[event.handler_id]
            self._current_time = event.time
            self.log.info("Handling event", extra={"sim_time": self._current_time})
            component.handle_event(self, event)

    def get_current_time(self):
        return self._current_time

    def get_results(self):
        """Return all components (e.g. for stats.get_records_as_printable_string(engine.get_results()))."""
        return self._components.values()