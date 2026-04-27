from __future__ import annotations

import os
from typing import Any, Callable, Literal

from src.core.components import SingleIOComponent, SourceComponent
from src.core.context import SimulationContext
from src.core.events import Entity, Event
from src.modules.operation_mode import HasOperationModeManager
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


def get_advancer_linear_inventory_state(
    *,
    level_key: str,
    in_rate_key: str,
    out_rate_key: str,
    time_key: str,
    min_level: float = 0.0,
) -> Callable[[SimulationContext], None]:
    """
    Build an advancer for one inventory-like state variable under piecewise-constant rates.

    The returned callable updates ``ctx.component.state`` in-place:
    - ``state[level_key]`` integrates with derivative ``in_rate - out_rate``
    - ``state[time_key]`` is set to current simulation time
    """
    def _advance(ctx: SimulationContext) -> None:
        st = ctx.component.state
        now = ctx.engine.get_current_time()
        last_t = float(st[time_key])
        dt = max(0.0, now - last_t)
        if dt <= 0.0:
            st[time_key] = now
            return

        in_rate = float(st[in_rate_key])
        out_rate = float(st[out_rate_key])
        next_level = float(st[level_key]) + (in_rate - out_rate) * dt
        st[level_key] = max(min_level, next_level)
        st[time_key] = now

    return _advance


def get_default_rate_update_handler(
    *,
    level_key: str,
    in_rate_key: str,
    out_rate_key: str,
    advance_state: Callable[[SimulationContext], None],
    incoming_rate_entity_key: str = "rate_tph",
    mode_capacity_key: str = "crush_rate_tph",
) -> Callable[[SimulationContext], None]:
    """
    Build a default one-dimensional linear ``RateUpdate``/``ModeChange`` handler. Intended for
    use with ``RateSchedulerComponent``.

    Lifecycle:
    1) advance state to ``now`` (via ``advance_state`` policy hook)
    2) apply incoming upstream rate update (for ``RateUpdate`` events)
    3) resolve mode, compute internal processing rate, write it to state
    4) emit self ``Departure`` (the component forwards it as downstream ``RateUpdate``)
    5) predict/schedule next local ``ModeChange`` and invalidate old projections
    """

    eps_time = float(os.getenv("EPS_TIME", "1e-9"))

    def _handler(ctx: SimulationContext) -> None:
        engine = ctx.engine
        comp = ctx.component
        st = comp.state
        now = engine.get_current_time()

        advance_state(ctx)

        if ctx.event.type == "RateUpdate" and incoming_rate_entity_key in ctx.event.entity:
            st[in_rate_key] = float(ctx.event.entity[incoming_rate_entity_key])

        selected_mode = comp.update_current_mode(ctx)
        if selected_mode is None:
            raise RuntimeError("No operational mode selected for component.")

        capacity_obj = selected_mode.data[mode_capacity_key]
        sampled_capacity = capacity_obj.sample() if hasattr(capacity_obj, "sample") else capacity_obj
        capacity = float(sampled_capacity)
        # Internal processing rate is mode-driven (not directly tied to incoming boundary rate).
        out_rate = capacity
        st[out_rate_key] = out_rate

        payload: dict[str, Any] = {
            "rate_tph": out_rate,
            "mode": selected_mode.name,
            "name": ctx.event.entity.get("name", ""),
            level_key: float(st[level_key]),
            in_rate_key: float(st[in_rate_key]),
        }

        delta = {level_key: float(st[in_rate_key]) - float(st[out_rate_key])}
        next_mode, next_t = comp.get_next_mode_change(ctx, delta)
        if next_mode is not None and next_t is not None:
            if next_t <= now + eps_time:
                next_t = now + eps_time
            if engine.time_limit is None or next_t < engine.time_limit:
                comp.advance_version()
                engine.add_event(Event(next_t, comp.component_id, "ModeChange", {}, {}))

        # Enqueue departure after any version bump so it stays valid.
        engine.add_event(Event(now, comp.component_id, "Departure", payload, {}))

    return _handler


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
        self.set_handleable_event("Departure", self.ratesource_handle_departure)

    def ratesource_handle_departure(self, ctx: SimulationContext) -> None:
        t = ctx.engine.get_current_time()
        payload = ctx.event.entity
        ctx.engine.add_event(
            Event(
                t,
                ctx.component.output.component_id,
                "RateUpdate",
                payload,
                {},
            )
        )


class RateSchedulerComponent(SingleIOComponent, HasOperationModeManager):
    """
    Scheduler component for threshold-crossing control logic.

    Event flow:
    ``RateUpdate`` / ``ModeChange`` (in) -> self ``Departure`` -> downstream ``RateUpdate`` (out)

    The provided handler is responsible for updating state, resolving mode, scheduling next
    ``ModeChange``, and emitting self ``Departure`` with the current output payload.
    """

    def __init__(
        self,
        component_id: str,
        scheduler_handler: Callable[[SimulationContext], None],
        track_state: bool = False,
    ):
        SingleIOComponent.__init__(self, component_id, "RateScheduler", track_state=track_state)
        HasOperationModeManager.__init__(self)
        self.set_handleable_event("RateUpdate", scheduler_handler)
        self.set_handleable_event("ModeChange", scheduler_handler)
        self.set_handleable_event("Departure", self.ratescheduler_handle_departure)

    def ratescheduler_handle_departure(self, ctx: SimulationContext) -> None:
        now = ctx.engine.get_current_time()
        ctx.engine.add_event(Event(now, self.output.component_id, "RateUpdate", ctx.event.entity, {}))


class RateTransformerComponent(SingleIOComponent):
    """
    Transform-only component for control/rate streams that preserves two-step event flow.

    Event flow:
    ``RateUpdate`` (in) -> self ``Departure`` -> downstream ``RateUpdate`` (out)
    """

    def __init__(
        self,
        component_id: str,
        transform_function: Callable[[SimulationContext], Entity],
        track_state: bool = False,
    ):
        super().__init__(component_id, "RateTransformer", track_state=track_state)
        self.transform_function = transform_function
        self.set_handleable_event("RateUpdate", self.ratetransformer_handle_rateupdate)
        self.set_handleable_event("Departure", self.ratetransformer_handle_departure)

    def ratetransformer_handle_rateupdate(self, ctx: SimulationContext) -> None:
        now = ctx.engine.get_current_time()
        transformed_entity = self.transform_function(ctx)
        ctx.engine.add_event(Event(now, self.component_id, "Departure", transformed_entity, {}))

    def ratetransformer_handle_departure(self, ctx: SimulationContext) -> None:
        now = ctx.engine.get_current_time()
        ctx.engine.add_event(Event(now, self.output.component_id, "RateUpdate", ctx.event.entity, {}))
