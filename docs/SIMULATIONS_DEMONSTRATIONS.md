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
- **Output points of interest**:
  - Sink arrival order and timestamps (baseline flow sanity check).
  - Delay occupancy behavior implied by arrival/departure timing.
- **Visualize / plot**:
  - `--viz`: useful to verify simple event propagation sequence.
  - `--plot`: not implemented in this simulation.

### `des_2_simple.py`
- **Meaning**: Adds payload transformation and shared simulation variables.
- **Introduces**: `TransformerComponent`, stateful transform logic.
- **Patterns featured**:
  - Read/write `engine.simulation_variables`
  - Mutate per-component `component.state`
  - Transform payload via `ctx.entity`
- **Output points of interest**:
  - How token fields (`name`, `value`) evolve through transformer logic.
  - Correlation between source counters and transformed payloads.
- **Visualize / plot**:
  - `--viz`: useful for inspecting where transformation-caused branching effects appear in time.
  - `--plot`: not implemented.

### `des_3_converger_splitter.py`
- **Meaning**: Multi-input merge followed by deterministic fan-out split.
- **Introduces**: `ConvergerComponent` and `SplitterComponent`.
- **Patterns featured**:
  - Many-to-one topology (`source_a/source_b -> converger`)
  - Splitter function returning `dict[output_component_id, Entity]`
  - Omittable outputs by missing keys in splitter mapping
- **Output points of interest**:
  - Left/right sink symmetry (equal split by weight).
  - Preservation of source identity fields after merge and split.
- **Visualize / plot**:
  - `--viz`: especially useful to confirm converger fan-in and splitter fan-out wiring.
  - `--plot`: not implemented.

---

## Queue / Backpressure Handshake (DES)

### `des_4_queue_credit_delay.py`
- **Meaning**: Basic pull/credit queue handshake with delay server.
- **Introduces**: `QueueComponent`, `with_queue(DelayComponent)`, `QueueCredit`.
- **Patterns featured**:
  - Server-to-queue credit signaling via `HasQueue`
  - Implicit initial credit bootstrap (no manual startup credit events)
  - Queue-driven dispatch into downstream service
- **Output points of interest**:
  - Queue growth/shrink behavior under delay capacity constraints.
  - Credit-driven dispatch cadence (not pure push flow).
- **Visualize / plot**:
  - `--viz`: high value here; it shows queue-credit handshake timing clearly.
  - `--plot`: not implemented.

### `des_5_queue_credit_delay_weighted.py`
- **Meaning**: Queue-credit model with weighted entities and richer tracked state.
- **Introduces**: custom state-updater pattern.
- **Patterns featured**:
  - `set_state_updater(...)` instead of custom handler rewrites
  - Runtime snapshots of queue buffer / ready credits / delay content
  - Weighted payload generation (`floor(uniform)` style)
- **Output points of interest**:
  - Queue `state_history`: `size`, `ready_credits`, and buffered entities over time.
  - Delay `state_history`: scheduled departures and instantaneous occupancy.
  - Weighted-entity effects on credit requirements and queue persistence.
- **Visualize / plot**:
  - `--viz`: useful for validating weighted flow plus handshake dynamics.
  - `--plot`: not implemented (inspect printed state snapshots instead).

### `des_6_overlapping_queues.py`
- **Meaning**: Two-queue overlapping chain with configurable queue/server pairings.
- **Introduces**: handshake wiring experiments and interaction modes.
- **Patterns featured**:
  - Shared topology with toggleable queue-credit pairings
  - Comparison of independent-pairs vs cross-coupled pairings
  - Queue and delay introspection via state updaters
- **Output points of interest**:
  - Contrast `q1` and `q2` accumulation under each pairing mode.
  - Throughput impact of pairing choice with identical physical topology.
  - Delay occupancy asymmetry (`d1` vs `d2`) as bottlenecks shift.
- **Visualize / plot**:
  - `--viz`: strongly recommended to compare the two handshake modes.
  - `--plot`: not implemented.

---

## Resource Workflow (DES)

### `des_7_resource_bottleneck.py`
- **Meaning**: Resource-limited throughput where pool capacity is the bottleneck.
- **Introduces**: baseline request/free resource lifecycle.
- **Patterns featured**:
  - `RequestResourceComponent` for acquire-gated dispatch
  - `FreeResourceComponent` for releasing resources from main flow
  - Explicit request->free ownership linkage via `request.set_free_component(free)`
- **Output points of interest**:
  - Request buffer growth under `ResourcePool(capacity=1)`.
  - Separation between process capacity and actual throughput (resource-limited).
  - Free-stage release count progression and bottleneck confirmation.
- **Visualize / plot**:
  - `--viz`: useful to see acquire-delay-release cycles.
  - `--plot`: not implemented.

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
- **Output points of interest**:
  - Blocking behavior: main flow pauses until pre-acquire and post-release complete.
  - Side-flow latency contribution (`pre_delay`, `post_delay`) to overall cycle time.
  - Correct resource identity propagation through side-flow payload enrichment.
- **Visualize / plot**:
  - `--viz`: very helpful to trace side-flow handshakes against main flow.
  - `--plot`: not implemented.

---

## DRS / Crusher Family

### `drs_1_crusher_tickwise.py`
- **Meaning**: Single-machine tickwise crusher inventory with hysteresis mode switching.
- **Introduces**: core tickwise DRS behavior in DES runtime.
- **Patterns featured**:
  - Source-generated mass feed
  - Transformer-managed stockpile + mode state
  - Hysteresis thresholds (`HIGH`/`LOW`) in state logic
- **Output points of interest**:
  - Crusher stockpile oscillation shape and switching frequency.
  - Relationship between `raw_in`, processed tonnes, and mode.
- **Visualize / plot**:
  - `--viz`: useful for event timing sanity checks.
  - `--plot`: available via central runner for stockpile-focused inspection.

### `drs_2_crusher_tickwise_with_operation_mode.py`
- **Meaning**: Same crusher dynamics but mode logic extracted to operation-mode module.
- **Introduces**: `OperationMode`, `OperationModeTrigger`, `with_operational_mode`.
- **Patterns featured**:
  - Mode resolution via reusable mode manager
  - Cleaner transform logic by moving mode checks out of ad-hoc branches
- **Output points of interest**:
  - Mode transition points vs stockpile thresholds.
  - Equivalence (or intentional difference) versus `drs_1` dynamics with cleaner architecture.
- **Visualize / plot**:
  - `--viz`: useful for validating event order around mode transitions.
  - `--plot`: available for state-history driven trend checks.

### `drs_3_crusher_threshold_crossing.py`
- **Meaning**: Legacy threshold-crossing trace file.
- **Introduces**: historical API trace of removed helper.
- **Patterns featured**:
  - Kept intentionally failing as migration trace (`get_departure_event_forwarder` import)
  - Useful as a “what changed” reference, not a runnable example
- **Output points of interest**:
  - No runtime output expected (intentional import failure).
  - Use as migration diff reference, not simulation behavior reference.
- **Visualize / plot**:
  - `--viz`: not applicable.
  - `--plot`: not applicable.

### `drs_4_crusher_threshold_crossing_intended_design.py`
- **Meaning**: Intended threshold-crossing architecture using rate components.
- **Introduces**: modular control-rate pipeline.
- **Patterns featured**:
  - `RateSourceComponent` -> `RateSchedulerComponent` -> `RateTransformerComponent`
  - Piecewise-constant linear predictors (`get_linear_predictor`)
  - `ModeChange` scheduling and per-component event invalidation (`advance_version`)
- **Output points of interest**:
  - Scheduled `ModeChange` timing under piecewise-constant rates.
  - Rate propagation consistency (`incoming_rate_tph` -> internal out rate -> converted out rate).
  - Stability of stockpile integration between sparse threshold-crossing events.
- **Visualize / plot**:
  - `--viz`: useful to inspect low-event-count threshold-crossing behavior.
  - `--plot`: available when post-run plotting is enabled in runner flow.

### `drs_5_crusher_tickwise_two_stage_operation_mode.py`
- **Meaning**: Two-stage tickwise chain (crusher -> grinder), each with independent modes.
- **Introduces**: multi-stage operation-mode interactions and optional plotting.
- **Patterns featured**:
  - Per-stage state and mode tracking
  - Stage-specific thresholds/capacities
  - Simulation-owned plotting in `post_run`
- **Output points of interest**:
  - Grinder state trend under upstream crusher variability.
  - Desynchronization of crusher/grinder mode changes.
  - Per-step processed tonnes (`processed_tonnes_step`) and stage coupling effects.
- **Visualize / plot**:
  - `--viz`: useful for event-level chain diagnostics.
  - `--plot`: primary analysis mode here; use it to inspect configured target series.

---

## Generated Prototype Output

### `generated_simulation.py`
- **Meaning**: Auto-generated scaffold from the simulation-designer prototype.
- **Introduces**: generated baseline wiring.
- **Patterns featured**:
  - Basic source/delay/sink scaffold with startup generate
  - Manual-review marker and editable generated structure
  - Useful as a starting point, not canonical style
- **Output points of interest**:
  - Basic end-to-end event flow only; intended for manual extension.
  - Verification that generated wiring runs after edits.
- **Visualize / plot**:
  - `--viz`: useful for quick sanity check of generated topology.
  - `--plot`: typically not implemented unless user extends `post_run`.

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
