## DES: source -> request_resource -> delay -> free_resource -> sink
## Demonstrates resource bottleneck (pool capacity << arrival pressure).

import sys
from copy import deepcopy
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.core import (
    DelayComponent,
    Engine,
    Event,
    FreeResourceComponent,
    RequestResourceComponent,
    Resource,
    ResourcePool,
    SimulationContext,
    SinkComponent,
    SourceComponent,
)
from src.modules import get_records_as_printable_string
from src.modules.sim_output import RunOptions
from src.modules.utils import UniformDistribution

SOURCE_INTERVAL = UniformDistribution(0.18, 0.24)
PROCESS_DELAY = UniformDistribution(0.95, 1.1)
TIME_LIMIT = 4.0

INITIAL_SOURCE_STATE = {"count": 0}
INITIAL_REQUEST_STATE = {"size": 0, "pending_entities": []}
INITIAL_DELAY_STATE = {"size": 0, "scheduled_departures": []}
INITIAL_FREE_STATE = {"released_count": 0}


def token_generator(ctx: SimulationContext) -> dict:
    idx = int(ctx.component.state.get("count", 0)) + 1
    ctx.component.state["count"] = idx
    return {"id": idx, "name": f"ore-{idx}"}


def request_state_updater(ctx: SimulationContext) -> None:
    ctx.component.state["size"] = len(ctx.component.buffer)
    ctx.component.state["pending_entities"] = deepcopy(ctx.component.buffer)


def delay_state_updater(ctx: SimulationContext) -> None:
    ctx.component.state["size"] = ctx.component.count
    ctx.component.state["scheduled_departures"] = deepcopy(sorted(ctx.component.content, key=lambda x: x[0]))


def free_state_updater(ctx: SimulationContext) -> None:
    released = int(ctx.component.state.get("released_count", 0))
    if ctx.event.type == "Arrival":
        released += 1
    ctx.component.state["released_count"] = released


def des_7_resource_bottleneck_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    source = SourceComponent("source", token_generator, interval=SOURCE_INTERVAL, track_state=True)
    source.state = deepcopy(INITIAL_SOURCE_STATE)

    # Single resource ensures this stage is the global throughput bottleneck.
    truck_pool = ResourcePool(
        pool_id="truck_pool",
        resource_type="truck",
        resource_generator=lambda: Resource(data={"max_payload_t": 35}),
        capacity=1,
    )

    request = RequestResourceComponent(
        "request",
        resource_pool=truck_pool,
        max_length=1000,
        track_state=True,
    )
    request.state = deepcopy(INITIAL_REQUEST_STATE)
    request.set_state_updater(request_state_updater)

    # Processing capacity itself is not the bottleneck; resource ownership is.
    delay = DelayComponent(
        "process",
        delay_interval=PROCESS_DELAY,
        capacity=8,
        track_state=True,
    )
    delay.state = deepcopy(INITIAL_DELAY_STATE)
    delay.set_state_updater(delay_state_updater)

    free = FreeResourceComponent(
        "free",
        resource_pool=truck_pool,
        track_state=True,
    )
    request.set_free_component(free)
    free.state = deepcopy(INITIAL_FREE_STATE)
    free.set_state_updater(free_state_updater)

    sink = SinkComponent("sink", track_state=False)

    for c in (source, request, delay, free, sink):
        engine.add_component(c)
    engine.connect(source, request)
    engine.connect(request, delay)
    engine.connect(delay, free)
    engine.connect(free, sink)

    engine.run()
    return engine


def post_run(engine: Engine, options: RunOptions) -> None:
    _ = options
    print(get_records_as_printable_string(engine.get_results()))


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
