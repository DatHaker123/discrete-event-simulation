## Simple system with a source, a delay, and a sink

import sys
from pathlib import Path

# Add project root and src so both "src.xxx" and internal "from events import" etc. resolve
_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import logging
from src.engine import Engine
from src.components import SourceComponent, DelayComponent, SinkComponent
from src.logger import setup_logging
from src.stats import get_records_as_printable_string
from src.utils import UniformDistribution
from src.events import Event


def simple_simulation():
    engine = Engine(startup_events=[Event(0, "source", "Generate", None, {})], visualize=True)
    source = SourceComponent("source", lambda _e, _comp: "token", UniformDistribution(0, 10))

    delay = DelayComponent("delay", UniformDistribution(0, 10), capacity=1000)
    sink = SinkComponent("sink")
    source.output_to(delay)
    delay.output_to(sink)

    engine.add_component(source)
    engine.add_component(delay)
    engine.add_component(sink)
    engine.run()
    return get_records_as_printable_string(engine.get_results())


if __name__ == "__main__":
    setup_logging(level=logging.INFO, log_file="sim.log", output_dir="output")
    results = simple_simulation()
    print(results)