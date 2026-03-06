from __future__ import annotations

import heapq
import os
from typing import TYPE_CHECKING, Callable

from events import Event, priority_for_event_type
from logger import get_logger

if TYPE_CHECKING:
    from components import Component

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

    def get_snapshot(self):
        """Return a sorted list of events currently in the queue (order they would be popped)."""
        return [item[3] for item in sorted(self._queue, key=lambda x: (x[0], x[1], x[2]))]


class Engine:
    def __init__(
        self,
        time_limit: float | None = None,
        startup_events: list[Event] | None = None,
        visualize: bool = True,
        output_dir: str = "output",
    ):
        _max = os.getenv("MAX_SIM_TIME")
        self.time_limit = float(_max) if _max is not None and _max != "" else time_limit
        self._components = {}
        self._event_queue = EventQueue()
        self._current_time = 0.0
        self.log = get_logger("engine")
        self.startup_events = startup_events if startup_events is not None else []
        self.visualize = visualize
        self.output_dir = output_dir

    def add_event(self, event: Event):
        self.log.info("Adding event", extra={"sim_time": self._current_time, "event_type": event.type, "event_handler_id": event.handler_id})
        self._event_queue.push(event)

    def pop_event(self):
        return self._event_queue.pop()

    def peek_event(self):
        return self._event_queue.peek()

    def add_component(self, component: "Component"):
        self._components[component.component_id] = component

    def remove_component(self, component: "Component"):
        del self._components[component.component_id]

    def run(self, on_step: Callable[[float, Event | None, list], None] | None = None):
        if self.time_limit is not None:
            self.add_event(Event(self.time_limit, "End", "End", (), {}))

        for event in self.startup_events:
            self.add_event(event)

        visualizer = None
        if self.visualize:
            from visualization import Visualizer
            visualizer = Visualizer(*self.get_graph(), output_dir=self.output_dir)

        FRAME_EVENT_TYPES = frozenset({"Departure", "Arrival", "Generate"})

        def _step(t: float, e: Event | None, q: list) -> None:
            if visualizer is not None and (e is None or e.type in FRAME_EVENT_TYPES):
                visualizer.add_frame(t, e, list(q))
            if on_step is not None:
                on_step(t, e, q)

        step_cb = _step if (visualizer is not None or on_step is not None) else None
        if step_cb is not None:
            step_cb(0.0, None, self.get_queue_snapshot())

        while not self._event_queue.is_empty():
            event = self.pop_event()
            if event.type == "End":
                break
            if self.time_limit is not None and event.time >= self.time_limit:
                continue
            component = self._components[event.handler_id]
            self._current_time = event.time
            if step_cb is not None:
                step_cb(self._current_time, event, self.get_queue_snapshot())
            component.handle_event(self, event)

        if visualizer is not None:
            path = visualizer.close()
            self.log.info(f"Visualization saved to {path}", extra={"sim_time": self._current_time})

    def get_current_time(self):
        return self._current_time

    def get_queue_snapshot(self):
        """Return a sorted list of events currently in the queue."""
        return self._event_queue.get_snapshot()

    def get_results(self):
        return self._components.values()

    def get_graph(self):
        """Return (node_ids, edges) for visualization. Nodes = component_id, edges = (from_id, to_id)."""
        nodes = list(self._components.keys())
        edges = []
        for c in self._components.values():
            for out in getattr(c, "_outputs", []) or getattr(c, "output", []) or []:
                if out is not None:
                    try:
                        edges.append((c.component_id, out.component_id))
                    except AttributeError:
                        pass
        return nodes, edges