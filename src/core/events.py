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
    #: Epoch when this event was accepted by the engine (see ``Engine.add_event`` / ``advance_version``).
    #: Mainly useful for invalidating pre-scheduled work in discrete-rate / tick-style models; purely
    #: discrete-event models often need not advance the epoch.
    version: int = 0


def priority_for_event_type(event_type: str) -> int:
    """
    Returns the priority value for the given event type string.
    Subclasses or the user should implement this function.
    """
    if event_type == "Generate":
        return 1
    elif event_type == "Arrival":
        return 2
    elif event_type == "Departure":
        return 3
    else:
        return 0
