# Engine and Components

This guide explains the core runtime building blocks with intuitive patterns for:
- instantiation,
- preparation,
- registration/wiring,
- overriding behavior safely.

---

## Core Build Lifecycle

Use this order in almost every simulation:

1. **Instantiate** engine and components.
2. **Prepare** component state and optional custom handlers/updaters.
3. **Register** all components with `engine.add_component(...)`.
4. **Wire** topology with `engine.connect(c1, c2)`.
5. **Seed** startup events with `engine.add_startup_event(...)`.
6. **Run** via `engine.run()`.

Minimal skeleton:

```python
from src.core import Engine, Event, SourceComponent, DelayComponent, SinkComponent
from src.modules.utils import ConstantDistribution

engine = Engine(time_limit=10.0, visualize=False)
engine.add_startup_event(Event(0.0, "source", "Generate", {}, {}))

source = SourceComponent("source", lambda _ctx: {"id": 1}, interval=ConstantDistribution(1.0))
delay = DelayComponent("delay", delay_interval=ConstantDistribution(0.5), capacity=4)
sink = SinkComponent("sink")

for c in (source, delay, sink):
    engine.add_component(c)
engine.connect(source, delay)
engine.connect(delay, sink)

engine.run()
```

---

## Engine

`Engine` is responsible for:
- component registry,
- event queue and dispatch,
- topology ownership (`connect`/`disconnect`),
- startup events and run loop,
- optional visualization (`visualize=True`).

### Instantiation

```python
engine = Engine(
    time_limit=120.0,   # optional, overrides MAX_SIM_TIME env
    visualize=False,
    output_dir="output",
)
```

### Preparation

- Add startup events: `engine.add_startup_event(Event(...))`
- Optionally set global model variables: `engine.simulation_variables[...] = ...`

### `simulation_variables` (still supported)

`Engine` still exposes:

```python
engine.simulation_variables: dict[str, Any]
```

Use it for simulation-wide counters/flags that are not naturally owned by one component.

Example:

```python
engine.simulation_variables["token_count"] = 0

def generator(ctx):
    ctx.engine.simulation_variables["token_count"] += 1
    return {"id": ctx.engine.simulation_variables["token_count"]}
```

### Registration and wiring

- Register first: `engine.add_component(component)`
- Then connect: `engine.connect(upstream, downstream)`
- Components can be passed as objects (preferred) or IDs.

### Overriding/extension patterns

- Most custom logic belongs in component handlers, not in `Engine`.
- If you need custom state capture logic, use `component.set_state_updater(...)`.
- Avoid direct topology mutation in components; topology is engine-owned by design.

---

## Component Base Concepts

All components derive from `Component` and share:
- `component_id`, `type`,
- user-defined `state` dict,
- optional `state_history` when `track_state=True`,
- handler map configured by `set_handleable_event(event_type, handler)`,
- `inputs` and `outputs` as read-only views.

### State recording

- `track_state=True` enables snapshot recording.
- Initial snapshot is recorded at `t=-1`.
- A snapshot is recorded after each handled event.
- `set_state_updater(fn)` runs right before snapshot; this is the preferred pattern for derived metrics.

---

## SourceComponent

Generates entities on `Generate`, forwards on `Departure`.

### Instantiate

```python
source = SourceComponent(
    "source",
    entity_generator=lambda ctx: {"token": ctx.engine.get_current_time()},
    interval=ConstantDistribution(1.0),  # None => startup/manual only
    track_state=True,
)
```

### Prepare

```python
source.state["count"] = 0
```

### Register

- Add to engine, then connect to one downstream.

### Override example

Override `Generate` behavior but keep default flow:

```python
def source_handle_generate_custom(ctx):
    ctx.component.state["count"] = int(ctx.component.state.get("count", 0)) + 1
    ctx.component.source_handle_generate(ctx)  # call base behavior

source.set_handleable_event("Generate", source_handle_generate_custom)
```

---

## SinkComponent

Terminal collector; handles `Arrival` and records `(time, entity)` in `records`.

### Instantiate

```python
sink = SinkComponent("sink", track_state=False)
```

### Prepare

- Usually no prep required.

### Override example

Add side effects while preserving sink recording:

```python
def sink_handle_arrival_custom(ctx):
    ctx.component.sink_handle_arrival(ctx)  # keep default recording
    # custom analytics/logging here

sink.set_handleable_event("Arrival", sink_handle_arrival_custom)
```

---

## DelayComponent

Finite-capacity service stage:
- `Arrival` schedules delayed `Departure`,
- `Departure` forwards downstream.

### Instantiate

```python
delay = DelayComponent(
    "delay",
    delay_interval=ConstantDistribution(0.5),
    capacity=3,
    track_state=True,
)
```

### Prepare with state updater

```python
from copy import deepcopy

def delay_state_updater(ctx):
    ctx.component.state["size"] = ctx.component.count
    ctx.component.state["scheduled_departures"] = deepcopy(sorted(ctx.component.content, key=lambda x: x[0]))

delay.set_state_updater(delay_state_updater)
```

### Override example

Wrap `Departure` then call base:

```python
def delay_handle_departure_custom(ctx):
    # custom pre-departure logic
    ctx.component.delay_handle_departure(ctx)

delay.set_handleable_event("Departure", delay_handle_departure_custom)
```

---

## TransformerComponent

Maps inbound entity to transformed outbound entity.

### Instantiate

```python
transformer = TransformerComponent(
    "transformer",
    transform_function=lambda ctx: {"x2": 2 * float(ctx.entity.get("x", 0.0))},
    track_state=True,
)
```

### Prepare

```python
transformer.state["processed"] = 0
```

### Override pattern

- Prefer customizing `transform_function`.
- If wrapping handler, call `transformer_handle_arrival(...)` to preserve default two-step flow.

---

## AssertComponent

Validates entities; can drop or fail.

### Instantiate

```python
assert_c = AssertComponent(
    "assert_positive",
    condition=lambda ctx: float(ctx.entity.get("value", 0)) >= 0.0,
)
```

### Override fail handling

```python
def fail_handler(ctx):
    # custom behavior: record, reroute, or raise
    raise ValueError("Invalid entity")

assert_c = AssertComponent("assert_positive", condition=..., fail_handler=fail_handler)
```

---

## ConvergerComponent

Many upstreams -> single downstream pass-through.

### Instantiate

```python
converger = ConvergerComponent("converger")
```

### Registration pattern

Wire many upstreams into converger, then converger to one downstream.

---

## SplitterComponent

Single inbound entity -> selected subset of downstream outputs.

### Instantiate

```python
def split_fn(ctx):
    e = ctx.entity
    return {
        "left_sink": {"part": "left", **e},
        "right_sink": {"part": "right", **e},
        # omit key to emit nothing for that branch
    }

splitter = SplitterComponent("splitter", splitter_function=split_fn)
```

### Important rule

- Return type must be `dict[str, Entity]` keyed by downstream `component_id`.
- Unknown keys raise an error.

---

## QueueComponent and with_queue

`QueueComponent` is FIFO with explicit `QueueCredit` handshake.
`with_queue(BaseComponent)` wraps a single-IO server to auto-notify queue credits on departure.

### Instantiate queue

```python
queue = QueueComponent(
    "queue",
    max_length=1000,
    credits_required=lambda ctx: int(ctx.entity.get("weight", 1)),
    track_state=True,
)
```

### Instantiate server with queue mixin

```python
from src.core import with_queue, DelayComponent
DelayWithQueue = with_queue(DelayComponent)
server = DelayWithQueue("server", delay_interval=ConstantDistribution(1.0), capacity=2)
server.set_queue_component_id("queue")
```

### Wiring

`source -> queue -> server -> sink`

---

## Resource Components

### ResourcePool

```python
from src.core import Resource, ResourcePool

pool = ResourcePool(
    pool_id="truck_pool",
    resource_type="truck",
    resource_generator=lambda: Resource(data={"max_payload_t": 35}),
    capacity=2,
)
```

### RequestResourceComponent / FreeResourceComponent

```python
request = RequestResourceComponent("request", resource_pool=pool, max_length=1000)
free = FreeResourceComponent("free", resource_pool=pool)
request.set_free_component(free)
```

Main-line wiring:
- `source -> request -> process -> free -> sink`

### Optional side-flow components

- Pre-acquire: `PreAcquireSourceComponent`, `PreAcquireSinkComponent`
- Post-release: `PostReleaseSourceComponent`, `PostReleaseSinkComponent`

Reference-based linking pattern:

```python
request.link_pre_acquire_source(pre_source)
pre_sink.set_request_component(request)
free.set_post_release_source_component(post_source)
post_sink.set_free_component(free)
```

---

## Safe Overriding Checklist

When overriding handlers:

1. Keep naming convention: `component_handle_eventtype`.
2. Prefer wrapping over replacing when base behavior is still needed.
3. If wrapping, call the base handler explicitly.
4. Keep `state` user-defined; avoid writing framework internals into it.
5. Use `set_state_updater` for derived snapshot fields instead of invasive handler edits.

