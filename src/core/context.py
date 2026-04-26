from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .components import Component
    from .engine import Engine
    from .events import Entity, Event


@dataclass(slots=True)
class SimulationContext:
    engine: "Engine"
    event: "Event"
    component: "Component"

    @property
    def entity(self) -> "Entity":
        """
        Alias for ``event.entity``.

        ``Event.entity`` remains the canonical payload storage; this accessor is ergonomic sugar
        so handlers can use ``ctx.entity`` instead of ``ctx.event.entity``.
        """
        return self.event.entity

    @entity.setter
    def entity(self, value: dict[str, Any]) -> None:
        self.event.entity = value
