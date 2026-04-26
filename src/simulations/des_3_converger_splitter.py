## DES: two sources (A/B) -> converger -> delay -> splitter -> two sinks

import sys
from pathlib import Path

# Add project root and src so ``from src.core`` / ``from src.modules`` resolve
_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.core import (
    ConvergerComponent,
    DelayComponent,
    Engine,
    Entity,
    Event,
    SimulationContext,
    SinkComponent,
    SourceComponent,
    SplitterComponent,
)
from src.modules import get_records_as_printable_string
from src.modules.sim_output import RunOptions
from src.modules.utils import UniformDistribution

SOURCE_A_INTERVAL = UniformDistribution(0.8, 1.4)
SOURCE_B_INTERVAL = UniformDistribution(0.9, 1.5)
SOURCE_A_WEIGHT = UniformDistribution(8.0, 12.0)
SOURCE_B_WEIGHT = UniformDistribution(6.0, 10.0)
DELAY_INTERVAL = UniformDistribution(0.2, 0.6)
TIME_LIMIT = 5.0


def des_two_sources_converger_delay_splitter_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source_a", "Generate", {}, {}))
    engine.add_startup_event(Event(0, "source_b", "Generate", {}, {}))

    def generate_substance_a(_ctx: SimulationContext) -> Entity:
        return {"name": "substance A", "weight": SOURCE_A_WEIGHT.sample()}

    def generate_substance_b(_ctx: SimulationContext) -> Entity:
        return {"name": "substance B", "weight": SOURCE_B_WEIGHT.sample()}

    def split_evenly(ctx: SimulationContext) -> dict[str, Entity]:
        incoming = ctx.entity
        half_weight = float(incoming.get("weight", 0.0)) / 2.0
        base_name = str(incoming.get("name", "substance"))
        return {
            "sink_left": {"name": base_name, "weight": half_weight, "split_path": "left"},
            "sink_right": {"name": base_name, "weight": half_weight, "split_path": "right"},
        }

    source_a = SourceComponent("source_a", generate_substance_a, interval=SOURCE_A_INTERVAL)
    source_b = SourceComponent("source_b", generate_substance_b, interval=SOURCE_B_INTERVAL)
    converger = ConvergerComponent("converger")
    delay = DelayComponent("delay", delay_interval=DELAY_INTERVAL, capacity=500)
    splitter = SplitterComponent("splitter", split_evenly)
    sink_left = SinkComponent("sink_left")
    sink_right = SinkComponent("sink_right")

    for component in (source_a, source_b, converger, delay, splitter, sink_left, sink_right):
        engine.add_component(component)

    engine.connect(source_a, converger)
    engine.connect(source_b, converger)
    engine.connect(converger, delay)
    engine.connect(delay, splitter)
    engine.connect(splitter, sink_left)
    engine.connect(splitter, sink_right)

    engine.run()
    return engine


def post_run(engine: Engine, options: RunOptions) -> None:
    _ = options
    print(get_records_as_printable_string(engine.get_results()))


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
