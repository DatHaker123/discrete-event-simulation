## Simple system with a source, delay, transformer, and sink

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
from src.components import Component, SourceComponent, DelayComponent, SinkComponent, TransformerComponent
from src.logger import setup_logging
from src.stats import get_records_as_printable_string
from src.utils import UniformDistribution
from src.events import Event


def simple_simulation():
    engine = Engine(startup_events=[Event(0, "source", "Generate", None, {})], visualize=False)
    engine.simulation_variables["token_count"] = 0

    def token_generator(_engine: Engine, _comp: Component) -> dict:
        _engine.simulation_variables["token_count"] += 1
        return {"name": "token", "value": _engine.simulation_variables["token_count"]}

    source = SourceComponent("source", token_generator, UniformDistribution(0, 10))

    delay = DelayComponent("delay", UniformDistribution(0, 10), capacity=1000)

    def transformation_function(engine: Engine, event: Event, comp: Component) -> dict:
        original = event.entity
        st = comp.state
        if original["value"] > 5:
            original["value"] = original["value"] - 5
            original["name"] = "token2"

        if engine.simulation_variables["token_count"] > 10:
            original["name"] = "token3"
            original["value"] = engine.simulation_variables["token_count"] - 10

        if st["token_count"] > 15:
            original["name"] = "token4"
            original["value"] = st["token_count"] - 15
        st["token_count"] += 1
        return original

    transformer = TransformerComponent("transformer", transformation_function, track_state=True)
    transformer.state["token_count"] = 0

    sink = SinkComponent("sink")
    source.output_to(delay)
    delay.output_to(transformer)
    transformer.output_to(sink)

    engine.add_component(source)
    engine.add_component(delay)
    engine.add_component(transformer)
    engine.add_component(sink)
    engine.run()
    return get_records_as_printable_string(engine.get_results())


if __name__ == "__main__":
    setup_logging(level=logging.INFO, log_file="sim.log", output_dir="output")
    results = simple_simulation()
    print(results)
