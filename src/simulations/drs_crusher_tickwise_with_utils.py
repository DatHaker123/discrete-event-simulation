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
from src.modules.DRS_utils import Constraint, ModeResolver, ModeRule
from src.modules.utils import ConstantDistribution, Distribution, UniformDistribution


SOURCE_INTERVAL = ConstantDistribution(1.0)
RAW_BATCH = UniformDistribution(2.4, 3.2)

SLOW_CRUSH = UniformDistribution(0.9, 1.6)
FAST_CRUSH = UniformDistribution(4.2, 6.5)

HIGH_STOCK = 20.0
LOW_STOCK = 9.0

TIME_LIMIT = 220.0

SWELL_FACTOR = 1.1

INITIAL_SOURCE_STATE: dict[str, Any] = {
    "feeds": 0,
    "total_feed_tonnes": 0.0,
    "last_raw_tonnes": 0.0,
}

INITIAL_CRUSHER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "mode": "slow",
    "total_raw_in": 0.0,
    "total_crushed_out": 0.0,
}


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

    mode_resolver = ModeResolver()
    mode_resolver.add_rule(
        ModeRule(
            name="switch_to_slow_at_low_stock",
            mode="slow",
            priority=10,
            constraints=[
                Constraint(
                    name="stockpile_at_or_below_low",
                    check=lambda _eng, ev, comp: float(comp.state["stockpile"])
                    + (
                        float(ev.entity.get("raw_tonnes", 0.0))
                        if isinstance(ev.entity, dict)
                        else 0.0
                    )
                    <= LOW_STOCK,
                )
            ],
        )
    )
    mode_resolver.add_rule(
        ModeRule(
            name="switch_to_fast_at_high_stock",
            mode="fast",
            priority=20,
            constraints=[
                Constraint(
                    name="stockpile_at_or_above_high",
                    check=lambda _eng, ev, comp: float(comp.state["stockpile"])
                    + (
                        float(ev.entity.get("raw_tonnes", 0.0))
                        if isinstance(ev.entity, dict)
                        else 0.0
                    )
                    >= HIGH_STOCK,
                )
            ],
        )
    )

    def crush_transform(_engine: Engine, event: Event, comp: Component) -> Entity:
        st = comp.state
        raw_in = float(event.entity.get("raw_tonnes", 0.0))
        stock_before = float(st["stockpile"])

        stock_after_feed = stock_before + raw_in

        current_mode = str(st["mode"])
        mode = mode_resolver.resolve(_engine, event, comp, default=current_mode)
        if mode is None:
            mode = current_mode
        st["mode"] = mode

        capacity = FAST_CRUSH.sample() if mode == "fast" else SLOW_CRUSH.sample()
        crushed = min(stock_after_feed * SWELL_FACTOR, capacity)

        stock_after = stock_after_feed - crushed
        st["stockpile"] = stock_after

        st["total_raw_in"] = float(st["total_raw_in"]) + raw_in
        st["total_crushed_out"] = float(st["total_crushed_out"]) + crushed

        entity: Entity = {
            "crushed_tonnes": crushed,
            "stockpile_after": stock_after,
            "mode": mode,
            "raw_in": raw_in,
        }
        return entity

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
