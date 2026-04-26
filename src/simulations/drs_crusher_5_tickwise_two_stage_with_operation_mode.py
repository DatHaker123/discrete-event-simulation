## Two-stage tickwise DRS: source -> crusher (mode-controlled) -> grinder (mode-controlled) -> sink
#
# This extends drs_crusher_2 by chaining a grinder after the crusher. Both machines use
# high/low hysteresis modes, but with intentionally different capacities and thresholds so
# their switches do not synchronize. The resulting downstream (grinder) stockpile should
# exhibit a richer pattern than a single-machine model.

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
from src.modules.sim_output import (
    RunOptions,
    SimulationPlot,
    print_series_sample,
)
from src.modules.stats import get_records_as_printable_string, state_key_series_from_history
from src.modules.utils import ConstantDistribution, UniformDistribution


# --- Tuning: feed and timing ---
SOURCE_INTERVAL = ConstantDistribution(1.0)
RAW_BATCH = UniformDistribution(7.0, 7.5)

# --- Crusher tuning ---
CRUSHER_SLOW_CAPACITY = UniformDistribution(6.0, 6.5)
CRUSHER_FAST_CAPACITY = UniformDistribution(8.0, 8.5)
CRUSHER_HIGH_STOCK = 24.0
CRUSHER_LOW_STOCK = 10.5
CRUSHER_SWELL_FACTOR = 1.3

# --- Grinder tuning (intentionally offset from crusher) ---
GRINDER_SLOW_CAPACITY = UniformDistribution(6.0, 6.2)
GRINDER_FAST_CAPACITY = UniformDistribution(8.5, 8.7)
GRINDER_HIGH_STOCK = 20.5
GRINDER_LOW_STOCK = 8.5
GRINDER_YIELD = 1.0

TIME_LIMIT = 320.0


INITIAL_SOURCE_STATE: dict[str, Any] = {
    "feeds": 0,
    "total_feed_tonnes": 0.0,
    "last_raw_tonnes": 0.0,
}

INITIAL_CRUSHER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "mode": "slow",
    "total_in": 0.0,
    "total_out": 0.0,
}

INITIAL_GRINDER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "mode": "slow",
    "total_in": 0.0,
    "total_out": 0.0,
}

def ore_feed_entity(ctx: SimulationContext) -> Entity:
    st = ctx.component.state
    raw = RAW_BATCH.sample()
    st["last_raw_tonnes"] = raw
    st["feeds"] = int(st["feeds"]) + 1
    st["total_feed_tonnes"] = float(st["total_feed_tonnes"]) + raw
    return {"raw_tonnes": raw}


TransformerComponentWithMode = with_operational_mode(TransformerComponent)


def crusher_transform(ctx: SimulationContext) -> Entity:
    st = ctx.component.state
    raw_in = float(ctx.event.entity.get("raw_tonnes", 0.0))

    st["stockpile"] = float(st["stockpile"]) + raw_in
    st["total_in"] = float(st["total_in"]) + raw_in

    selected_mode = ctx.component.update_current_mode(ctx)
    st["mode"] = selected_mode.name
    capacity = float(selected_mode.data["throughput_tph"].sample())
    crushed = min(float(st["stockpile"]) * CRUSHER_SWELL_FACTOR, capacity)

    st["stockpile"] = float(st["stockpile"]) - crushed
    st["total_out"] = float(st["total_out"]) + crushed

    return {
        "crushed_tonnes": crushed,
        "crusher_mode": selected_mode.name,
    }


def grinder_transform(ctx: SimulationContext) -> Entity:
    st = ctx.component.state
    infeed = float(ctx.event.entity.get("crushed_tonnes", 0.0))

    st["stockpile"] = float(st["stockpile"]) + infeed
    st["total_in"] = float(st["total_in"]) + infeed

    selected_mode = ctx.component.update_current_mode(ctx)
    st["mode"] = selected_mode.name
    capacity = float(selected_mode.data["throughput_tph"].sample())
    processed = min(float(st["stockpile"]), capacity)
    final_out = processed * GRINDER_YIELD

    st["stockpile"] = float(st["stockpile"]) - processed
    st["total_out"] = float(st["total_out"]) + final_out

    return {
        "ground_tonnes": final_out,
        "grinder_mode": selected_mode.name,
    }


crusher_high_trigger = OperationModeTrigger(
    name="crusher_stock_high",
    check=lambda ctx: float(ctx.component.state["stockpile"]) >= CRUSHER_HIGH_STOCK,
)
crusher_low_trigger = OperationModeTrigger(
    name="crusher_stock_low",
    check=lambda ctx: float(ctx.component.state["stockpile"]) <= CRUSHER_LOW_STOCK,
)
CRUSHER_MODE_SLOW = OperationMode(
    "slow",
    triggers=[crusher_low_trigger],
    data={"throughput_tph": CRUSHER_SLOW_CAPACITY},
)
CRUSHER_MODE_FAST = OperationMode(
    "fast",
    triggers=[crusher_high_trigger],
    data={"throughput_tph": CRUSHER_FAST_CAPACITY},
)

grinder_high_trigger = OperationModeTrigger(
    name="grinder_stock_high",
    check=lambda ctx: float(ctx.component.state["stockpile"]) >= GRINDER_HIGH_STOCK,
)
grinder_low_trigger = OperationModeTrigger(
    name="grinder_stock_low",
    check=lambda ctx: float(ctx.component.state["stockpile"]) <= GRINDER_LOW_STOCK,
)
GRINDER_MODE_SLOW = OperationMode(
    "slow",
    triggers=[grinder_low_trigger],
    data={"throughput_tph": GRINDER_SLOW_CAPACITY},
)
GRINDER_MODE_FAST = OperationMode(
    "fast",
    triggers=[grinder_high_trigger],
    data={"throughput_tph": GRINDER_FAST_CAPACITY},
)


def drs_crusher_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    source = SourceComponent("source", ore_feed_entity, interval=SOURCE_INTERVAL, track_state=True)
    source.state = INITIAL_SOURCE_STATE

    crusher = TransformerComponentWithMode("crusher", crusher_transform, track_state=True)
    crusher.add_mode(CRUSHER_MODE_SLOW)
    crusher.add_mode(CRUSHER_MODE_FAST)
    crusher.state = INITIAL_CRUSHER_STATE

    grinder = TransformerComponentWithMode("grinder", grinder_transform, track_state=True)
    grinder.add_mode(GRINDER_MODE_SLOW)
    grinder.add_mode(GRINDER_MODE_FAST)
    grinder.state = INITIAL_GRINDER_STATE

    sink = SinkComponent("sink", track_state=False)

    source.output_to(crusher)
    crusher.output_to(grinder)
    grinder.output_to(sink)

    for c in (source, crusher, grinder, sink):
        engine.add_component(c)

    engine.run()
    return engine


def post_run(engine: Engine, options: RunOptions, module: object | None = None) -> None:
    _ = module
    print(get_records_as_printable_string(engine.get_results()))

    target_component_id = "crusher"
    target_component = next((c for c in engine.get_results() if c.component_id == target_component_id), None)

    # series = state_key_series_from_history(target_component, "stockpile")
    # print(f"\n# stockpile component: {target_component_id}")
    # print_series_sample(series, label=f"{target_component_id} stockpile")

    if not options.plot:
        return

    plotter = SimulationPlot(
        state_history=target_component.state_history,
        y_key="stockpile",
        name=f"{target_component_id} stockpile vs time",
    )
    plotter.add_horizontal_line(CRUSHER_HIGH_STOCK, label="high", color="C3")
    plotter.add_horizontal_line(CRUSHER_LOW_STOCK, label="low", color="C2")

    plotter.plot_mode_changes()
    figure_path = plotter.render(
        output_name_prefix=f"{Path(__file__).stem}_{target_component_id}_stockpile",
        show=True,
    )
    if figure_path is not None:
        print(f"\nSaved figure to {figure_path}")


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
