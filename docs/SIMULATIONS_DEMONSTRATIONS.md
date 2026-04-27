# Simulations Demonstration Guide

This guide documents each simulation under `src/simulations`, what it models, what concept it introduces, and the programming patterns it demonstrates.

Use the central runner:

```bash
python -m src.run --file <simulation_file.py>
```

Add `--viz` for PDF frames and `--plot` where the simulation implements plotting in `post_run`.

---

## DES Foundations

### `des_1_simple.py`
- **Meaning**: Minimal event-driven line: source -> delay -> sink.
- **Introduces**: Startup `Generate`, single-path `connect`, sink records.
- **Patterns featured**:
  - `engine.add_startup_event(Event(..., "Generate", {}, {}))`
  - `SourceComponent` with simple generator lambda
  - `DelayComponent` as service-time stage

### `des_2_simple.py`
- **Meaning**: Adds payload transformation and shared simulation variables.
- **Introduces**: `TransformerComponent`, stateful transform logic.
- **Patterns featured**:
  - Read/write `engine.simulation_variables`
  - Mutate per-component `component.state`
  - Transform payload via `ctx.entity`

### `des_3_converger_splitter.py`
- **Meaning**: Multi-input merge followed by deterministic fan-out split.
- **Introduces**: `ConvergerComponent` and `SplitterComponent`.
- **Patterns featured**:
  - Many-to-one topology (`source_a/source_b -> converger`)
  - Splitter function returning `dict[output_component_id, Entity]`
  - Omittable outputs by missing keys in splitter mapping

---

## Queue / Backpressure Handshake (DES)

### `des_4_queue_credit_delay.py`
- **Meaning**: Basic pull/credit queue handshake with delay server.
- **Introduces**: `QueueComponent`, `with_queue(DelayComponent)`, `QueueCredit`.
- **Patterns featured**:
  - Server-to-queue credit signaling via `HasQueue`
  - Implicit initial credit bootstrap (no manual startup credit events)
  - Queue-driven dispatch into downstream service

### `des_5_queue_credit_delay_weighted.py`
- **Meaning**: Queue-credit model with weighted entities and richer tracked state.
- **Introduces**: custom state-updater pattern.
- **Patterns featured**:
  - `set_state_updater(...)` instead of custom handler rewrites
  - Runtime snapshots of queue buffer / ready credits / delay content
  - Weighted payload generation (`floor(uniform)` style)

### `des_6_overlapping_queues.py`
- **Meaning**: Two-queue overlapping chain with configurable queue/server pairings.
- **Introduces**: handshake wiring experiments and interaction modes.
- **Patterns featured**:
  - Shared topology with toggleable queue-credit pairings
  - Comparison of independent-pairs vs cross-coupled pairings
  - Queue and delay introspection via state updaters

---

## Resource Workflow (DES)

### `des_7_resource_bottleneck.py`
- **Meaning**: Resource-limited throughput where pool capacity is the bottleneck.
- **Introduces**: baseline request/free resource lifecycle.
- **Patterns featured**:
  - `RequestResourceComponent` for acquire-gated dispatch
  - `FreeResourceComponent` for releasing resources from main flow
  - Explicit request->free ownership linkage via `request.set_free_component(free)`

### `des_8_resource_blocking_pre_post.py`
- **Meaning**: Resource lifecycle with blocking pre-acquire and post-release side-flows.
- **Introduces**: four hook components around request/free.
- **Patterns featured**:
  - Pre side-flow:
    - `PreAcquireSourceComponent` (`PreAcquireStart` entry)
    - `PreAcquireSinkComponent` (`PreAcquireComplete` emit + validation)
  - Post side-flow:
    - `PostReleaseSourceComponent` (`PostReleaseStart` entry)
    - `PostReleaseSinkComponent` (`PostReleaseComplete` emit + validation)
  - Reference-based linking:
    - `request.link_pre_acquire_source(pre_source)`
    - `pre_sink.set_request_component(request)`
    - `free.set_post_release_source_component(post_source)`
    - `post_sink.set_free_component(free)`

---

## DRS / Crusher Family

### `drs_1_crusher_tickwise.py`
- **Meaning**: Single-machine tickwise crusher inventory with hysteresis mode switching.
- **Introduces**: core tickwise DRS behavior in DES runtime.
- **Patterns featured**:
  - Source-generated mass feed
  - Transformer-managed stockpile + mode state
  - Hysteresis thresholds (`HIGH`/`LOW`) in state logic

### `drs_2_crusher_tickwise_with_operation_mode.py`
- **Meaning**: Same crusher dynamics but mode logic extracted to operation-mode module.
- **Introduces**: `OperationMode`, `OperationModeTrigger`, `with_operational_mode`.
- **Patterns featured**:
  - Mode resolution via reusable mode manager
  - Cleaner transform logic by moving mode checks out of ad-hoc branches

### `drs_3_crusher_threshold_crossing.py`
- **Meaning**: Legacy threshold-crossing trace file.
- **Introduces**: historical API trace of removed helper.
- **Patterns featured**:
  - Kept intentionally failing as migration trace (`get_departure_event_forwarder` import)
  - Useful as a “what changed” reference, not a runnable example

### `drs_4_crusher_threshold_crossing_intended_design.py`
- **Meaning**: Intended threshold-crossing architecture using rate components.
- **Introduces**: modular control-rate pipeline.
- **Patterns featured**:
  - `RateSourceComponent` -> `RateSchedulerComponent` -> `RateTransformerComponent`
  - Piecewise-constant linear predictors (`get_linear_predictor`)
  - `ModeChange` scheduling and per-component event invalidation (`advance_version`)

### `drs_5_crusher_tickwise_two_stage_operation_mode.py`
- **Meaning**: Two-stage tickwise chain (crusher -> grinder), each with independent modes.
- **Introduces**: multi-stage operation-mode interactions and optional plotting.
- **Patterns featured**:
  - Per-stage state and mode tracking
  - Stage-specific thresholds/capacities
  - Simulation-owned plotting in `post_run`

---

## Generated Prototype Output

### `generated_simulation.py`
- **Meaning**: Auto-generated scaffold from the simulation-designer prototype.
- **Introduces**: generated baseline wiring.
- **Patterns featured**:
  - Basic source/delay/sink scaffold with startup generate
  - Manual-review marker and editable generated structure
  - Useful as a starting point, not canonical style

---

## Suggested Learning Order

1. `des_1_simple.py`
2. `des_2_simple.py`
3. `des_3_converger_splitter.py`
4. `des_4_queue_credit_delay.py`
5. `des_5_queue_credit_delay_weighted.py`
6. `des_7_resource_bottleneck.py`
7. `des_8_resource_blocking_pre_post.py`
8. `drs_1_crusher_tickwise.py` -> `drs_2_*` -> `drs_4_*` -> `drs_5_*`

This order moves from baseline DES, to handshake protocols, to resource workflows, and finally to DRS-specific modeling styles.
