from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from src.core.components import Component


@dataclass(slots=True)
class OperationModeTrigger:
    name: str
    # Check if the mode is triggered. Ex: stockpile exceeds 100 tonnes
    # would be check = lambda comp: comp.state["stockpile"] > 100
    check: Callable[[Component], bool]


@dataclass(slots=True)
class OperationMode:
    name: str
    triggers: list[OperationModeTrigger]
    # Data is used to store the mode's data. Ex: crush speed, crush capacity, etc.
    data: dict[str, Any] = field(default_factory=dict)
    # If multiple modes are triggered, the mode with the highest priority is selected.
    priority: int = 0


class HasOperationalModeManager:
    """
    Mixin for components that carry operation modes.

    Intended usage via multiple inheritance with a Component subclass, for example:
    ``class TransformerComponentWithMode(TransformerComponent, HasOperationalModeManager): ...``
    """

    def __init__(self) -> None:
        if not isinstance(self, Component):
            raise TypeError("HasOperationalModeManager must be mixed into a Component subclass")
        self.modes: dict[str, OperationMode] = {}
        self.current_mode: OperationMode | None = None

    def add_mode(self, mode: OperationMode) -> None:
        self.modes[mode.name] = mode

    def update_current_mode(self) -> OperationMode | None:
        # If multiple modes are triggered, the mode with the highest priority is selected.
        # If no modes are triggered, the current mode is not changed.
        for mode in sorted(self.modes.values(), key=lambda x: x.priority, reverse=True):
            if all(trigger.check(self) for trigger in mode.triggers):
                self.current_mode = mode
                return mode
        return self.current_mode


TComponent = TypeVar("TComponent", bound=Component)


def with_operational_mode(base_cls: type[TComponent]) -> type[TComponent]:
    """
    Build a component class that mixes ``HasOperationalModeManager`` into ``base_cls``.

    Example:
    ``TransformerComponentWithMode = with_operational_mode(TransformerComponent)``
    """

    class ComponentWithOperationalMode(base_cls, HasOperationalModeManager):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            base_cls.__init__(self, *args, **kwargs)
            HasOperationalModeManager.__init__(self)

    ComponentWithOperationalMode.__name__ = f"{base_cls.__name__}WithOperationalMode"
    return ComponentWithOperationalMode  # type: ignore[return-value]
