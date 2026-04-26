## DRS-style threshold crossing: startup rate update -> crusher mode changes -> sink
#
# Rebuilt from drs_crusher_2 with deterministic, piecewise-constant rates. Source emits a
# single startup ``RateUpdate``. Crusher scheduler recomputes expected next mode-change time
# whenever it receives ``RateUpdate`` or local ``ModeChange``, propagates internal processing
# rate downstream, and schedules the next local ``ModeChange``.

import sys
from pathlib import Path
from typing import Any

_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.core import (
    Engine,
    Event,
    SinkComponent,
    SimulationContext
)
from src.modules.operation_mode import OperationMode, OperationModeTrigger
from src.modules.stats import get_records_as_printable_string
from src.modules.sim_output import RunOptions
from src.modules.threshold_crossing import (
    RateSchedulerComponent,
    RateSourceComponent,
    RateTransformerComponent,
    get_advancer_linear_inventory_state,
    get_default_rate_update_handler,
    get_linear_predictor,
)
from src.modules.utils import ConstantDistribution

# --- Tuning: deterministic rates and capacities ---
SOURCE_RATE_TPH = 2.8
SLOW_PROCESSING_TPH = ConstantDistribution(1.25)
FAST_PROCESSING_TPH = ConstantDistribution(3.0)
RATE_CONVERSION_MULTIPLIER = 1.1

# --- Tuning: mode-switch thresholds and horizon ---
HIGH_STOCK = 20.0
LOW_STOCK = 9.0
TIME_LIMIT = 220.0

# --- Initial component.state seeds ---
INITIAL_CRUSHER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "incoming_rate_tph": 0.0,
    "outgoing_rate_tph": 0.0,
    "last_update_time": 0.0,
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
MODE_SLOW = OperationMode("slow", triggers=[stockpile_low_trigger], data={"crush_rate_tph": SLOW_PROCESSING_TPH}, priority=10)
MODE_FAST = OperationMode("fast", triggers=[stockpile_high_trigger], data={"crush_rate_tph": FAST_PROCESSING_TPH}, priority=20)

advance_crusher_inventory_state = get_advancer_linear_inventory_state(
    level_key="stockpile",
    in_rate_key="incoming_rate_tph",
    out_rate_key="outgoing_rate_tph",
    time_key="last_update_time",
    min_level=0.0,
)

crusher_rate_update_handler = get_default_rate_update_handler(
    level_key="stockpile",
    in_rate_key="incoming_rate_tph",
    out_rate_key="outgoing_rate_tph",
    advance_state=advance_crusher_inventory_state,
    incoming_rate_entity_key="rate_tph",
    mode_capacity_key="crush_rate_tph",
)

def convert_rate_a_to_rate_b(ctx: SimulationContext) -> dict[str, Any]:
    """Pure conversion stage: map upstream rate A to downstream rate B."""
    input_rate = float(ctx.event.entity.get("rate_tph", 0.0))
    return {
        "name": "crushed ore",
        "rate_tph": input_rate * RATE_CONVERSION_MULTIPLIER,
    }


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
    startup_rate_entity = {"name": "raw ore", "rate_tph": SOURCE_RATE_TPH}
    source = RateSourceComponent(
        "source",
        lambda _ctx: startup_rate_entity,
        interval=None,
        track_state=False,
    )

    # --- Crusher scheduler ---
    # Handles stockpile dynamics and mode scheduling (RateUpdate + ModeChange).
    crusher = RateSchedulerComponent("crusher", crusher_rate_update_handler, track_state=True)
    crusher.state = INITIAL_CRUSHER_STATE
    crusher.add_mode(MODE_SLOW)
    crusher.add_mode(MODE_FAST)

    # --- Rate converter ---
    # Separate mapping stage from internal processing rate to downstream rate.
    converter = RateTransformerComponent("crusher_rate_converter", convert_rate_a_to_rate_b, track_state=False)

    # --- Sink ---
    sink = SinkComponent("sink", track_state=False)
    sink.set_handleable_event("RateUpdate", sink.sink_handle_arrival)

    # --- Topology and registration ---
    source.output_to(crusher)
    crusher.output_to(converter)
    converter.output_to(sink)

    for c in (source, crusher, converter, sink):
        engine.add_component(c)

    # --- Run ---
    engine.run()
    return engine


def post_run(engine: Engine, options: RunOptions) -> None:
    _ = options
    print(get_records_as_printable_string(engine.get_results()))


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
