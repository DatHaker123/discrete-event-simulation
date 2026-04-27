# Extra Features

This guide covers the remaining advanced features beyond baseline engine/components usage.

---

## Operation Modes

Operation modes provide reusable control regimes (for example `slow`/`fast`).

Key pieces:
- `OperationModeTrigger(name, check, expected_next_trigger_time=None)`
- `OperationMode(name, triggers, data, priority=0)`
- `with_operational_mode(BaseComponent)` mixin factory

Typical pattern:

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

---

## Threshold-Crossing Helpers

For piecewise-constant continuous-state control:
- `get_linear_predictor(...)`
- `get_advancer_linear_inventory_state(...)`
- `get_default_rate_update_handler(...)`
- rate components in `threshold_crossing.py`.

Use threshold-crossing when you want sparse control events instead of fixed ticks.

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

