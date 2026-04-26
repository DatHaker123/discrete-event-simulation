## Simple system with a source, a delay, and a sink

import sys
from pathlib import Path

# Add project root and src so ``from src.core`` / ``from src.modules`` resolve
_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.core import DelayComponent, Engine, Event, SinkComponent, SourceComponent
from src.modules import get_records_as_printable_string
from src.modules.sim_output import RunOptions
from src.modules.utils import UniformDistribution


def simple_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))
    source = SourceComponent("source", lambda _ctx: {"value": "token"}, UniformDistribution(0, 10))

    delay = DelayComponent("delay", UniformDistribution(0, 10), capacity=1000)
    sink = SinkComponent("sink")
    source.output_to(delay)
    delay.output_to(sink)

    engine.add_component(source)
    engine.add_component(delay)
    engine.add_component(sink)
    engine.run()
    return engine


def post_run(engine: Engine, options: RunOptions) -> None:
    _ = options
    print(get_records_as_printable_string(engine.get_results()))


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
