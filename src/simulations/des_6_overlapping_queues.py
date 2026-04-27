## DES: source -> q1 -> q2 -> d2 -> d1 -> sink
## Overlapping queues with independent handshake pairs: q1<->d1 and q2<->d2.

import sys
from copy import deepcopy
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.core import DelayComponent, Engine, Event, QueueComponent, SimulationContext, SinkComponent, SourceComponent, with_queue
from src.modules import get_records_as_printable_string
from src.modules.sim_output import RunOptions
from src.modules.utils import UniformDistribution

SOURCE_INTERVAL = UniformDistribution(0.18, 0.28)
D2_DELAY = UniformDistribution(0.9, 1.1)
D1_DELAY = UniformDistribution(2.4, 2.8)
TIME_LIMIT = 6.0


def queue_state_updater(ctx: SimulationContext) -> None:
    ctx.component.state["size"] = len(ctx.component.buffer)
    ctx.component.state["ready_credits"] = ctx.component.ready_credits
    ctx.component.state["entities"] = deepcopy(ctx.component.buffer)


def delay_state_updater(ctx: SimulationContext) -> None:
    ctx.component.state["size"] = ctx.component.count
    ctx.component.state["scheduled_departures"] = deepcopy(sorted(ctx.component.content, key=lambda x: x[0]))


def des_6_overlapping_queues_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    def token_generator(ctx: SimulationContext) -> dict:
        idx = int(ctx.component.state.get("count", 0)) + 1
        ctx.component.state["count"] = idx
        return {"id": idx, "name": f"token-{idx}"}

    source = SourceComponent("source", token_generator, interval=SOURCE_INTERVAL, track_state=True)
    source.state["count"] = 0

    q1 = QueueComponent("q1", max_length=1000, track_state=True)
    q1.state = {"size": 0, "ready_credits": 0, "entities": []}
    q1.set_state_updater(queue_state_updater)

    q2 = QueueComponent("q2", max_length=1000, track_state=True)
    q2.state = {"size": 0, "ready_credits": 0, "entities": []}
    q2.set_state_updater(queue_state_updater)

    DelayWithQueue = with_queue(DelayComponent)
    d2 = DelayWithQueue("d2", delay_interval=D2_DELAY, capacity=2, track_state=True)
    d2.state = {"size": 0, "scheduled_departures": []}
    d2.set_state_updater(delay_state_updater)

    d1 = DelayWithQueue("d1", delay_interval=D1_DELAY, capacity=4, track_state=True)
    d1.state = {"size": 0, "scheduled_departures": []}
    d1.set_state_updater(delay_state_updater)

    sink = SinkComponent("sink", track_state=False)

    # ---------------- Queue-credit wiring modes ----------------
    # Shared structure in BOTH modes:
    #   q1 -> q2 -> d2 -> d1
    #
    # MODE A: independent pairs
    #   q1 <-> d1
    #   q2 <-> d2
    #
    # d2.set_queue_component_id("q2")
    # d1.set_queue_component_id("q1")
    #
    # MODE B: cross-coupled
    #   q1 <-> d2
    #   q2 <-> d1

    d2.set_queue_component_id("q1")
    d1.set_queue_component_id("q2")

    # ------------------------------------------------------------

    for c in (source, q1, q2, d2, d1, sink):
        engine.add_component(c)
    engine.connect(source, q1)
    engine.connect(q1, q2)
    engine.connect(q2, d2)
    engine.connect(d2, d1)
    engine.connect(d1, sink)

    engine.run()
    return engine


def post_run(engine: Engine, options: RunOptions) -> None:
    _ = options
    print(get_records_as_printable_string(engine.get_results()))


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
