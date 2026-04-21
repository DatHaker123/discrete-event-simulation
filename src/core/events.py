"""Shared event type, entity alias, and priority. No dependency on engine or components."""

from dataclasses import dataclass
from typing import Any, TypeAlias

# Payload carried on events (``Event.entity``): string-keyed mapping (values are model-defined).
Entity: TypeAlias = dict[str, Any]


@dataclass(slots=True)
class Event:
    time: float
    handler_id: str
    type: str
    entity: Entity
    kwargs: dict
    #: Snapshot of the target component's ``version`` when ``Engine.add_event`` enqueued this event
    #: (see ``Component.advance_version``). Stale if the component's version has since increased.
    version: int = 0


def priority_for_event_type(event_type: str) -> int:
    """
    Returns the priority value for the given event type string.
    Subclasses or the user should implement this function.
    """
    if event_type == "ArrivalRateUpdate":
        return 1
    elif event_type == "Generate":
        return 2
    elif event_type == "Arrival":
        return 3
    elif event_type == "Departure":
        return 4
    else:
        return 0
