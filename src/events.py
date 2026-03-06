"""Shared event type and priority. No dependency on engine or components."""

from dataclasses import dataclass

@dataclass
class Event:
    time: float
    handler_id: str
    type: str
    args: tuple
    kwargs: dict


def priority_for_event_type(event_type: str) -> int:
    """
    Returns the priority value for the given event type string.
    Subclasses or the user should implement this function.
    """
    # TODO: Implement priority for event type
    return 0
