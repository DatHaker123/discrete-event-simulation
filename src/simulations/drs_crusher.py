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
# Crusher ``state``: stockpile, mode, stockpile_before_feed, stockpile_after_feed, last_raw_in,
#   last_crushed, last_capacity_drawn, arrivals, total_raw_in, total_crushed_out,
#   high_threshold, low_threshold.
# (Crusher also runs a same-time Departure after each Arrival; Departure does not change state,
#   so consecutive duplicate timestamps in raw ``state_history`` are normal.)
#
# Tune: SOURCE_INTERVAL, RAW_BATCH, SLOW_CRUSH, FAST_CRUSH, HIGH_STOCK, LOW_STOCK, TIME_LIMIT
# Run as script: ``python -m src.simulations.drs_crusher --plot`` for stockpile figure (saved under output/).

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import logging
from typing import Any

from src.engine import Engine
from src.components import Component, SourceComponent, SinkComponent, TransformerComponent
from src.events import Event
from src.logger import setup_logging
from src.stats import get_records_as_printable_string
from src.utils import ConstantDistribution, Distribution, UniformDistribution


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
    "nominal_feed_dt": SOURCE_INTERVAL.value,
}

# Full initial ``crusher.state``. Thresholds stay fixed; transform updates the rest each Arrival.
INITIAL_CRUSHER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "mode": "slow",
    "arrivals": 0,
    "total_raw_in": 0.0,
    "total_crushed_out": 0.0,
    "high_threshold": HIGH_STOCK,
    "low_threshold": LOW_STOCK,
    "stockpile_before_feed": 0.0,
    "stockpile_after_feed": 0.0,
    "last_raw_in": 0.0,
    "last_crushed": 0.0,
    "last_capacity_drawn": 0.0,
}


class OreFeedSource(SourceComponent):
    """
    On ``Generate``, updates ``state`` (batch counters), then runs
    ``SourceComponent.default_handle_generate`` so interval + Departure scheduling stay default.
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
        self._pending_entity: dict[str, Any] | None = None
        super().__init__(
            component_id,
            self._emit_pending_entity,
            interval=interval,
            track_state=track_state,
        )
        self.set_handleable_event("Generate", self.handle_generate_with_state)

    def handle_generate_with_state(
        self, engine: Engine, event: Event, component: Component
    ) -> None:
        st = component.state
        raw = self._raw_batch.sample()
        st["last_raw_tonnes"] = raw
        st["feeds"] = int(st["feeds"]) + 1
        st["total_feed_tonnes"] = float(st["total_feed_tonnes"]) + raw
        self._pending_entity = {"raw_tonnes": raw}
        try:
            SourceComponent.default_handle_generate(self, engine, event, component)
        finally:
            self._pending_entity = None

    def _emit_pending_entity(self, _engine: Engine, _component: Component) -> dict[str, Any]:
        assert self._pending_entity is not None
        return self._pending_entity


def drs_crusher_simulation(visualize: bool = False) -> tuple[str, TransformerComponent]:
    """
    Run source → crusher → sink. Returns (stats text, crusher) so callers can plot
    ``stockpile_series_from_crusher(crusher)``.
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

    def crush_transform(_engine: Engine, event: Event, comp: Component) -> dict[str, Any]:
        st = comp.state
        hi, lo = st["high_threshold"], st["low_threshold"]
        raw_in = float(event.entity.get("raw_tonnes", 0.0))
        stock_before = float(st["stockpile"])
        st["stockpile_before_feed"] = stock_before

        stock_after_feed = stock_before + raw_in
        st["stockpile_after_feed"] = stock_after_feed
        st["last_raw_in"] = raw_in

        mode = st["mode"]
        if stock_after_feed >= hi:
            mode = "fast"
        elif stock_after_feed <= lo:
            mode = "slow"
        st["mode"] = mode

        capacity = FAST_CRUSH.sample() if mode == "fast" else SLOW_CRUSH.sample()
        st["last_capacity_drawn"] = capacity
        crushed = min(stock_after_feed, capacity)
        st["last_crushed"] = crushed

        stock_after = stock_after_feed - crushed
        st["stockpile"] = stock_after

        st["arrivals"] = int(st["arrivals"]) + 1
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


def stockpile_series_from_crusher(crusher: TransformerComponent) -> list[tuple[float, float]]:
    """(time, stockpile) from crusher ``state_history`` (one point per time; Departure repeats same t)."""
    by_t: dict[float, float] = {}
    for t, snap in crusher.state_history:
        if "stockpile" in snap:
            by_t[float(t)] = float(snap["stockpile"])
    return sorted(by_t.items())


def crusher_snapshots(crusher: TransformerComponent) -> list[tuple[float, dict[str, Any]]]:
    """Full ``(time, state_dict)`` rows from ``state_history`` (same keys as ``crusher.state``)."""
    return list(crusher.state_history)


def plot_stockpile_series(
    series: list[tuple[float, float]],
    *,
    save_path: Path | None = None,
    show: bool = True,
) -> None:
    """Plot ``(time, stockpile)`` from ``stockpile_series_from_crusher`` with hysteresis lines."""
    import matplotlib.pyplot as plt

    if not series:
        return
    t, y = zip(*series)
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(t, y, color="C0", lw=1.2, label="stockpile")
    ax.axhline(HIGH_STOCK, color="C3", ls="--", lw=0.9, alpha=0.85, label="high / low")
    ax.axhline(LOW_STOCK, color="C2", ls="--", lw=0.9, alpha=0.85)
    ax.set_xlabel("time")
    ax.set_ylabel("stockpile (tonnes)")
    ax.set_title("Crusher stockpile vs time")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=120)
    if show:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    setup_logging(level=logging.INFO, log_file="sim.log", output_dir="output")
    report, crusher = drs_crusher_simulation(visualize=False)
    print(report)
    series = stockpile_series_from_crusher(crusher)
    print("\n# stockpile vs time (t, stockpile) — sample for plotting")
    for t, s in series[:25]:
        print(f"{t:.4f}\t{s:.4f}")
    if len(series) > 25:
        print("...")
    for t, s in series[-12:]:
        print(f"{t:.4f}\t{s:.4f}")

    if "--plot" in sys.argv:
        out = _root / "output" / "drs_crusher_stockpile.png"
        plot_stockpile_series(series, save_path=out, show=True)
        print(f"\nSaved figure to {out}")
