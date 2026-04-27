# Extra Features

This guide covers the remaining advanced features beyond baseline engine/components usage.

---

## Operation Modes

Operation modes provide reusable control regimes (for example `slow`/`fast`).

Key pieces:
- `OperationModeTrigger(name, check, expected_next_trigger_time=None)`
- `OperationMode(name, triggers, data, priority=0)`
- `with_operational_mode(BaseComponent)` mixin factory

### Class-by-class: what each is, does, and how to use it

- `OperationModeTrigger`
  - **What it is**: a trigger definition object for one condition.
  - **What it does**: evaluates `check(ctx)` to say whether a condition is currently true; optionally predicts next trigger time with `expected_next_trigger_time(ctx, delta)`.
  - **How to use it**: create small, composable triggers (for example high/low stock), then attach them to one or more modes.
- `OperationMode`
  - **What it is**: one named operating regime (for example `slow`, `fast`).
  - **What it does**: groups triggers and carries mode-specific parameters in `data` (for example distributions/capacities).
  - **How to use it**: keep `data` schema stable and explicit; set `priority` to control tie-breaking when multiple modes are valid.
- `HasOperationModeManager`
  - **What it is**: mixin that stores `modes` and `current_mode` and provides resolution methods.
  - **What it does**:
    - `add_mode(mode)` registers regimes,
    - `update_current_mode(ctx)` selects active mode now,
    - `get_next_mode_change(ctx, delta)` predicts next mode transition (mainly for threshold-crossing).
  - **How to use it**: you typically do not instantiate this directly; consume it through `with_operational_mode` or components that already include it.
- `with_operational_mode(base_cls)`
  - **What it is**: factory that returns a new class combining `base_cls` + mode manager behavior.
  - **What it does**: preserves base component behavior and adds mode APIs.
  - **How to use it**: prefer for tickwise transformer/scheduler style components when you want mode logic without rewriting component classes.

What happens at runtime:
- You register modes on a component (usually a transformer/scheduler wrapper).
- On each relevant event, call `update_current_mode(ctx)`.
- The manager evaluates modes in descending `priority`.
- The first mode whose triggers all pass becomes `current_mode`.
- If no mode matches, the previously selected mode is retained.

### Typical pattern (tickwise)

```python
from src.modules.operation_mode import OperationMode, OperationModeTrigger, with_operational_mode
from src.core import TransformerComponent

check_high = lambda ctx: float(ctx.component.state["stockpile"]) >= 20.0
check_low = lambda ctx: float(ctx.component.state["stockpile"]) <= 9.0

MODE_SLOW = OperationMode("slow", triggers=[OperationModeTrigger("low", check_low)], data={"rate": 1.2}, priority=10)
MODE_FAST = OperationMode("fast", triggers=[OperationModeTrigger("high", check_high)], data={"rate": 5.3}, priority=20)

TransformerWithMode = with_operational_mode(TransformerComponent)
crusher = TransformerWithMode("crusher", transform_function=...)
crusher.add_mode(MODE_SLOW)
crusher.add_mode(MODE_FAST)
```

### Lambda vs explicit function (clarity guidance)

Use **lambdas** when:
- trigger check is one short expression,
- no branching, no logging, no reuse.

Use **explicit named functions** when:
- trigger logic has multiple conditions,
- you want descriptive names and comments,
- the same check is reused across files/simulations.

Recommended explicit style for readability:

```python
def is_stockpile_high(ctx):
    return float(ctx.component.state["stockpile"]) >= HIGH_STOCK

def is_stockpile_low(ctx):
    return float(ctx.component.state["stockpile"]) <= LOW_STOCK
```

### Practical notes from examples

- In `drs_2_crusher_tickwise_with_operation_mode.py`, inline lambdas are acceptable because checks are small and local.
- For larger models, prefer named functions so mode wiring remains easy to scan and debug.
- Keep mode `data` keys stable (for example `crush_speed`) to avoid brittle handler code.

### Explicit example: referencing mode inside `transform_function`

This is the most common usage pattern:

```python
def crusher_transform(ctx):
    st = ctx.component.state
    raw_in = float(ctx.entity.get("raw_tonnes", 0.0))

    # 1) Update state that triggers depend on.
    st["stockpile"] = float(st["stockpile"]) + raw_in

    # 2) Resolve active mode for THIS event.
    selected_mode = ctx.component.update_current_mode(ctx)
    if selected_mode is None:
        raise RuntimeError("No mode selected for crusher")

    # 3) Read mode parameters from mode.data.
    capacity = float(selected_mode.data["crush_speed"].sample())

    crushed = min(float(st["stockpile"]), capacity)
    st["stockpile"] = float(st["stockpile"]) - crushed

    # 4) Optional: keep mode name in state/output for plotting/debugging.
    st["mode"] = selected_mode.name
    return {"crushed_tonnes": crushed, "mode": selected_mode.name}
```

Alternative pattern when you want to avoid re-resolving if already set:

```python
active_mode = ctx.component.current_mode
if active_mode is None:
    active_mode = ctx.component.update_current_mode(ctx)
```

Recommendation:
- In most transforms, call `update_current_mode(ctx)` after updating the state that triggers inspect.
- Use `current_mode` as a cache/read convenience, not as a substitute for proper mode resolution timing.

---

## Threshold-Crossing Helpers

For piecewise-constant continuous-state control:
- `get_linear_predictor(...)`
- `get_advancer_linear_inventory_state(...)`
- `get_default_rate_update_handler(...)`
- rate components in `threshold_crossing.py`.

Use threshold-crossing when you want sparse control events instead of fixed ticks.

### Function/class-by-function: what each is, does, and how to use it

- `get_linear_predictor(state_key, threshold, crossing, delta_key=None)`
  - **What it is**: helper factory that returns a predictor callable.
  - **What it does**: computes next crossing time under a linear derivative assumption from `delta`.
  - **How to use it**: attach returned predictor to `OperationModeTrigger.expected_next_trigger_time`; use only when piecewise-constant delta is a reasonable approximation.
- `get_advancer_linear_inventory_state(level_key, in_rate_key, out_rate_key, time_key, min_level=0.0)`
  - **What it is**: helper factory for inventory integration logic.
  - **What it does**: advances level from `last_time` to `now` using `in_rate - out_rate`.
  - **How to use it**: call from scheduler handler before mode resolution/output emission; keep `time_key` maintained in state.
- `get_default_rate_update_handler(...)`
  - **What it is**: default scheduler loop constructor.
  - **What it does**: advance state -> apply inbound rate -> resolve mode -> compute out rate -> emit departure -> predict/schedule next mode change.
  - **How to use it**: best for one-dimensional linear rate-control models; replace with explicit custom handler when physics is nonlinear or requires richer constraints.
- `RateSourceComponent`
  - **What it is**: source variant for control/rate streams.
  - **What it does**: emits downstream `RateUpdate` on departure (instead of material `Arrival`).
  - **How to use it**: startup-only (`interval=None`) for boundary condition injection, or periodic for external control streams.
- `RateSchedulerComponent`
  - **What it is**: single-IO scheduler core with operation-mode support.
  - **What it does**: handles `RateUpdate` and `ModeChange`, then emits `RateUpdate` downstream via its own departure.
  - **How to use it**: provide a scheduler handler (default helper or custom); ensure it updates state consistently and schedules future mode events carefully.
- `RateTransformerComponent`
  - **What it is**: transform stage for rate payloads.
  - **What it does**: maps one `RateUpdate` entity to another while preserving two-step event flow.
  - **How to use it**: separate physical conversion/mapping from scheduling logic to keep scheduler focused.

### Core flow (intended design)

Typical architecture from `drs_4_crusher_threshold_crossing_intended_design.py`:

1. `RateSourceComponent` emits startup `RateUpdate`.
2. `RateSchedulerComponent` receives `RateUpdate`/`ModeChange`.
3. Scheduler advances inventory state to `now` (continuous integration step).
4. Scheduler resolves mode, computes output rate, emits self `Departure`.
5. Scheduler predicts next crossing and schedules `ModeChange`.
6. Scheduler calls `advance_version()` before scheduling projected future control events, so stale projections are skipped later.
7. `RateTransformerComponent` maps internal rate payload to downstream payload.

### Predictors and advancers

- `get_linear_predictor(...)` assumes piecewise-constant delta and solves crossing time analytically.
- `get_advancer_linear_inventory_state(...)` integrates one inventory-like state using `in_rate - out_rate`.
- `get_default_rate_update_handler(...)` combines the recurring control loop (advance -> resolve mode -> emit rate -> schedule next mode change).

### Lambda vs explicit function (clarity guidance)

For threshold crossing, prefer **explicit functions** for predictors and checks in most cases.

Use lambdas only when the function is trivial and local:

```python
check_high = lambda ctx: float(ctx.component.state["stockpile"]) >= HIGH_STOCK
```

Prefer explicit functions when reasoning matters:

```python
def predict_time_to_high(ctx, delta):
    stock = float(ctx.component.state["stockpile"])
    d_stock = float(delta.get("stockpile", 0.0))
    now = ctx.engine.get_current_time()
    if stock >= HIGH_STOCK:
        return now
    if d_stock <= 0.0:
        return None
    return now + (HIGH_STOCK - stock) / d_stock
```

Why explicit is usually better here:
- easier to validate assumptions (`d_stock > 0`, bounds, epsilon),
- easier to unit-test predictor logic,
- easier to debug unexpected switching times.

### Usage guidance by model complexity

- **Simple/teaching model**: helper factories + a couple of lambdas are fine.
- **Production/research model**: prefer explicit named check/predict/handler functions so assumptions are visible and testable.
- **Nonlinear dynamics**: replace `get_default_rate_update_handler` with explicit handler logic; keep rate components but make solver assumptions explicit in code comments.

### When to choose threshold-crossing vs tickwise

- Choose **tickwise** when model behavior is highly nonlinear or frequent and simple stepping is acceptable.
- Choose **threshold-crossing** when rates are approximately piecewise constant and you want fewer, meaningful control events.

---

## Rate Components

These components model control/rate streams directly:

- `RateSourceComponent`
  - emits downstream `RateUpdate` on departure.
- `RateSchedulerComponent`
  - handles `RateUpdate` + `ModeChange`, then emits `RateUpdate` downstream.
- `RateTransformerComponent`
  - transforms one rate payload into another.

Pipeline pattern:

`RateSource -> RateScheduler -> RateTransformer -> Sink`

---

## Event Versioning for Staleness

Each component has `version`.
Each queued event stores `event.version` at enqueue time.

If component logic reschedules future control events and invalidates older projections:
- call `component.advance_version()`.

During `engine.run()`, events with stale versions are skipped for that component.

Use cases:
- threshold-crossing re-prediction,
- any design that pre-schedules tentative future events.

---

## Queue Credit Protocol

Queue flow is explicit pull/credit, not naive push:
- `QueueComponent` buffers arrivals,
- downstream server grants `QueueCredit`,
- queue dispatches only when credits are available.

Enhancements:
- `credits_required(ctx)` supports weighted credit cost per entity.
- `with_queue(DelayComponent)` (or other `SingleIOComponent`) adds automatic credit notification on departure.
- engine auto-bootstraps initial queue credits for `HasQueue` servers.

---

## Resource Workflow

### Core objects

- `Resource` (first-class object with `id`, `pool_id`, type, allocation metadata, and `data`)
- `ResourcePool` (same-type reusable resources, deterministic first-available allocation)

### Main components

- `RequestResourceComponent`
  - queue-like request stage that acquires resources before dispatch.
- `FreeResourceComponent`
  - releases tracked resources and notifies request side with `ResourceReleased`.

Event kwargs conventions:
- `kwargs["resources"][pool_id] -> list[resource_id]`
- `kwargs["resource_payloads"][pool_id][resource_id] -> payload dict`

---

## Blocking Side-Flows (Pre/Post)

Optional lifecycle hook flows:

- Pre-acquire:
  - `PreAcquireSourceComponent` (entry on `PreAcquireStart`)
  - `PreAcquireSinkComponent` (validates and emits `PreAcquireComplete`)
- Post-release:
  - `PostReleaseSourceComponent` (entry on `PostReleaseStart`)
  - `PostReleaseSinkComponent` (validates and emits `PostReleaseComplete`)

Reference-based linking:

```python
request.link_pre_acquire_source(pre_source)
pre_sink.set_request_component(request)

free.set_post_release_source_component(post_source)
post_sink.set_free_component(free)
```

---

## Implicit `kwargs` Propagation

The engine propagates active event `kwargs` to newly scheduled events automatically.

Implications:
- protocol metadata (queue/resource tags) follows event chains without manual threading,
- event kwargs are merged with explicit kwargs on `add_event`.

Design note:
- this is powerful, but keep metadata keys deliberate and stable.

---

## `SimulationContext` Ergonomics

Handlers receive `SimulationContext(engine, event, component)` and should use:
- `ctx.entity` for payload access,
- `ctx.engine` for scheduling,
- `ctx.component` for state/mode/internal logic.

Prefer `ctx.entity` over direct `ctx.event.entity` for readability consistency.

---

## Visualization and Plot Extras

- `Engine(visualize=True)` enables frame capture into output artifacts.
- `SimulationPlot` provides lightweight immediate plotting from state history.
- `plot_mode_changes()` marks first mode and transitions with deterministic color mapping.

---

## When To Reach For Each Feature

- **Baseline DES**: always start here.
- **Operation modes**: state-dependent regime switching.
- **Threshold-crossing/rate components**: sparse control-event simulation.
- **Queue credits**: explicit downstream capacity handshake.
- **Resources**: shared constrained assets.
- **Pre/post side-flows**: lifecycle sub-processes around acquire/release.
- **Versioning**: invalidate stale pre-scheduled events.

