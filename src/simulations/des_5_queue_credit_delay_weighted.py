## DES: source -> queue (QueueCredit handshake) -> delay-with-queue -> sink
## Variant: weighted entities + richer queue/delay state tracking

import math
import sys
from copy import deepcopy
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
from src.modules.utils import ConstantDistribution, UniformDistribution

SOURCE_INTERVAL = UniformDistribution(0.4, 0.8)
DELAY_INTERVAL = UniformDistribution(2.0, 2.5)
WEIGHT_DISTRIBUTION = UniformDistribution(1.0, 4.0)
TIME_LIMIT = 5.0

INITIAL_SOURCE_STATE = {
    "count": 0,
}
INITIAL_QUEUE_STATE = {
    "size": 0,
    "ready_credits": 0,
    "entities": [],
}
INITIAL_DELAY_STATE = {
    "size": 0,
    "scheduled_departures": [],
}

DelayWithQueueComponent = with_queue(DelayComponent)

def delay_state_updater(ctx: SimulationContext) -> None:
    ctx.component.state["size"] = ctx.component.count
    ctx.component.state["scheduled_departures"] = deepcopy(sorted(ctx.component.content, key=lambda x: x[0]))


def queue_state_updater(ctx: SimulationContext) -> None:
    ctx.component.state["size"] = len(ctx.component.buffer)
    ctx.component.state["ready_credits"] = ctx.component.ready_credits
    ctx.component.state["entities"] = deepcopy(ctx.component.buffer)

def token_generator(ctx: SimulationContext) -> dict:
    idx = int(ctx.component.state.get("count", 0)) + 1
    ctx.component.state["count"] = idx
    # Use floor(uniform) and clamp upper edge to keep integer weights in [1, 3].
    weight = min(3, math.floor(WEIGHT_DISTRIBUTION.sample()))
    entity = {"name": "token", "id": idx, "weight": weight}
    ctx.component.state["last_generated_entity"] = entity
    return entity

def des_5_queue_credit_delay_weighted_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    source = SourceComponent("source", token_generator, interval=SOURCE_INTERVAL, track_state=True)
    source.state = deepcopy(INITIAL_SOURCE_STATE)

    queue = QueueComponent("queue", max_length=1000, track_state=True)
    queue.state = deepcopy(INITIAL_QUEUE_STATE)
    queue.set_state_updater(queue_state_updater)

    delay = DelayWithQueueComponent(
        "delay",
        delay_interval=DELAY_INTERVAL,
        capacity=5,
        track_state=True,
    )
    delay.state = deepcopy(INITIAL_DELAY_STATE)
    delay.set_state_updater(delay_state_updater)
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
