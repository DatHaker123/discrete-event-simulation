# Discrete simulation — Documentation

This project is a **discrete simulation** framework in two layers:

1. **Core = discrete-event simulation (DES)** — The runtime is built around a **future-event list**: simulation time jumps from event to event; components **schedule** and **handle** typed events. There is no fixed time step; state changes only when an event is processed. That is the **base program**: engine, queue, `Event`, handlers using `SimulationContext(engine, event, component)`, wiring, sinks, delays, transformers, and sources that emit entities on a schedule you define in event logic.

2. **Discrete-rate simulation (DRS) features on top** — When a model **pre-schedules many future instants** (e.g. threshold-crossing control updates), the queue can hold work that later becomes invalid (regime changes, crossing predictions becoming obsolete). Each **component** owns a monotonic **`version`** and **`advance_version()`**; **`Event.version`** records the target component’s version at enqueue time. That lets you **invalidate already-queued events for that handler** without canceling them individually. Optional helpers in `src/modules/operation_mode.py` and `src/modules/threshold_crossing.py` support DRS-style modelling but are not required for plain DES.

**What this entails in practice**

- **DES-only models** use the engine and components as usual; **`Component.advance_version()`** is optional and often unused. You express the future entirely by **scheduling only events you still want** from each handler.
- **DRS-oriented models** combine the same DES machinery with **recurring scheduling** (e.g. tickwise `Generate`) and, when physics or policy changes, call **`some_component.advance_version()`** so stale queued events **for that component** are **skipped** in `run()`. The **`version`** field on each `Event` records the target component’s version at enqueue time; **`add_event`** stamps it from the handler identified by **`handler_id`**.

See *Discrete simulation styles* below for a concise comparison.

---

## Overview

- **Engine** (`src/core/engine.py`): Simulation time, priority event queue, registered components, optional `simulation_variables` dict, and `run()` dispatch. When `time_limit` is set, an internal `"End"` event stops the run (entity payload is `{}`).
- **Events** (`src/core/events.py`): Dated messages with a type, target `handler_id`, **`entity`** payload, and **`version`** (epoch stamp). **`Entity`** is a type alias for **`dict[str, Any]`**. Tie-breaking uses `priority_for_event_type()` when two events share the same time.
- **Epoch / staleness** (see *Discrete simulation styles*): Each **component** has **`version`** and **`advance_version()`**. **`add_event`** sets **`event.version`** from the **target** component’s version (or **`0`** if no handler is registered yet, e.g. internal **`"End"`**). Events popped with **`event.version < component.version`** for that **`handler_id`** are skipped (not dispatched). The internal **`"End"`** event is recognized before the stale check and still stops **`run()`**.

### Discrete simulation styles

- **Discrete-event simulation (DES)** — The **base** semantics of this codebase. State changes only when an event occurs. A model can be **fully event-driven**: every future change is scheduled by the logic that runs on the current event, so the queue need not hold a long horizon of “tentative” instants. In that setting, **`Component.advance_version()`** is often unnecessary: you simply schedule the events you still want and never enqueue superseded work.
- **Discrete-rate simulation (DRS)** — **Additional** concern: many future sampling or processing instants are **pre-scheduled** ahead of time (e.g. a source that queues the next **`Generate`** at each tick). When a **threshold crossing** or other structural change invalidates some of those future instants, **`advance_version()`** on the relevant **component(s)** marks earlier queued work for that handler stale so the engine **skips** those events, without having to dequeue them one-by-one by hand.

**Event versions** are aimed at DRS-style queues: they invalidate **already-queued** work when the “rate” or schedule implied by past scheduling is no longer valid. They are **not** required for a purely DES formulation where the queue only ever contains events you still intend to process.

- **Components** (`src/core/components.py`): Register handlers per event type. Each handler receives a **`SimulationContext`** object (`engine`, `event`, `component`) so you can use `component.state`, `component.output`, etc. without capturing the component in a closure. `SimulationContext` also exposes `entity` as an alias for `event.entity`.
- **Output**: Logs under `output/` (and optionally console). With `visualize=True`, each run can write a UUID-named PDF (graph + queue per step). CLI simulation scripts expose this as opt-in via `--viz` (default off). Sinks keep `records`; **`get_records_as_printable_string`** (`src/modules/stats.py`) formats sink tables and optional **state history**.

### `src.core` public exports

Import from `src.core` (see `src/core/__init__.py`): **`Engine`**, **`EventQueue`**, **`Event`**, **`Entity`**, **`priority_for_event_type`**, **`Component`**, **`SingleIOComponent`**, **`SourceComponent`**, **`SinkComponent`**, **`DelayComponent`**, **`TransformerComponent`**, **`AssertComponent`**.

---

## Installation

- **Python**: 3.12+
- **Dependencies**: `uv sync` or `pip install -e .` (see `pyproject.toml`: `python-dotenv`, `matplotlib`, `networkx`).

---

## Project structure

```
discrete-event-simulation/
├── pyproject.toml
├── .env                    # RANDOM_SEED, MAX_SIM_TIME, EPS_TIME, VERBOSE (optional)
├── docs/
│   └── DOCUMENTATION.md    # This file
├── output/                 # Runtime: logs, PDFs, optional PNGs from examples
│   ├── sim.log
│   └── <uuid>.pdf
└── src/
    ├── run.py              # Central CLI runner (--file, --viz, --plot); simulations own post-run output
    ├── core/               # DES core: engine, events, components
    │   ├── __init__.py     # Re-exports public API
    │   ├── engine.py       # queue, run(); stamps event.version from target component
    │   ├── events.py       # Event, Entity, priority_for_event_type
    │   └── components.py
    ├── modules/            # Logging, stats, distributions, visualization, DRS helpers
    │   ├── logger.py
    │   ├── stats.py
    │   ├── utils.py
    │   ├── operation_mode.py    # OperationMode, triggers, mode manager mixin/factory
    │   ├── threshold_crossing.py # Rate components + threshold-crossing helper factories
    │   ├── sim_output.py     # RunOptions + SimulationPlot (simulation-owned plotting helpers)
    │   └── visualization.py
    └── simulations/
        ├── des_simple.py             # source → delay → sink
        ├── des_simple2.py            # source → delay → transformer → sink
        ├── drs_crusher_1_tickwise.py
        ├── drs_crusher_2_tickwise_with_operation_mode.py
        ├── drs_crusher_5_tickwise_two_stage_with_operation_mode.py
        ├── drs_crusher_3_threshold_crossing.py
        └── drs_crusher_4_threshold_crossing_intended_design.py
```

---

## Core concepts

### Entity and `Event` (`src/core/events.py`)

- **`Entity`**: `TypeAlias = dict[str, Any]`. All event payloads are **dicts**; values are model-defined (numbers, strings, nested structures, etc.).
- **`Event(time, handler_id, type, entity, kwargs, version=0)`** (dataclass, `slots=True`)
  - **`time`**: Simulation time when the event is processed.
  - **`handler_id`**: `component_id` of the component that handles it.
  - **`type`**: String (`"Generate"`, `"Arrival"`, `"Departure"`, `"RateUpdate"`, `"ModeChange"`, `"End"`, …) — selects the handler and, with `priority_for_event_type()`, orders same-time events.
  - **`entity`**: **`Entity`**. Use **`{}`** when no fields are needed (e.g. startup **`Generate`** before the source fills it; internal **`End`** event). The **`Generate`** event’s **`entity`** is ignored by **`SourceComponent.default_handle_generate`** when an **`entity_generator`** is supplied — the generated dict becomes the **`Departure`** payload.
  - **`kwargs`**: Reserved for future use (plain `dict` in the dataclass).
  - **`version`**: Snapshot of the **target** component’s **`version`** when the event enters the queue ( **`add_event`** overwrites the dataclass default). Stale when **`event.version < component.version`** for **`handler_id`**. A **DRS-layer** feature; DES-only models often never bump the component version (see the introduction above).

- **`priority_for_event_type(event_type) -> int`**  
  Lower value = higher priority when times are equal (current built-ins: `RateUpdate`/`ModeChange` first, then `Generate`, then `Arrival`, then `Departure`; other types get a default priority).

### Engine (`src/core/engine.py`)

- **`Engine(time_limit=None, visualize=False, output_dir="output")`**
  - **`time_limit`**: When not `None`, schedules an internal **`"End"`** event at that time to stop the run. If omitted, **`MAX_SIM_TIME`** is used as fallback from env. The **`End`** event uses **`entity={}`**.
  - **`visualize`**: If `True`, builds a PDF of frames under **`output_dir`**.
  - **`simulation_variables`**: `dict[str, Any]` for model-wide counters or parameters.

- **`add_startup_event(event)`**: Register startup events queued at the start of `run()` (e.g. first **`Generate`** per source).

- **`add_component` / `remove_component`** — Register components by **`component_id`** (must match **`handler_id`** on events).

- **`add_event(event)`** — Deep-copies **`event.entity`** (payload isolation), sets **`event.version`** from the registered component with **`component_id == event.handler_id`** (or **`0`** if none, e.g. **`"End"`**), then pushes onto the priority queue.

- **`run(on_step=None)`** — Drains the queue. For each event (except **`"End"`**, which stops the loop): resolve the target component; if **`event.version < component.version`**, skip without calling handlers or **`on_step`**. Otherwise dispatches **`component.handle_event(self, event)`** for events that pass the time-limit filter. Optional **`on_step(sim_time, event, queue_snapshot)`** after each **dispatched** step (and once for initial state when visualization or **`on_step`** is used).

- **`get_current_time()`** — Current simulation time after the last processed event.

- **`get_results()`** — Registered components (for stats).

- **`get_graph()`** — **`(node_ids, edges)`** from each component’s **`outputs`** list (for visualization).

### Components (`src/core/components.py`)

#### Base: `Component(component_id, type, track_state=False)`

- **`outputs` / `inputs`** — Read-only tuple views of downstream/upstream components. Topology is engine-owned and mutates only via **`engine.connect(...)`** / **`engine.disconnect(...)`**.
- **`state`**: `dict[str, Any]` — per-component mutable state.
- **`state_history`**: When **`track_state=True`**, after each successful handler, append **`(sim_time, dict(state))`** (shallow copy of **`state`**).
- **`set_handleable_event(event_type, handler)`** — Registers an **`EventHandler`**.
- **`handle_event(engine, event)`** — Invokes the handler for **`event.type`**, then records state history if **`track_state`**.
- **`version`** (read-only) / **`advance_version() -> int`** — Per-component epoch; **`add_event`** copies **`version`** onto each event targeting this **`component_id`**. Call **`advance_version()`** on this instance to invalidate queued events for this handler only (**DRS**); **DES-only** models often never call it.

**`EventHandler`**: `Callable[[SimulationContext], None]`

`SimulationContext.component` is the concrete receiver, so handlers can schedule:

```python
Event(t, component.output.component_id, "Arrival", entity_dict, {})
```

#### `SingleIOComponent`

- Uses engine-owned topology with **`engine.connect(c1, c2)`**.  
  For single-IO blocks, **`output`** and **`input`** expect exactly one downstream/upstream peer.
- **`default_handle_departure(ctx)`** — Schedules **`Arrival`** at **`output.component_id`** with the same logical payload as **`event.entity`**.

#### `SourceComponent(component_id, entity_generator, interval=None, track_state=False)`

- **`entity_generator(ctx) -> Entity`** — Called on each **`Generate`**. Return value becomes the entity on the internal same-time **`Departure`**, then forwarded downstream as **`Arrival`**. The **`entity`** field on the **`Generate`** event itself is not used by the default source logic.
- **`interval`**: If set (**`Distribution`**), schedules the next **`Generate`** on self at **`now + interval.sample()`**. If **`None`**, only startup events added via **`engine.add_startup_event(...)`** (or manually queued **`Generate`**) drive output.
- Flow: **`Generate`** → **`Departure`** (self, entity from generator) → **`Arrival`** (output). **`default_handle_generate`** also schedules the next **`Generate`** with **`entity={}`** when **`interval`** is set.

#### `DelayComponent(component_id, delay_interval, capacity=1, track_state=False)`

- **`Arrival`**: Samples delay, queues **`Departure`** at **`now + delay`**, stores **`(departure_time, entity)`** in **`content`**.
- **`Departure`**: Removes matching **`(time, entity)`**, then **`default_handle_departure`**.

#### `SinkComponent(component_id, track_state=False)`

- **`Arrival`**: Appends **`(current_time, event.entity)`** to **`records`**.

#### `AssertComponent(component_id, condition, fail_handler=None, track_state=False)`

- **`condition(ctx) -> bool`**. If false, **`fail_handler`** runs (default drop or error). If true, forwards **`Arrival`** to output.

#### `TransformerComponent(component_id, transform_function, track_state=False)`

- **`transform_function(ctx) -> Entity`** — Returns a new **`dict`** payload; a same-time **`Departure`** is scheduled with that entity, then **`default_handle_departure`** forwards it.

#### `SplitterComponent(component_id, splitter_function, track_state=False)`

- **`splitter_function(ctx) -> dict[str, Entity]`** — Returns a mapping keyed by downstream `component_id`.
- Unknown keys raise an error.
- Omitted downstream IDs are allowed and mean “emit nothing” for that branch on that event.

Default handlers are **public methods** (e.g. **`SourceComponent.default_handle_generate`**) so subclasses or wrappers can delegate. Call them with a proper **`SimulationContext`** for the intended concrete component.

---

## Operation modes (`src/modules/operation_mode.py`)

Optional helpers for **mode-driven control** (e.g. crusher fast vs slow) without ad-hoc nesting:

- **`OperationModeTrigger`**:
  - `check: Callable[[SimulationContext], bool]`
  - optional `expected_next_trigger_time: Callable[[SimulationContext, dict[str, float]], float | None]` (mainly for continuous threshold-crossing models)
- **`OperationMode`**:
  - `name`, `triggers`, `data`, `priority`
- **`HasOperationModeManager`** (mixin):
  - `add_mode(mode)`
  - `update_current_mode(ctx)`
  - `get_next_mode_change(ctx, delta)`
- **`with_operational_mode(base_cls)`**:
  - Factory that builds a mode-enabled class from any component base class.

Example simulation: **`src/simulations/drs_crusher_2_tickwise_with_operation_mode.py`**.

---

## Threshold-crossing helpers (`src/modules/threshold_crossing.py`)

Utilities and components for continuous-state / piecewise-constant-rate DRS models:

- **`get_linear_predictor(...)`**  
  Factory for trigger prediction callbacks used by `OperationModeTrigger.expected_next_trigger_time`.
- **`get_advancer_linear_inventory_state(...)`**  
  Factory returning a state advancer callable (`SimulationContext -> None`) for one-dimensional inventory integration.
- **`get_default_rate_update_handler(...)`**  
  Default scheduler handler for `RateUpdate`/`ModeChange` loops. It:
  1. advances state,
  2. applies incoming upstream rate updates,
  3. resolves mode and internal processing rate,
  4. emits self `Departure`,
  5. predicts and self-schedules next `ModeChange` (with component version invalidation).

Specialized components:

- **`RateSourceComponent`**  
  Source-style control emitter with flow: `Generate -> Departure -> downstream RateUpdate`.
- **`RateSchedulerComponent`**  
  Mode-driven scheduler component with flow: `RateUpdate/ModeChange -> self Departure -> downstream RateUpdate`.
- **`RateTransformerComponent`**  
  Pure control-stream mapper with flow: `RateUpdate -> self Departure -> downstream RateUpdate`.

Example simulation using the intended split design:
**`src/simulations/drs_crusher_4_threshold_crossing_intended_design.py`**.

Compatibility note:

- The old helper **`get_departure_event_forwarder(...)`** was intentionally removed during handler/component cleanup.
- Older simulations that still import it (for example legacy trace files) are expected to fail until migrated to explicit handler functions or to `RateSourceComponent`.

---

## Building a simulation

1. Create **`Engine`** (optional **`time_limit`**, **`visualize`**, **`output_dir`**). Optionally fill **`engine.simulation_variables`**.
2. Instantiate components.
3. **`engine.add_component(...)`** for each block (IDs must match event **`handler_id`**s).
4. Add startup events with **`engine.add_startup_event(...)`**.
5. **`engine.run()`**.
6. Inspect **`get_records_as_printable_string(engine.get_results())`** or component **`state`** / **`state_history`**.

Minimal example (see **`src/simulations/des_simple.py`**):

```python
from src.core import DelayComponent, Engine, Event, SinkComponent, SourceComponent
from src.modules import get_records_as_printable_string
from src.modules.utils import UniformDistribution

engine = Engine(visualize=False)
engine.add_startup_event(Event(0, "source", "Generate", {}, {}))
source = SourceComponent(
    "source",
    lambda _ctx: {"value": "token"},
    UniformDistribution(0, 10),
)
delay = DelayComponent("delay", UniformDistribution(0, 10), capacity=1000)
sink = SinkComponent("sink")
for c in (source, delay, sink):
    engine.add_component(c)
engine.connect(source, delay)
engine.connect(delay, sink)
engine.run()
print(get_records_as_printable_string(engine.get_results()))
```

---

## Configuration

### Environment (`.env`)

- **`RANDOM_SEED`** — Seeded at import of **`src.modules.utils`** for reproducible distributions.
- **`MAX_SIM_TIME`** — Used as fallback engine **`time_limit`** when `Engine(time_limit=...)` is omitted.
- **`EPS_TIME`** — Small epsilon used by threshold-crossing helpers for near-immediate rescheduling.
- **`VERBOSE`** — `1` / `true` / `yes` / `on` → DEBUG logging.

### Logging (`src/modules/logger.py`)

- **`setup_logging(...)`** — Call once; log file under **`output/`** by default.
- **`get_logger(name)`** — Use **`extra={"sim_time": engine.get_current_time()}`** for simulation time in log lines.

---

## Statistics (`src/modules/stats.py`)

- **`get_records_as_printable_string(components)`** — Intended for **`engine.get_results()`**.
- **`state_key_series_from_history(component, key)`** — **`(time, value)`** series from **`state_history`** (last snapshot wins when times repeat).
- **`state_history_snapshots(component)`** — **`list[(time, state_dict)]`**.
- **`plot_time_series(series, ...)`** — Plots **`(x, y)`**; optional **`horizontal_lines`** as **`(y, label)`** tuples.

Output sections:

1. **Sink records** — For components with **`records`**: table with **`idx`**, **`arrival t`**, **`dt`**, **`entity`** (dicts pretty-printed).
2. **Recorded component states** — For components with **`state_history`**: timestamped shallow snapshots of **`state`**.

If a section is empty, a short placeholder line is printed.

---

## Visualization (`src/modules/visualization.py`)

When **`visualize=True`**, **`run()`** builds a **`Visualizer`**, calls **`add_frame`** for the initial queue and for selected event steps, then **`close()`** to finalize the PDF. Frame selection includes material-flow events (`Generate` / `Arrival` / `Departure`) and key control-flow events (`RateUpdate` / `ModeChange`) with same-time control deduplication to keep PDFs readable.

---

## Extending

- **Custom components**: Subclass **`Component`** or **`SingleIOComponent`**, register handlers with **`set_handleable_event`**, schedule events with **`engine.add_event(...)`**, and rely on engine-owned wiring via **`engine.connect(...)`**. Use **`Entity`** (**`dict[str, Any]`**) for payloads.
- **Epochs / `Component.advance_version`**: **DRS-layer** tool when a discrete-rate-style model has obsolete future events **for a given handler** in the queue; **DES-only** models can usually rely on explicit scheduling alone (see the introduction).
- **Replace or wrap a default handler**: After construction, **`set_handleable_event("Arrival", my_handler)`**. Inside **`my_handler`**, call the original public method on the instance with a proper `SimulationContext` so pre/post logic composes cleanly.
- **Custom distributions**: Subclass **`Distribution`** in **`src/modules/utils.py`** and implement **`sample() -> float`**.
- **Event priority**: Adjust **`priority_for_event_type`** in **`src/core/events.py`**.

---

## Running the examples

Use the central runner to execute any simulation module and share one set of CLI flags for
visualization, plotting, and logging. What gets printed/plotted is defined by each simulation
via `post_run(...)` (or `simulation_post_run(...)`).

By default, **`--file`** is resolved under **`src/simulations`**. These are equivalent:

```bash
uv run python -m src.run --file drs_crusher_4_threshold_crossing_intended_design.py
uv run python -m src.run --file drs_crusher_4_threshold_crossing_intended_design
uv run python -m src.run --file src/simulations/drs_crusher_4_threshold_crossing_intended_design.py
```

From the project root:

```bash
uv run python -m src.run --file src/simulations/des_simple.py
```

```bash
uv run python -m src.run --file src/simulations/des_simple2.py
```

DRS stockpile / crusher (inline thresholds). Pass **`--viz`** to generate visualization PDF frames and **`--plot`** to enable simulation-defined plotting (for example, a UUID-named PNG under **`output/`**):

```bash
uv run python -m src.run --file src/simulations/drs_crusher_1_tickwise.py
uv run python -m src.run --file src/simulations/drs_crusher_1_tickwise.py --viz
uv run python -m src.run --file src/simulations/drs_crusher_1_tickwise.py --plot
```

Same scenario with operation modes from **`src/modules/operation_mode.py`**:

```bash
uv run python -m src.run --file src/simulations/drs_crusher_2_tickwise_with_operation_mode.py
uv run python -m src.run --file src/simulations/drs_crusher_2_tickwise_with_operation_mode.py --viz
uv run python -m src.run --file src/simulations/drs_crusher_2_tickwise_with_operation_mode.py --plot

# Two-stage variant: source -> crusher -> grinder -> sink (plot focuses on grinder stockpile)
uv run python -m src.run --file drs_crusher_5_tickwise_two_stage_with_operation_mode.py
uv run python -m src.run --file drs_crusher_5_tickwise_two_stage_with_operation_mode.py --plot
```

Threshold-crossing reference runs:

```bash
uv run python -m src.run --file src/simulations/drs_crusher_3_threshold_crossing.py
uv run python -m src.run --file src/simulations/drs_crusher_4_threshold_crossing_intended_design.py
uv run python -m src.run --file src/simulations/drs_crusher_4_threshold_crossing_intended_design.py --viz
```

`src.run` also supports **`--function`** to select a specific callable, and logging controls such
as **`--log-level`**, **`--log-file`**, and **`--console`**. The **`--plot`** flag is boolean only;
plot targets and plotted metrics are simulation-owned.

These examples typically write **`output/sim.log`**. Add **`--viz`** to produce a UUID **`output/*.pdf`** for that run.
