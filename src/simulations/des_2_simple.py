## Simple system with a source, delay, transformer, and sink

import sys
from pathlib import Path

# Add project root and src so ``from src.core`` / ``from src.modules`` resolve
_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.core import (
    DelayComponent,
    Engine,
    Entity,
    Event,
    SinkComponent,
    SimulationContext,
    SourceComponent,
    TransformerComponent,
)
from src.modules.utils import UniformDistribution


def simple_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))
    engine.simulation_variables["token_count"] = 0

    def token_generator(ctx: SimulationContext) -> Entity:
        ctx.engine.simulation_variables["token_count"] += 1
        return {"name": "token", "value": ctx.engine.simulation_variables["token_count"]}

    source = SourceComponent("source", token_generator, UniformDistribution(0, 10))

    delay = DelayComponent("delay", UniformDistribution(0, 10), capacity=1000)

    def transformation_function(ctx: SimulationContext) -> Entity:
        original = ctx.entity
        st = ctx.component.state
        if original["value"] > 5:
            original["value"] = original["value"] - 5
            original["name"] = "token2"

        if ctx.engine.simulation_variables["token_count"] > 10:
            original["name"] = "token3"
            original["value"] = ctx.engine.simulation_variables["token_count"] - 10

        if st["token_count"] > 15:
            original["name"] = "token4"
            original["value"] = st["token_count"] - 15
        st["token_count"] += 1
        return original

    transformer = TransformerComponent("transformer", transformation_function, track_state=True)
    transformer.state["token_count"] = 0

    sink = SinkComponent("sink")

    engine.add_component(source)
    engine.add_component(delay)
    engine.add_component(transformer)
    engine.add_component(sink)
    engine.connect(source, delay)
    engine.connect(delay, transformer)
    engine.connect(transformer, sink)
    engine.run()
    return engine


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
