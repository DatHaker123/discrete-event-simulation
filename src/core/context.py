from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .components import Component
    from .engine import Engine
    from .events import Event


@dataclass(slots=True)
class SimulationContext:
    engine: "Engine"
    event: "Event"
    component: "Component"
