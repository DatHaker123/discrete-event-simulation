from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from src.core.components import Component
from src.core.context import SimulationContext


@dataclass(slots=True)
class OperationModeTrigger:
    name: str
    # Check if the mode is triggered. Ex: stockpile exceeds 100 tonnes
    # would be check = lambda ctx: ctx.component.state["stockpile"] > 100
    check: Callable[[SimulationContext], bool]
    # Optional predictor for the next trigger time under a continuous-state assumption.
    # Return simulation time (float) when this trigger is expected next, or None if no
    # upcoming crossing is expected. This is primarily useful for continuous
    # threshold-crossing simulations; tickwise models typically do not need it.
    expected_next_trigger_time: Callable[[SimulationContext, dict[str, float]], float | None] | None = None


@dataclass(slots=True)
class OperationMode:
    name: str
    triggers: list[OperationModeTrigger]
    # Data is used to store the mode's data. Ex: crush speed, crush capacity, etc.
    data: dict[str, Any] = field(default_factory=dict)
    # If multiple modes are triggered, the mode with the highest priority is selected.
    priority: int = 0


class HasOperationModeManager:
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

    def update_current_mode(self, ctx: SimulationContext) -> OperationMode | None:
        # If multiple modes are triggered, the mode with the highest priority is selected.
        # If no modes are triggered, the current mode is not changed.
        for mode in sorted(self.modes.values(), key=lambda x: x.priority, reverse=True):
            if all(trigger.check(ctx) for trigger in mode.triggers):
                self.current_mode = mode
                return mode
        return self.current_mode

    def get_next_mode_change(self, ctx: SimulationContext, delta: dict[str, float]) -> tuple[OperationMode | None, float | None]:
        """
        Resolve current mode now, then predict the next mode change under piecewise-constant
        rates ``delta``. Returns ``(next_mode, next_mode_change_time)`` where either item can
        be ``None`` when no upcoming change is predicted.

        ``delta`` parallels component ``state`` for numeric keys and represents per-time change
        rates. This is primarily for continuous threshold-crossing simulations; tickwise models
        usually only need ``update_current_mode``.
        """
        current_mode = self.update_current_mode(ctx)
        now = ctx.engine.get_current_time()

        next_mode: OperationMode | None = None
        next_t: float | None = None
        for mode in sorted(self.modes.values(), key=lambda x: x.priority, reverse=True):
            if current_mode is not None and mode.name == current_mode.name:
                continue

            trigger_times: list[float] = []
            for trigger in mode.triggers:
                if trigger.expected_next_trigger_time is None:
                    trigger_times = []
                    break
                t = trigger.expected_next_trigger_time(ctx, delta)
                if t is None:
                    trigger_times = []
                    break
                trigger_times.append(t)

            if not trigger_times:
                continue

            # All triggers for a mode must hold; with per-trigger predicted crossing times, a
            # simple approximation is when the last required trigger crosses.
            candidate_t = max(trigger_times)
            if candidate_t < now:
                candidate_t = now

            if next_t is None or candidate_t < next_t:
                next_t = candidate_t
                next_mode = mode

        return next_mode, next_t


TComponent = TypeVar("TComponent", bound=Component)


def with_operational_mode(base_cls: type[TComponent]) -> type[TComponent]:
    """
    Build a component class that mixes ``HasOperationalModeManager`` into ``base_cls``.

    Example:
    ``TransformerComponentWithMode = with_operational_mode(TransformerComponent)``
    """

    class ComponentWithOperationalMode(base_cls, HasOperationModeManager):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            base_cls.__init__(self, *args, **kwargs)
            HasOperationModeManager.__init__(self)

    ComponentWithOperationalMode.__name__ = f"{base_cls.__name__}WithOperationalMode"
    return ComponentWithOperationalMode  # type: ignore[return-value]
