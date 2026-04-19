## DRS-style stockpile: constant-rate ore feed -> crusher (mode rules via DRS_utils) -> sink
#
# Same behavior as drs_crusher_tickwise.py, but crusher mode selection uses
# ModeResolver/ModeRule/Constraint from src.modules.DRS_utils.

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
from src.modules.DRS_utils import OperationModeConstraint, OperationModeResolver, OperationModeRule, OperationMode
from src.modules.utils import ConstantDistribution, Distribution, UniformDistribution


# --- Tuning: feed and timing ---
# Source emits one batch per tick (interval); each batch size is drawn from RAW_BATCH.
SOURCE_INTERVAL = ConstantDistribution(1.0)
RAW_BATCH = UniformDistribution(2.4, 3.2)

# --- Tuning: crusher throughput (tonnes per processing step, mode-dependent) ---
SLOW_CRUSH = UniformDistribution(0.9, 1.6)
FAST_CRUSH = UniformDistribution(4.2, 6.5)


# Modes embed tuning in ``data``; rules return these objects—handlers index keys they define.
MODE_SLOW = OperationMode("slow", {"crush_speed": SLOW_CRUSH})
MODE_FAST = OperationMode("fast", {"crush_speed": FAST_CRUSH})

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
    "mode_name": MODE_SLOW.name,
    "total_raw_in": 0.0,
    "total_crushed_out": 0.0,
}


# --- Source block: samples ore batches and updates source counters in state ---
class OreFeedSource(SourceComponent):
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
    Wire source → crusher → sink, run the engine, return a text report and the crusher
    (for plotting ``state_history``). Sections below mirror the setup order.
    """
    # --- Engine ---
    # Queue an initial Generate at t=0; optional PDF visualization; stop at TIME_LIMIT.
    engine = Engine(
        startup_events=[Event(0, "source", "Generate", {}, {})],
        visualize=visualize,
        time_limit=TIME_LIMIT,
    )

    # --- Source ---
    # Constant-interval feeds; state tracks batch counts and last sample for inspection.
    source = OreFeedSource(
        "source",
        RAW_BATCH,
        SOURCE_INTERVAL,
        track_state=True,
    )
    source.state.update(INITIAL_SOURCE_STATE)

    # --- Mode rules (DRS_utils) ---
    # Rules see the same (engine, event, component) triple as handlers. Stock *after* this
    # feed is stockpile + incoming raw_tonnes (matches crush_transform before state write).
    # Each rule's ``mode`` is an ``OperationalMode`` (name + string-keyed ``data``).
    # Higher priority first: fast when high, else slow when low; else resolve() uses current mode_name.
    mode_resolver: OperationModeResolver[OperationMode] = OperationModeResolver()

    stockpile_low = OperationModeConstraint(
        name="stockpile_at_or_below_low",
        check=lambda _eng, ev, comp: float(comp.state["stockpile"])
        + float(ev.entity.get("raw_tonnes", 0.0))
        <= LOW_STOCK,
    )
    stockpile_high = OperationModeConstraint(
        name="stockpile_at_or_above_high",
        check=lambda _eng, ev, comp: float(comp.state["stockpile"])
        + float(ev.entity.get("raw_tonnes", 0.0))
        >= HIGH_STOCK,
    )

    slow_mode_rule = OperationModeRule(
        name="switch_to_slow_at_low_stock",
        mode=MODE_SLOW,
        priority=10,
        constraints=[stockpile_low],
    )
    fast_mode_rule = OperationModeRule(
        name="switch_to_fast_at_high_stock",
        mode=MODE_FAST,
        priority=20,
        constraints=[stockpile_high],
    )

    mode_resolver.add_rule(slow_mode_rule)
    mode_resolver.add_rule(fast_mode_rule)

    # --- Crusher (transformer) ---
    # On each Arrival: resolve mode, sample capacity, update stockpile and counters, emit outbound entity.
    def crush_transform(_engine: Engine, event: Event, comp: Component) -> Entity:
        st = comp.state
        raw_in = float(event.entity.get("raw_tonnes", 0.0))
        stock_before = float(st["stockpile"])

        stock_after_feed = stock_before + raw_in

        current_name = str(st["mode_name"])
        default_mode = MODE_FAST if current_name == MODE_FAST.name else MODE_SLOW
        selected_mode = mode_resolver.resolve(_engine, event, comp, default=default_mode)
        if selected_mode is None:
            selected_mode = default_mode
        st["mode_name"] = selected_mode.name

        capacity = selected_mode.data["crush_speed"].sample()
        crushed = min(stock_after_feed * SWELL_FACTOR, capacity)

        stock_after = stock_after_feed - crushed
        st["stockpile"] = stock_after

        st["total_raw_in"] = float(st["total_raw_in"]) + raw_in
        st["total_crushed_out"] = float(st["total_crushed_out"]) + crushed

        entity: Entity = {
            "crushed_tonnes": crushed,
            "stockpile_after": stock_after,
            "mode": selected_mode.name,
            "raw_in": raw_in,
        }
        return entity

    crusher = TransformerComponent("crusher", crush_transform, track_state=True)
    crusher.state.update(INITIAL_CRUSHER_STATE)

    # --- Sink ---
    # Records arrivals only; no downstream.
    sink = SinkComponent("sink", track_state=False)

    # --- Topology and registration ---
    source.output_to(crusher)
    crusher.output_to(sink)

    for c in (source, crusher, sink):
        engine.add_component(c)

    # --- Run ---
    engine.run()
    return get_records_as_printable_string(engine.get_results()), crusher


# --- CLI: run simulation, print report and stockpile samples; optional --plot ---
if __name__ == "__main__":
    setup_logging(level=logging.INFO, log_file="sim.log", output_dir="output")
    report, crusher = drs_crusher_simulation(visualize=False)
    print(report)
    series = state_key_series_from_history(crusher, "stockpile")
    print("\n# stockpile vs time (t, stockpile) - sample for plotting")
    for t, s in series[:25]:
        print(f"{t:.4f}\t{s:.4f}")
    if len(series) > 25:
        print("...")
    for t, s in series[-12:]:
        print(f"{t:.4f}\t{s:.4f}")

    if "--plot" in sys.argv:
        out = _root / "output" / f"drs_crusher_stockpile_with_utils_{uuid.uuid4()}.png"
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
