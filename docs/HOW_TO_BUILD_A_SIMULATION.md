# How To Build a Simulation

This guide shows how to build simulations in this repository, starting from the three simulation types used here, then giving one build recipe for each.

---

## The 3 Simulation Types

### 1) DES (Discrete-Event Simulation)
- **What it is**: State changes only when events occur.
- **When to use**: Queues, delays, resource handshakes, routing logic, and most workflow/process models.
- **Mental model**: Build components, wire with `engine.connect(...)`, and schedule only the next events you need.

### 2) DRS Tickwise (Rate modeled with regular discrete updates)
- **What it is**: Still DES under the hood, but rates/inventory are updated at regular ticks (for example every 1.0 time units).
- **When to use**: Inventory/stockpile dynamics where fixed-step updates are simple and good enough.
- **Mental model**: A source or scheduler emits recurring events; handlers update stock/rates each tick.

### 3) DRS Threshold-Crossing (Event-sparse rate control)
- **What it is**: Instead of fixed ticks, the model predicts the next meaningful change time (such as crossing a threshold) and schedules only that.
- **When to use**: Piecewise-constant-rate systems where you want fewer events and direct control logic.
- **Mental model**: Predict next crossing, schedule `ModeChange`/`RateUpdate`, and invalidate stale future events with component versioning when needed.

---

## Build Recipe 1: DES Simulation

Use this for classic flow models (example references: `des_1_simple.py`, `des_4_queue_credit_delay.py`, `des_7_resource_bottleneck.py`).

1. **Create engine**
   - `engine = Engine(visualize=visualize, time_limit=...)`
2. **Seed startup events**
   - Usually `Event(0, "source", "Generate", {}, {})`
3. **Define components**
   - `SourceComponent`, `DelayComponent`, `TransformerComponent`, `SinkComponent`, or queue/resource components
4. **Initialize user state (optional)**
   - Set `component.state` keys before run
5. **Register components and connect topology**
   - `engine.add_component(c)`
   - `engine.connect(upstream, downstream)`
6. **Run and inspect**
   - `engine.run()`
   - Inspect sink records and `state_history` for tracked components

**What to inspect in output**
- Entity correctness at sinks (shape, fields, ordering).
- Queue sizes / delay occupancy over time (if tracked).
- Throughput and bottlenecks (for queue/resource models).

**Visualization / plotting**
- Use `--viz` for flow debugging and handshake timing.
- Use `--plot` only if the simulation defines plot logic in `post_run`.

---

## Build Recipe 2: DRS Tickwise Simulation

Use this for regular-step stockpile/rate systems (example references: `drs_1_crusher_tickwise.py`, `drs_2_crusher_tickwise_with_operation_mode.py`, `drs_5_crusher_tickwise_two_stage_operation_mode.py`).

1. **Start from DES structure**
   - Engine + startup + components + connects
2. **Create periodic trigger**
   - Source with fixed interval (`ConstantDistribution(1.0)` is common)
3. **Track dynamic state on components**
   - Stockpile, mode, totals in/out, per-step processed amount
4. **Update state every step in handlers**
   - Read from `ctx.entity` and `ctx.component.state`
5. **(Optional) Use operation modes**
   - Add modes/triggers with `with_operational_mode(...)`
6. **Run and plot state series**
   - Stockpile and mode changes are usually the key diagnostics

**What to inspect in output**
- Oscillation shape (sawtooth/flat/growing stockpile).
- Mode transitions versus threshold settings.
- Stage coupling behavior in multi-stage models (crusher -> grinder).

**Visualization / plotting**
- `--viz`: event-level debugging.
- `--plot`: preferred for trend analysis (stockpile or processed-tonnes series).

---

## Build Recipe 3: DRS Threshold-Crossing Simulation

Use this when rate regimes are piecewise constant and you want sparse events (example reference: `drs_4_crusher_threshold_crossing_intended_design.py`).

1. **Use rate-oriented components**
   - `RateSourceComponent` for startup or external rate signals
   - `RateSchedulerComponent` for inventory/rate dynamics + mode scheduling
   - `RateTransformerComponent` for downstream rate conversion/mapping
2. **Define predictors**
   - Use helpers like `get_linear_predictor(...)` for high/low crossings
3. **Define mode triggers and mode data**
   - `OperationModeTrigger`, `OperationMode`
4. **Advance state to current event time**
   - Integrate inventory from last update time to `engine.get_current_time()`
5. **Schedule next crossing event**
   - Emit `ModeChange`/`RateUpdate` at predicted time
6. **Handle staleness**
   - Call `component.advance_version()` when rescheduling makes prior projections obsolete

**What to inspect in output**
- Correctness of predicted crossing times.
- Event sparsity versus tickwise equivalent.
- Consistency of incoming/internal/outgoing rates through the pipeline.

**Visualization / plotting**
- `--viz`: good for validating sparse control-event ordering.
- `--plot`: useful when post-run exposes stock/rate trajectories.

---

## Practical Starting Point

- Start with `des_1_simple.py` for skeleton.
- Move to `des_3_converger_splitter.py` or `des_4_queue_credit_delay.py` for structure.
- Choose one DRS style:
  - Tickwise first (`drs_1`/`drs_2`) for easier iteration.
  - Threshold-crossing (`drs_4`) when you want fewer, smarter scheduled events.

Run any simulation with:

```bash
python -m src.run --file <simulation_name.py> [--viz] [--plot]
```
