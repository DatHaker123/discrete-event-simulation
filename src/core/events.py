"""
Shared event model and event-type priority helpers.

Event types used by the framework/simulations:

- ``Generate``:
  Trigger a component to create or emit work/material/control payload.
  Most commonly used by ``SourceComponent``.
- ``Departure``:
  Internal handoff event for a component after it has produced output.
  For single-output blocks, default behavior typically forwards to downstream ``Arrival``.
- ``Arrival``:
  Incoming payload to a downstream component (the standard flow event between blocks).
- ``RateUpdate``:
  Control-style event used by threshold-crossing / piecewise-constant-rate simulations
  to propagate a new effective rate (instead of material arrivals).
  Conceptually, think of this as an ``Arrival`` for a control/rate stream: it is still
  an inbound update into the receiving component, just over "rate state" rather than inventory.
- ``ModeChange``:
  Control-style event usually self-scheduled by a component to apply a predicted mode
  transition time. In threshold-crossing models this is commonly paired with ``RateUpdate``:
  ``RateUpdate`` updates boundary/input rate, while ``ModeChange`` applies local control changes.
- ``QueueCredit``:
  Queue-server handshake signal that grants one dispatch credit to an upstream queue.
  A queue receiving ``QueueCredit`` may release one buffered entity downstream immediately.
- Custom event types:
  Allowed and encouraged for model-specific behavior (for example, maintenance, failures,
  control commands, or domain-specific transitions).

This module has no dependency on engine/components beyond shared typing.
"""

from dataclasses import dataclass
from typing import Any, TypeAlias

# Payload carried on events (``Event.entity``): string-keyed mapping (values are model-defined).
Entity: TypeAlias = dict[str, Any]


@dataclass(slots=True)
class Event:
    """Scheduled event routed to ``handler_id`` at ``time`` with model-defined payload in ``entity``.
    ``kwargs`` is internal, use with caution, just pass empty dict {} 99% of the time"""

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
    Return default tie-break priority for same-timestamp events.

    Higher values are processed later when timestamps are equal.
    Unknown/custom event types default to ``0``.

    Current built-in mapping:
    - ``RateUpdate`` -> 1 
    - ``ModeChange`` -> 1
    - ``Generate`` -> 2
    - ``Arrival`` -> 3
    - ``Departure`` -> 4
    """
    if event_type == "RateUpdate":
        return 1
    elif event_type == "ModeChange":
        return 1
    elif event_type == "Generate":
        return 2
    elif event_type == "Arrival":
        return 3
    elif event_type == "Departure":
        return 4
    else:
        return 0
