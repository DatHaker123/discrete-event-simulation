## DRS-style threshold crossing: startup rate update -> crusher mode changes -> sink
#
# Rebuilt from drs_crusher_2 with deterministic, piecewise-constant rates. Source emits a
# single startup ``RateUpdate``. Crusher recomputes expected next mode-change time whenever
# it receives ``RateUpdate`` (startup or self-scheduled), propagates its new output rate
# downstream, and schedules the next local ``RateUpdate``.

import sys
import uuid
from pathlib import Path
from typing import Any

_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import logging

from src.core import (
    Engine,
    Entity,
    Event,
    SinkComponent,
    SimulationContext,
    TransformerComponent,
)
from src.modules import (
    get_records_as_printable_string,
    plot_time_series,
    setup_logging,
    state_key_series_from_history,
)
from src.modules.operation_mode import OperationMode, OperationModeTrigger, with_operational_mode
from src.modules.threshold_crossing import RateSourceComponent, get_linear_predictor
from src.modules.utils import ConstantDistribution

# --- Tuning: deterministic rates and capacities ---
SOURCE_RATE_TPH = 2.8
SLOW_CAPACITY_TPH = ConstantDistribution(1.25)
FAST_CAPACITY_TPH = ConstantDistribution(5.35)

# --- Tuning: mode-switch thresholds and horizon ---
HIGH_STOCK = 20.0
LOW_STOCK = 9.0
TIME_LIMIT = 1000.0
SWELL_FACTOR = 1.1

# --- Numerical guard for immediate re-schedules ---
EPS_TIME = 1e-9

# --- Initial component.state seeds ---
INITIAL_SOURCE_STATE: dict[str, Any] = {
    "startup_rate_sent": False,
}

INITIAL_CRUSHER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "incoming_rate_tph": 0.0,
    "outgoing_rate_tph": 0.0,
    "last_update_time": 0.0,
    "total_raw_in": 0.0,
    "total_crushed_out": 0.0,
}


# --- Threshold-crossing predictors (piecewise-constant linear model) ---
predict_time_to_high = get_linear_predictor(
    state_key="stockpile",
    threshold=HIGH_STOCK,
    crossing="at_or_above",
)
predict_time_to_low = get_linear_predictor(
    state_key="stockpile",
    threshold=LOW_STOCK,
    crossing="at_or_below",
)


# --- Trigger checks: is the mode condition currently true? ---
check_stockpile_high = lambda ctx: float(ctx.component.state["stockpile"]) >= HIGH_STOCK
check_stockpile_low = lambda ctx: float(ctx.component.state["stockpile"]) <= LOW_STOCK
stockpile_high_trigger = OperationModeTrigger(name="stockpile_at_or_above_high", check=check_stockpile_high, expected_next_trigger_time=predict_time_to_high)
stockpile_low_trigger = OperationModeTrigger(name="stockpile_at_or_below_low", check=check_stockpile_low, expected_next_trigger_time=predict_time_to_low)
MODE_SLOW = OperationMode("slow", triggers=[stockpile_low_trigger], data={"crush_rate_tph": SLOW_CAPACITY_TPH}, priority=10)
MODE_FAST = OperationMode("fast", triggers=[stockpile_high_trigger], data={"crush_rate_tph": FAST_CAPACITY_TPH}, priority=20)

TransformerComponentWithMode = with_operational_mode(TransformerComponent)


def startup_rate_entity(ctx: SimulationContext) -> Entity:
    ctx.component.state["startup_rate_sent"] = True
    return {"rate_tph": SOURCE_RATE_TPH}


def _advance_inventory_to_now(ctx: SimulationContext) -> None:
    """Integrate stockpile forward using piecewise-constant in/out rates."""
    st = ctx.component.state
    now = ctx.engine.get_current_time()
    last_t = float(st["last_update_time"])
    dt = max(0.0, now - last_t)
    if dt <= 0.0:
        st["last_update_time"] = now
        return

    in_rate = float(st["incoming_rate_tph"])
    out_rate = float(st["outgoing_rate_tph"])
    new_stock = max(0.0, float(st["stockpile"]) + (in_rate - out_rate) * dt)

    st["stockpile"] = new_stock
    st["total_raw_in"] = float(st["total_raw_in"]) + in_rate * dt
    st["total_crushed_out"] = float(st["total_crushed_out"]) + out_rate * dt
    st["last_update_time"] = now


def crusher_rate_update_handler(ctx: SimulationContext) -> None:
    """
    Handle incoming/local RateUpdate:
    - advance inventory to now
    - apply incoming rate change
    - resolve current mode and outgoing rate
    - propagate downstream rate
    - schedule next local mode-change update
    """
    engine = ctx.engine
    comp = ctx.component
    st = comp.state
    now = engine.get_current_time()

    # Propagate previous piecewise-constant rates up to current event time.
    _advance_inventory_to_now(ctx)

    # External (upstream) rate update replaces incoming rate.
    if "rate_tph" in ctx.event.entity:
        st["incoming_rate_tph"] = float(ctx.event.entity["rate_tph"])

    selected_mode = comp.update_current_mode(ctx)
    if selected_mode is None:
        raise RuntimeError("No operational mode selected for crusher.")

    capacity_tph = float(selected_mode.data["crush_rate_tph"].sample())
    out_rate_tph = min(float(st["incoming_rate_tph"]) * SWELL_FACTOR, capacity_tph)
    st["outgoing_rate_tph"] = out_rate_tph

    # Propagate current output rate downstream as a RateUpdate.
    downstream = Event(
        now,
        comp.output.component_id,
        "RateUpdate",
        {
            "rate_tph": out_rate_tph,
            "mode": selected_mode.name,
            "stockpile": float(st["stockpile"]),
            "incoming_rate_tph": float(st["incoming_rate_tph"]),
        },
        {},
    )
    engine.add_event(downstream)

    # Predict next mode-change crossing under piecewise-constant rates and schedule local update.
    delta = {"stockpile": float(st["incoming_rate_tph"]) - float(st["outgoing_rate_tph"])}
    next_mode, next_t = comp.get_next_mode_change(ctx, delta)
    if next_mode is None or next_t is None:
        return
    if next_t <= now + EPS_TIME:
        next_t = now + EPS_TIME
    if engine.time_limit is not None and next_t >= engine.time_limit:
        return

    # Use component versioning to invalidate earlier projected updates.
    comp.advance_version()
    engine.add_event(Event(next_t, comp.component_id, "RateUpdate", {}, {}))


def drs_crusher_simulation(visualize: bool = False) -> Engine:
    """
    Build and run source -> crusher -> sink (threshold-crossing variant).
    Returns the Engine after run().
    """
    # --- Engine ---
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    # --- Source ---
    # Startup-only source: emits one rate update at t=0 (no interval self-scheduling).
    source = RateSourceComponent(
        "source",
        startup_rate_entity,
        interval=None,
        track_state=True,
    )
    source.state = INITIAL_SOURCE_STATE

    # --- Crusher ---
    # Transformer used as a generic single-output block with mode manager mixin.
    crusher = TransformerComponentWithMode("crusher", lambda _ctx: {}, track_state=True)
    crusher.state = INITIAL_CRUSHER_STATE
    crusher.add_mode(MODE_SLOW)
    crusher.add_mode(MODE_FAST)
    crusher.set_handleable_event("RateUpdate", crusher_rate_update_handler)

    # --- Sink ---
    sink = SinkComponent("sink", track_state=False)
    sink.set_handleable_event("RateUpdate", sink.sink_handle_arrival)

    # --- Topology and registration ---
    source.output_to(crusher)
    crusher.output_to(sink)

    for c in (source, crusher, sink):
        engine.add_component(c)

    # --- Run ---
    engine.run()
    return engine


if __name__ == "__main__":
    setup_logging(level=logging.INFO, log_file="sim.log", output_dir="output")
    engine = drs_crusher_simulation(visualize=False)

    components = engine.get_results()
    print(get_records_as_printable_string(components))
    crusher = next(c for c in components if c.component_id == "crusher")
    series = state_key_series_from_history(crusher, "stockpile")

    print("\n# stockpile vs time (t, stockpile) - sample for plotting")
    for t, s in series[:25]:
        print(f"{t:.4f}\t{s:.4f}")
    if len(series) > 25:
        print("...")
    for t, s in series[-12:]:
        print(f"{t:.4f}\t{s:.4f}")

    if "--plot" in sys.argv:
        out = _root / "output" / f"drs_crusher_3_threshold_stockpile_{uuid.uuid4()}.png"
        plot_time_series(
            series,
            x_label="time",
            y_label="stockpile (tonnes)",
            title="Crusher stockpile vs time (threshold-crossing)",
            line_label="stockpile",
            horizontal_lines=((HIGH_STOCK, "high"), (LOW_STOCK, "low")),
            save_path=out,
            show=True,
        )
        print(f"\nSaved figure to {out}")
