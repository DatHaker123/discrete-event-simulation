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
# Run as script: ``python -m src.simulations.drs_crusher --plot`` for stockpile figure (UUID-named PNG under output/).

import sys
import uuid
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))  # so ``from src.core`` / ``from src.modules`` work when run as script

import logging
from typing import Any

from src.core import (
    Component,
    Engine,
    Entity,
    Event,
    SinkComponent,
    SourceComponent,
    TransformerComponent,
)
from src.modules import (
    get_records_as_printable_string,
    plot_time_series,
    setup_logging,
    state_key_series_from_history,
)
from src.modules.utils import ConstantDistribution, Distribution, UniformDistribution


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


class OreFeedSource(SourceComponent):
    """
    ``entity_generator`` samples ore, updates source ``state``, and returns the emitted entity.
    """

    def __init__(
        self,
        component_id: str,
        raw_batch: UniformDistribution,
        interval: Distribution,
        *,
        track_state: bool = False,
    ):
        self._raw_batch = raw_batch
        super().__init__(
            component_id,
            self._generate_entity,
            interval=interval,
            track_state=track_state,
        )

    def _generate_entity(
        self, _engine: Engine, _event: Event, component: Component
    ) -> Entity:
        st = component.state
        raw = self._raw_batch.sample()
        st["last_raw_tonnes"] = raw
        st["feeds"] = int(st["feeds"]) + 1
        st["total_feed_tonnes"] = float(st["total_feed_tonnes"]) + raw
        return {"raw_tonnes": raw}


def drs_crusher_simulation(visualize: bool = False) -> tuple[str, TransformerComponent]:
    """
    Run source → crusher → sink. Returns (stats text, crusher). Plot stockpile with
    ``state_key_series_from_history(crusher, "stockpile")`` (see ``src.modules.stats``).
    """
    engine = Engine(
        startup_events=[Event(0, "source", "Generate", None, {})],
        visualize=visualize,
        time_limit=TIME_LIMIT,
    )

    source = OreFeedSource(
        "source",
        RAW_BATCH,
        SOURCE_INTERVAL,
        track_state=True,
    )
    source.state.update(INITIAL_SOURCE_STATE)

    def crush_transform(_engine: Engine, event: Event, comp: Component) -> Entity:
        st = comp.state
        raw_in = float(event.entity.get("raw_tonnes", 0.0))
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

    crusher = TransformerComponent("crusher", crush_transform, track_state=True)
    crusher.state.update(INITIAL_CRUSHER_STATE)

    sink = SinkComponent("sink", track_state=False)

    source.output_to(crusher)
    crusher.output_to(sink)

    for c in (source, crusher, sink):
        engine.add_component(c)

    engine.run()
    return get_records_as_printable_string(engine.get_results()), crusher


if __name__ == "__main__":
    setup_logging(level=logging.INFO, log_file="sim.log", output_dir="output")
    report, crusher = drs_crusher_simulation(visualize=False)
    print(report)
    series = state_key_series_from_history(crusher, "stockpile")
    print("\n# stockpile vs time (t, stockpile) — sample for plotting")
    for t, s in series[:25]:
        print(f"{t:.4f}\t{s:.4f}")
    if len(series) > 25:
        print("...")
    for t, s in series[-12:]:
        print(f"{t:.4f}\t{s:.4f}")

    if "--plot" in sys.argv:
        out = _root / "output" / f"drs_crusher_stockpile_{uuid.uuid4()}.png"
        plot_time_series(
            series,
            x_label="time",
            y_label="stockpile (tonnes)",
            title="Crusher stockpile vs time",
            line_label="stockpile",
            horizontal_lines=((HIGH_STOCK, "high"), (LOW_STOCK, "low")),
            save_path=out,
            show=True,
        )
        print(f"\nSaved figure to {out}")
