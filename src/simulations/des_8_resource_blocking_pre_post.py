## DES: source -> request -> process -> free -> sink
## With blocking pre-acquire and post-release side-flows.

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
    PostReleaseSinkComponent,
    PostReleaseSourceComponent,
    PreAcquireSinkComponent,
    PreAcquireSourceComponent,
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
PROCESS_DELAY = UniformDistribution(0.9, 1.0)
PRE_DELAY = UniformDistribution(0.25, 0.35)
POST_DELAY = UniformDistribution(0.25, 0.35)
TIME_LIMIT = 5.0


def token_generator(ctx: SimulationContext) -> dict:
    idx = int(ctx.component.state.get("count", 0)) + 1
    ctx.component.state["count"] = idx
    return {"id": idx, "name": f"ore-{idx}"}


def des_8_resource_blocking_pre_post_simulation(visualize: bool = False) -> Engine:
    engine = Engine(visualize=visualize, time_limit=TIME_LIMIT)
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    source = SourceComponent("source", token_generator, interval=SOURCE_INTERVAL, track_state=True)
    source.state = {"count": 0}

    truck_pool = ResourcePool(
        pool_id="truck_pool",
        resource_type="truck",
        resource_generator=lambda: Resource(data={"max_payload_t": 35}),
        capacity=1,
    )

    request = RequestResourceComponent("request", resource_pool=truck_pool, max_length=1000, track_state=True)
    request.state = {"size": 0}
    request.set_state_updater(lambda ctx: ctx.component.state.update({"size": len(ctx.component.buffer)}))

    process = DelayComponent("process", delay_interval=PROCESS_DELAY, capacity=8, track_state=False)

    free = FreeResourceComponent(
        "free",
        resource_pool=truck_pool,
        track_state=False,
    )

    pre_source = PreAcquireSourceComponent("pre_source", track_state=False)
    pre_delay = DelayComponent("pre_delay", delay_interval=PRE_DELAY, capacity=8, track_state=False)
    pre_sink = PreAcquireSinkComponent("pre_sink", track_state=False)

    post_source = PostReleaseSourceComponent("post_source", track_state=False)
    post_delay = DelayComponent("post_delay", delay_interval=POST_DELAY, capacity=8, track_state=False)
    post_sink = PostReleaseSinkComponent("post_sink", track_state=False)

    request.link_pre_acquire_source(pre_source)
    request.set_free_component(free)
    pre_sink.set_request_component(request)
    free.set_post_release_source_component(post_source)
    post_sink.set_free_component(free)

    sink = SinkComponent("sink", track_state=False)

    for c in (
        source,
        request,
        process,
        free,
        sink,
        pre_source,
        pre_delay,
        pre_sink,
        post_source,
        post_delay,
        post_sink,
    ):
        engine.add_component(c)

    # Main path
    engine.connect(source, request)
    engine.connect(request, process)
    engine.connect(process, free)
    engine.connect(free, sink)

    # Pre-acquire side-flow (blocking for RequestResource)
    engine.connect(pre_source, pre_delay)
    engine.connect(pre_delay, pre_sink)

    # Post-release side-flow (blocking for FreeResource)
    engine.connect(post_source, post_delay)
    engine.connect(post_delay, post_sink)

    engine.run()
    return engine


def post_run(engine: Engine, options: RunOptions) -> None:
    _ = options
    print(get_records_as_printable_string(engine.get_results()))


if __name__ == "__main__":
    from src.run import run_cli

    raise SystemExit(run_cli(sys.argv[1:], default_file=__file__))
