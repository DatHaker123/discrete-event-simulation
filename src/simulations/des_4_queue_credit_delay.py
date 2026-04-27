## DES: source -> queue (QueueCredit handshake) -> delay-with-queue -> sink

import sys
from pathlib import Path

# Add project root and src so ``from src.core`` / ``from src.modules`` resolve
_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.core import DelayComponent, Engine, Event, QueueComponent, SimulationContext, SinkComponent, SourceComponent, with_queue
from src.modules import get_records_as_printable_string
from src.modules.sim_output import RunOptions
from src.modules.utils import UniformDistribution

SOURCE_INTERVAL = UniformDistribution(0.4, 0.8)
DELAY_INTERVAL = UniformDistribution(1.0, 1.2)
TIME_LIMIT = 5.0


def des_queue_credit_delay_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    def token_generator(ctx: SimulationContext) -> dict:
        idx = int(ctx.component.state.get("count", 0)) + 1
        ctx.component.state["count"] = idx
        return {"name": "token", "id": idx}

    source = SourceComponent("source", token_generator, interval=SOURCE_INTERVAL, track_state=True)
    source.state["count"] = 0

    queue = QueueComponent("queue", max_length=1000, track_state=False)

    DelayWithQueue = with_queue(DelayComponent)
    delay = DelayWithQueue(
        "delay",
        delay_interval=DELAY_INTERVAL,
        capacity=2,
        track_state=True,
    )
    delay.set_queue_component_id("queue")

    sink = SinkComponent("sink", track_state=False)

    for c in (source, queue, delay, sink):
        engine.add_component(c)
    engine.connect(source, queue)
    engine.connect(queue, delay)
    engine.connect(delay, sink)

    engine.run()
    return engine


def post_run(engine: Engine, options: RunOptions) -> None:
    _ = options
    print(get_records_as_printable_string(engine.get_results()))


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
