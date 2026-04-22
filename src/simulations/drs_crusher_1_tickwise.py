## DRS-style stockpile: constant-rate ore feed → crusher (two modes + thresholds) → sink
#
# The crusher holds a stockpile. Each source tick adds raw ore. Each crusher arrival adds
# incoming mass to the pile, then removes a processing amount drawn from a mode-dependent
# distribution (slow vs fast). Mode switches with hysteresis on stockpile level so the
# stockpile time series tends to oscillate (classic sawtooth / inventory swing).
#
# With track_state=True, ``Component.handle_event`` snapshots ``state`` after each handler.
# Seed full ``state`` (constants + zeros) before ``engine.run()``; handlers only update dynamics.
#
# Source ``state``: feeds, total_feed_tonnes, last_raw_tonnes, nominal_feed_dt.
# Crusher ``state``: stockpile, mode, last_raw_in, last_crushed, arrivals,
#   total_raw_in, total_crushed_out.
# (Crusher also runs a same-time Departure after each Arrival; Departure does not change state,
#   so consecutive duplicate timestamps in raw ``state_history`` are normal.)
#
# Tune: SOURCE_INTERVAL, RAW_BATCH, SLOW_CRUSH, FAST_CRUSH, HIGH_STOCK, LOW_STOCK, TIME_LIMIT
# Run as script: use ``--viz`` for PDF queue frames and ``--plot`` for stockpile figure (UUID-named PNG under output/).

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))  # so ``from src.core`` / ``from src.modules`` work when run as script

from typing import Any

from src.core import (
    Engine,
    Entity,
    Event,
    SinkComponent,
    SimulationContext,
    SourceComponent,
    TransformerComponent,
)
from src.modules.utils import ConstantDistribution, UniformDistribution


# --- Tuning (balance inflow vs slow/fast outflow for visible up/down stockpile) ---
SOURCE_INTERVAL = ConstantDistribution(1.0)  # one arrival per time unit (constant rate)
RAW_BATCH = UniformDistribution(2.4, 3.2)  # tonnes per feed batch (slightly variable)

# Tonnes processed per crusher cycle in each mode (sampled each arrival)
SLOW_CRUSH = UniformDistribution(0.9, 1.6)
FAST_CRUSH = UniformDistribution(4.2, 6.5)

# Hysteresis: above HIGH switch to fast draining; below LOW switch to slow
HIGH_STOCK = 20.0
LOW_STOCK = 9.0

TIME_LIMIT = 220.0

# Full initial ``source.state`` (constants + counters). Generator only bumps counters / last batch.
INITIAL_SOURCE_STATE: dict[str, Any] = {
    "feeds": 0,
    "total_feed_tonnes": 0.0,
    "last_raw_tonnes": 0.0,
}

# Lean initial ``crusher.state``. Transform updates only dynamic values each Arrival.
INITIAL_CRUSHER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "mode": "slow",
    "total_raw_in": 0.0,
    "total_crushed_out": 0.0,
}


def ore_feed_entity(ctx: SimulationContext) -> Entity:
    """Samples ``RAW_BATCH``, updates source ``state``, returns entity for ``Departure``."""
    st = ctx.component.state
    raw = RAW_BATCH.sample()
    st["last_raw_tonnes"] = raw
    st["feeds"] = int(st["feeds"]) + 1
    st["total_feed_tonnes"] = float(st["total_feed_tonnes"]) + raw
    return {"raw_tonnes": raw}


def crush_transform(ctx: SimulationContext) -> Entity:
    st = ctx.component.state
    raw_in = float(ctx.event.entity.get("raw_tonnes", 0.0))
    stock_before = float(st["stockpile"])

    stock_after_feed = stock_before + raw_in

    mode = st["mode"]
    if stock_after_feed >= HIGH_STOCK:
        mode = "fast"
    elif stock_after_feed <= LOW_STOCK:
        mode = "slow"
    st["mode"] = mode

    capacity = FAST_CRUSH.sample() if mode == "fast" else SLOW_CRUSH.sample()
    crushed = min(stock_after_feed, capacity)

    stock_after = stock_after_feed - crushed
    st["stockpile"] = stock_after

    st["total_raw_in"] = float(st["total_raw_in"]) + raw_in
    st["total_crushed_out"] = float(st["total_crushed_out"]) + crushed

    return {
        "crushed_tonnes": crushed,
        "stockpile_after": stock_after,
        "mode": mode,
        "raw_in": raw_in,
    }

def drs_crusher_simulation(visualize: bool = False) -> Engine:
    """
    Build and run source → crusher → sink. Returns the ``Engine`` after ``run()``; use
    ``get_results()`` to reach components (e.g. crusher ``component_id == "crusher"``) for
    ``state_history`` and sink records.
    """
    engine = Engine(
        visualize=visualize,
        time_limit=TIME_LIMIT,
    )
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    source = SourceComponent(
        "source",
        ore_feed_entity,
        interval=SOURCE_INTERVAL,
        track_state=True,
    )
    source.state.update(INITIAL_SOURCE_STATE)


    crusher = TransformerComponent("crusher", crush_transform, track_state=True)
    crusher.state.update(INITIAL_CRUSHER_STATE)

    sink = SinkComponent("sink", track_state=False)

    source.output_to(crusher)
    crusher.output_to(sink)

    for c in (source, crusher, sink):
        engine.add_component(c)

    engine.run()
    return engine


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
