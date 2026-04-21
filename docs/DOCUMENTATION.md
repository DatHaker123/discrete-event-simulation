# Discrete simulation — Documentation

This project is a **discrete simulation** framework in two layers:

1. **Core = discrete-event simulation (DES)** — The runtime is built around a **future-event list**: simulation time jumps from event to event; components **schedule** and **handle** typed events. There is no fixed time step; state changes only when an event is processed. That is the **base program**: engine, queue, `Event`, handlers `(engine, event, component)`, wiring, sinks, delays, transformers, and sources that emit entities on a schedule you define in event logic.

2. **Discrete-rate simulation (DRS) features on top** — When a model **pre-schedules many future instants** (e.g. a source that always queues the next `Generate` at each tick), the queue can hold work that later becomes invalid (threshold crossings, regime changes). Each **component** owns a monotonic **`version`** and **`advance_version()`**; **`Event.version`** records the target component’s version at enqueue time. That lets you **invalidate already-queued events for that handler** without canceling them individually. Optional helpers in `src/modules/DRS_utils.py` (mode rules) support DRS-style modelling but are not required for plain DES.

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

- **Components** (`src/core/components.py`): Register handlers per event type. Each handler receives **`(engine, event, component)`** so you can use `component.state`, `component.output`, etc. without capturing the component in a closure.
- **Output**: Logs under `output/` (and optionally console). With `visualize=True`, each run can write a UUID-named PDF (graph + queue per step). Sinks keep `records`; **`get_records_as_printable_string`** (`src/modules/stats.py`) formats sink tables and optional **state history**.

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
├── .env                    # RANDOM_SEED, MAX_SIM_TIME, VERBOSE (optional)
├── docs/
│   └── DOCUMENTATION.md    # This file
├── output/                 # Runtime: logs, PDFs, optional PNGs from examples
│   ├── sim.log
│   └── <uuid>.pdf
└── src/
    ├── core/               # DES core: engine, events, components
    │   ├── __init__.py     # Re-exports public API
    │   ├── engine.py       # queue, run(); stamps event.version from target component
    │   ├── events.py       # Event, Entity, priority_for_event_type
    │   └── components.py
    ├── modules/            # Logging, stats, distributions, visualization, DRS helpers
    │   ├── logger.py
    │   ├── stats.py
    │   ├── utils.py
    │   ├── DRS_utils.py    # ModeResolver, ModeRule, Constraint (optional DRS modelling)
    │   └── visualization.py
    └── simulations/
        ├── simple.py                 # source → delay → sink
        ├── simple2.py                # source → delay → transformer → sink
        ├── drs_crusher_1_tickwise.py # stockpile + two-mode crusher (thresholds in code)
        └── drs_crusher_2_tickwise_with_utils.py  # same idea; mode rules via DRS_utils
```

---

## Core concepts

### Entity and `Event` (`src/core/events.py`)

- **`Entity`**: `TypeAlias = dict[str, Any]`. All event payloads are **dicts**; values are model-defined (numbers, strings, nested structures, etc.).
- **`Event(time, handler_id, type, entity, kwargs, version=0)`** (dataclass, `slots=True`)
  - **`time`**: Simulation time when the event is processed.
  - **`handler_id`**: `component_id` of the component that handles it.
  - **`type`**: String (`"Generate"`, `"Arrival"`, `"Departure"`, `"End"`, …) — selects the handler and, with `priority_for_event_type()`, orders same-time events.
  - **`entity`**: **`Entity`**. Use **`{}`** when no fields are needed (e.g. startup **`Generate`** before the source fills it; internal **`End`** event). The **`Generate`** event’s **`entity`** is ignored by **`SourceComponent.default_handle_generate`** when an **`entity_generator`** is supplied — the generated dict becomes the **`Departure`** payload.
  - **`kwargs`**: Reserved for future use (plain `dict` in the dataclass).
  - **`version`**: Snapshot of the **target** component’s **`version`** when the event enters the queue ( **`add_event`** overwrites the dataclass default). Stale when **`event.version < component.version`** for **`handler_id`**. A **DRS-layer** feature; DES-only models often never bump the component version (see the introduction above).

- **`priority_for_event_type(event_type) -> int`**  
  Lower value = higher priority when times are equal (default order: `Generate`, then `Arrival`, then `Departure`; other types get a default priority).

### Engine (`src/core/engine.py`)

- **`Engine(time_limit=None, startup_events=None, visualize=True, output_dir="output")`**
  - **`time_limit`**: When not `None`, schedules an **`"End"`** event at that time to stop the run. Overridable by env **`MAX_SIM_TIME`**. The **`End`** event uses **`entity={}`**.
  - **`startup_events`**: Queued at the start of `run()` (e.g. first **`Generate`** per source, often **`Event(0, "source", "Generate", {}, {})`**).
  - **`visualize`**: If `True`, builds a PDF of frames under **`output_dir`**.
  - **`simulation_variables`**: `dict[str, Any]` for model-wide counters or parameters.

- **`add_component` / `remove_component`** — Register components by **`component_id`** (must match **`handler_id`** on events).

- **`add_event(event)`** — Sets **`event.version`** from the registered component with **`component_id == event.handler_id`**, or **`0`** if none (e.g. **`"End"`**), then pushes onto the priority queue.

- **`run(on_step=None)`** — Drains the queue. For each event (except **`"End"`**, which stops the loop): resolve the target component; if **`event.version < component.version`**, skip without calling handlers or **`on_step`**. Otherwise dispatches **`component.handle_event(self, event)`** for events that pass the time-limit filter. Optional **`on_step(sim_time, event, queue_snapshot)`** after each **dispatched** step (and once for initial state when visualization or **`on_step`** is used).

- **`get_current_time()`** — Current simulation time after the last processed event.

- **`get_results()`** — Registered components (for stats).

- **`get_graph()`** — **`(node_ids, edges)`** from each component’s **`outputs`** list (for visualization).

### Components (`src/core/components.py`)

#### Base: `Component(component_id, type, track_state=False)`

- **`outputs` / `inputs`** — Wiring lists (**`SingleIOComponent`** enforces a single downstream for the main chain).
- **`state`**: `dict[str, Any]` — per-component mutable state.
- **`state_history`**: When **`track_state=True`**, after each successful handler, append **`(sim_time, dict(state))`** (shallow copy of **`state`**).
- **`set_handleable_event(event_type, handler)`** — Registers an **`EventHandler`**.
- **`handle_event(engine, event)`** — Invokes the handler for **`event.type`**, then records state history if **`track_state`**.
- **`version`** (read-only) / **`advance_version() -> int`** — Per-component epoch; **`add_event`** copies **`version`** onto each event targeting this **`component_id`**. Call **`advance_version()`** on this instance to invalidate queued events for this handler only (**DRS**); **DES-only** models often never call it.

**`EventHandler`**: `Callable[[Engine, Event, Component], None]`

The third argument is the **concrete component instance** receiving the event, so handlers can schedule:

```python
Event(t, component.output.component_id, "Arrival", entity_dict, {})
```

#### `SingleIOComponent`

- **`output_to(other)` / `disconnect_output_to(other)`** — At most one primary output; **`output`** property returns that peer.
- **`default_handle_departure(engine, event, component)`** — Schedules **`Arrival`** at **`output.component_id`** with the same **`event.entity`**.

#### `SourceComponent(component_id, entity_generator, interval=None, track_state=False)`

- **`entity_generator(engine, event, component) -> Entity`** — Called on each **`Generate`**. Return value becomes the entity on the internal same-time **`Departure`**, then forwarded downstream as **`Arrival`**. The **`entity`** field on the **`Generate`** event itself is not used by the default source logic.
- **`interval`**: If set (**`Distribution`**), schedules the next **`Generate`** on self at **`now + interval.sample()`**. If **`None`**, only **`startup_events`** or manually queued **`Generate`** events drive output.
- Flow: **`Generate`** → **`Departure`** (self, entity from generator) → **`Arrival`** (output). **`default_handle_generate`** also schedules the next **`Generate`** with **`entity={}`** when **`interval`** is set.

#### `DelayComponent(component_id, delay_interval, capacity=1, track_state=False)`

- **`Arrival`**: Samples delay, queues **`Departure`** at **`now + delay`**, stores **`(departure_time, entity)`** in **`content`**.
- **`Departure`**: Removes matching **`(time, entity)`**, then **`default_handle_departure`**.

#### `SinkComponent(component_id, track_state=False)`

- **`Arrival`**: Appends **`(current_time, event.entity)`** to **`records`**.

#### `AssertComponent(component_id, condition, fail_handler=None, track_state=False)`

- **`condition(engine, event, component) -> bool`**. If false, **`fail_handler`** runs (default drop or error). If true, forwards **`Arrival`** to output.

#### `TransformerComponent(component_id, transform_function, track_state=False)`

- **`transform_function(engine, event, component) -> Entity`** — Returns a new **`dict`** payload; a same-time **`Departure`** is scheduled with that entity, then **`default_handle_departure`** forwards it.

Default handlers are **public methods** (e.g. **`SourceComponent.default_handle_generate`**) so subclasses or wrappers can delegate. Call them with **`(engine, event, component)`** and ensure **`component`** is the correct concrete type.

---

## Mode rules (`src/modules/DRS_utils.py`)

Optional helpers for **if/then mode** logic (e.g. crusher fast vs slow) without ad-hoc nesting — **DRS-oriented** modelling sugar, not required for DES:

- **`Constraint`**: **`name`**, **`check: Callable[[Engine, Event, Component], bool]`** — same triple as event handlers.
- **`OperationalMode`**: **`name`** (string id) and **`data`** (`dict[str, Any]`; keys and value types are model-defined and not validated here). Use as **`ModeRule.mode`** so **`resolve()`** returns the full mode; handlers index **`data`** by convention (e.g. **`data["crush_speed"].sample()`**).
- **`ModeRule`**: **`name`**, **`mode`** (often an **`OperationalMode`**), **`priority`** (higher runs first in **`resolve`**), optional **`constraints`** list, **`enabled`** flag.
- **`ModeResolver`**: **`add_rule`**, **`remove_rule`**, **`replace_rule`**, **`enable_rule`**, **`disable_rule`**, **`get_rule`**, **`list_rules`**, **`clear_rules`**, **`resolve(engine, event, component, default=None)`**, **`explain(engine, event, component)`** (per-rule match diagnostics).

**`resolve`** walks rules in priority order and returns the first **`mode`** whose constraints all pass; if none match, returns **`default`**.

Example simulation: **`src/simulations/drs_crusher_2_tickwise_with_utils.py`**.

---

## Building a simulation

1. Create **`Engine`** (optional **`startup_events`**, **`time_limit`**, **`visualize`**, **`output_dir`**). Optionally fill **`engine.simulation_variables`**.
2. Instantiate components; wire with **`output_to`**.
3. **`engine.add_component(...)`** for each block (IDs must match event **`handler_id`**s).
4. **`engine.run()`**.
5. Inspect **`get_records_as_printable_string(engine.get_results())`** or component **`state`** / **`state_history`**.

Minimal example (see **`src/simulations/simple.py`**):

```python
from src.core import DelayComponent, Engine, Event, SinkComponent, SourceComponent
from src.modules import get_records_as_printable_string
from src.modules.utils import UniformDistribution

engine = Engine(startup_events=[Event(0, "source", "Generate", {}, {})], visualize=True)
source = SourceComponent(
    "source",
    lambda _e, _evt, _comp: {"value": "token"},
    UniformDistribution(0, 10),
)
delay = DelayComponent("delay", UniformDistribution(0, 10), capacity=1000)
sink = SinkComponent("sink")
source.output_to(delay)
delay.output_to(sink)
for c in (source, delay, sink):
    engine.add_component(c)
engine.run()
print(get_records_as_printable_string(engine.get_results()))
```

---

## Configuration

### Environment (`.env`)

- **`RANDOM_SEED`** — Seeded at import of **`src.modules.utils`** for reproducible distributions.
- **`MAX_SIM_TIME`** — Overrides engine **`time_limit`** when set.
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

With **`visualize=True`** (the engine default), **`run()`** builds a **`Visualizer`**, calls **`add_frame`** for the initial queue and for each **`Generate` / `Arrival` / `Departure`** step, then **`close()`** to finalize the PDF. On Windows, if the console cannot print Unicode arrows in progress text, set **`PYTHONIOENCODING=utf-8`** or adjust logging.

---

## Extending

- **Custom components**: Subclass **`Component`** or **`SingleIOComponent`**, implement **`output_to` / `disconnect_output_to`**, register handlers with **`set_handleable_event`**, schedule events with **`engine.add_event(...)`**. Use **`Entity`** (**`dict[str, Any]`**) for payloads.
- **Epochs / `Component.advance_version`**: **DRS-layer** tool when a discrete-rate-style model has obsolete future events **for a given handler** in the queue; **DES-only** models can usually rely on explicit scheduling alone (see the introduction).
- **Replace or wrap a default handler**: After construction, **`set_handleable_event("Arrival", my_handler)`**. Inside **`my_handler`**, call the original public method on the **instance**, e.g. **`sink.sink_handle_arrival(engine, event, sink)`** for a **`SinkComponent`** named **`sink`**, so pre/post logic composes without rebinding the same name to your wrapper.
- **Custom distributions**: Subclass **`Distribution`** in **`src/modules/utils.py`** and implement **`sample() -> float`**.
- **Event priority**: Adjust **`priority_for_event_type`** in **`src/core/events.py`**.

---

## Running the examples

From the project root:

```bash
uv run python src/simulations/simple.py
```

```bash
uv run python src/simulations/simple2.py
```

DRS stockpile / crusher (inline thresholds). Pass **`--plot`** to write a UUID-named PNG under **`output/`** (see each script’s **`__main__`** block):

```bash
uv run python src/simulations/drs_crusher_1_tickwise.py
uv run python src/simulations/drs_crusher_1_tickwise.py --plot
```

Same scenario with **`ModeResolver`** / **`ModeRule`** / **`Constraint`** from **`src/modules/DRS_utils.py`**:

```bash
uv run python src/simulations/drs_crusher_2_tickwise_with_utils.py
uv run python src/simulations/drs_crusher_2_tickwise_with_utils.py --plot
```

These examples typically write **`output/sim.log`**. With **`visualize=True`**, a new UUID **`output/*.pdf`** is produced per run.
