## DRS-style stockpile: constant-rate ore feed -> crusher (mode rules via operation_mode) -> sink
#
# Same behavior as drs_crusher_tickwise.py, but crusher mode selection uses
# ModeResolver/ModeRule/Constraint from src.modules.operation_mode.


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
    Entity,
    Event,
    SinkComponent,
    SimulationContext,
    SourceComponent,
    TransformerComponent,
)
from src.modules.operation_mode import OperationModeTrigger, OperationMode, with_operational_mode
from src.modules.utils import ConstantDistribution, UniformDistribution


# --- Tuning: feed and timing ---
# Source emits one batch per tick (interval); each batch size is drawn from RAW_BATCH.
SOURCE_INTERVAL = ConstantDistribution(1.0)
RAW_BATCH = UniformDistribution(2.4, 3.2)

# --- Tuning: crusher throughput (tonnes per processing step, mode-dependent) ---
SLOW_CRUSH = UniformDistribution(0.9, 1.6)
FAST_CRUSH = UniformDistribution(4.2, 6.5)


# Modes embed tuning in ``data``; rules return these objects—handlers index keys they define.
check_stockpile_high = lambda ctx: float(ctx.component.state["stockpile"]) >= HIGH_STOCK
check_stockpile_low = lambda ctx: float(ctx.component.state["stockpile"]) <= LOW_STOCK
stockpile_high_trigger = OperationModeTrigger(name="stockpile_too_high", check=check_stockpile_high)
stockpile_low_trigger = OperationModeTrigger(name="stockpile_too_low", check=check_stockpile_low)
MODE_SLOW = OperationMode("slow", triggers=[stockpile_low_trigger], data={"crush_speed": SLOW_CRUSH})
MODE_FAST = OperationMode("fast", triggers=[stockpile_high_trigger], data={"crush_speed": FAST_CRUSH})

# --- Tuning: stockpile hysteresis (mode switches when projected level crosses these) ---
HIGH_STOCK = 20.0
LOW_STOCK = 9.0

# --- Simulation horizon ---
TIME_LIMIT = 220.0

# --- Processing model: multiplicative factor on stock before comparing to capacity ---
SWELL_FACTOR = 1.1

# --- Initial component.state seeds (handlers only mutate dynamics after this) ---
INITIAL_SOURCE_STATE: dict[str, Any] = {
    "feeds": 0,
    "total_feed_tonnes": 0.0,
    "last_raw_tonnes": 0.0,
}

INITIAL_CRUSHER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "total_raw_in": 0.0,
    "total_crushed_out": 0.0,
}

# This defines the entity that is emitted by the source component.
def ore_feed_entity(ctx: SimulationContext) -> Entity:
    """Samples ``RAW_BATCH``, updates source ``state``, returns entity for ``Departure``."""
    st = ctx.component.state
    raw = RAW_BATCH.sample()
    st["last_raw_tonnes"] = raw
    st["feeds"] = int(st["feeds"]) + 1
    st["total_feed_tonnes"] = float(st["total_feed_tonnes"]) + raw
    return {"raw_tonnes": raw}


TransformerComponentWithMode = with_operational_mode(TransformerComponent)


def crush_transform(ctx: SimulationContext) -> Entity:
    st = ctx.component.state
    raw_in = float(ctx.event.entity.get("raw_tonnes", 0.0))

    # 1) Apply incoming feed first so mode triggers see post-feed stock.
    st["stockpile"] = float(st["stockpile"]) + raw_in
    st["total_raw_in"] = float(st["total_raw_in"]) + raw_in

    # 2) Resolve mode from updated component state.
    selected_mode = ctx.component.update_current_mode(ctx)

    # 3) Execute crushing with the selected mode and commit state.
    capacity = selected_mode.data["crush_speed"].sample()
    crushed = min(float(st["stockpile"]) * SWELL_FACTOR, capacity)
    stock_after = float(st["stockpile"]) - crushed
    st["stockpile"] = stock_after
    st["total_crushed_out"] = float(st["total_crushed_out"]) + crushed

    out: Entity = {
        "crushed_tonnes": crushed,
        "stockpile_after": stock_after,
        "mode": selected_mode.name,
        "raw_in": raw_in,
    }
    return out


def drs_crusher_simulation(visualize: bool = False) -> Engine:
    """
    Build and run source → crusher → sink. Returns the ``Engine`` after ``run()``; use
    ``get_results()`` to reach components (e.g. crusher ``component_id == "crusher"``).
    """
    # --- Engine ---
    # Queue an initial Generate at t=0; optional PDF visualization; stop at TIME_LIMIT.
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    # --- Source ---
    # Constant-interval feeds; state tracks batch counts and last sample for inspection.
    source = SourceComponent("source", ore_feed_entity, interval=SOURCE_INTERVAL, track_state=True)
    source.state = INITIAL_SOURCE_STATE

    # --- Crusher (transformer) ---
    # On each Arrival: resolve mode, sample capacity, update stockpile and counters, emit outbound entity.
    crusher = TransformerComponentWithMode("crusher", crush_transform, track_state=True)
    crusher.add_mode(MODE_SLOW)
    crusher.add_mode(MODE_FAST)

    crusher.state = INITIAL_CRUSHER_STATE

    # --- Sink ---
    # Records arrivals only; no downstream.
    sink = SinkComponent("sink", track_state=False)

    # --- Topology and registration ---
    source.output_to(crusher)
    crusher.output_to(sink)

    engine.add_component(source)
    engine.add_component(crusher)
    engine.add_component(sink)

    # --- Run ---
    engine.run()
    return engine


# --- CLI: run simulation, print report and stockpile samples; optional --viz / --plot ---
if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
