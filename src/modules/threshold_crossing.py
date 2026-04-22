from __future__ import annotations

from typing import Callable, Literal

from src.core.components import SourceComponent
from src.core.context import SimulationContext
from src.core.events import Entity, Event
from src.modules.utils import Distribution


def get_linear_predictor(
    *,
    state_key: str,
    threshold: float,
    crossing: Literal["at_or_above", "at_or_below"],
    delta_key: str | None = None,
) -> Callable[[SimulationContext, dict[str, float]], float | None]:
    """
    Build a linear (piecewise-constant-rate) threshold-crossing predictor.

    The returned callable matches ``OperationModeTrigger.expected_next_trigger_time`` and
    predicts when ``state[state_key]`` next crosses ``threshold`` using ``delta[delta_key]``
    as the state derivative.
    """
    d_key = delta_key if delta_key is not None else state_key

    def _predict(ctx: SimulationContext, delta: dict[str, float]) -> float | None:
        value = float(ctx.component.state[state_key])
        d_value = float(delta.get(d_key, 0.0))
        now = ctx.engine.get_current_time()

        if crossing == "at_or_above":
            if value >= threshold:
                return now
            if d_value <= 0.0:
                return None
            return now + (threshold - value) / d_value

        # crossing == "at_or_below"
        if value <= threshold:
            return now
        if d_value >= 0.0:
            return None
        return now + (threshold - value) / d_value

    return _predict



class RateSourceComponent(SourceComponent):
    """
    Generalized SourceComponent variant that emits downstream ``RateUpdate`` on Departure instead of the standard Arrival.

    This supports models where source emissions represent control/rate updates instead of material
    Arrival flow. The generated entity is forwarded as-is (shallow-copied) in a ``RateUpdate`` event.
    """

    def __init__(
        self,
        component_id: str,
        entity_generator: Callable[[SimulationContext], Entity],
        *,
        interval: Distribution | None = None,
        track_state: bool = False,
    ):
        super().__init__(component_id, entity_generator, interval=interval, track_state=track_state)
        self.set_handleable_event("Departure", self.forward_departure_as_update)

    def forward_departure_as_update(self, ctx: SimulationContext) -> None:
        t = ctx.engine.get_current_time()
        payload = dict(ctx.event.entity)
        ctx.engine.add_event(
            Event(
                t,
                ctx.component.output.component_id,
                "RateUpdate",
                payload,
                {},
            )
        )
