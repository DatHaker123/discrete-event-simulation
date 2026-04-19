# Discrete-Event Simulation — Documentation

A Python framework for discrete-event simulation (DES): events are processed in time order by components that schedule new events and connect to other components.

---

## Overview

- **Engine**: Simulation time, event queue, registered components, optional `simulation_variables` dict, and `run()` dispatch.
- **Events**: Dated messages with a type, target `handler_id`, and optional **entity** payload. `priority_for_event_type()` in `src/core/events.py` breaks ties when two events share the same time.
- **Components**: Register handlers per event type; each handler receives `(engine, event, component)` so you can use `component.state`, `component.output`, etc. without closures.
- **Output**: Logs under `output/` (and optionally console). With `visualize=True`, each run writes a UUID-named PDF (graph + queue per step). Sinks keep `records`; **`get_records_as_printable_string`** (`src.modules`) formats sink tables and optional **state history**.

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
├── output/                 # Runtime: logs, PDFs
│   ├── sim.log
│   └── <uuid>.pdf
└── src/
    ├── core/               # Engine, events, components
    │   ├── engine.py
    │   ├── events.py
    │   └── components.py
    ├── modules/            # Logging, stats, distributions, visualization
    │   ├── logger.py
    │   ├── stats.py
    │   ├── utils.py
    │   └── visualization.py
    └── simulations/
        ├── simple.py       # source → delay → sink
        ├── simple2.py      # source → delay → transformer → sink (example)
        └── drs_crusher.py  # DRS: constant-rate feed → two-mode crusher (stockpile) → sink
```

---

## Core concepts

### Events (`src/core/events.py`)

- **`Event(time, handler_id, type, entity, kwargs)`** (dataclass)  
  - **`time`**: Simulation time when the event is processed.  
  - **`handler_id`**: `component_id` of the component that handles it.  
  - **`type`**: String (`"Generate"`, `"Arrival"`, `"Departure"`, `"End"`, …) — selects the handler and, with `priority_for_event_type()`, orders same-time events.  
  - **`entity`**: Payload carried with the event (often the “token” flowing through the network). May be ignored by some handlers (e.g. source ignores `entity` on `Generate` when using `entity_generator`).  
  - **`kwargs`**: Extra dict for future use.

- **`priority_for_event_type(event_type) -> int`**  
  Lower value = higher priority when times are equal (default order: `Generate`, then `Arrival`, then `Departure`).

### Engine (`src/core/engine.py`)

- **`Engine(time_limit=..., startup_events=..., visualize=True, output_dir="output")`**  
  - **`time_limit`**: When not `None`, an internal `"End"` event is scheduled at that time to stop the run. Overridable by env **`MAX_SIM_TIME`**.  
  - **`startup_events`**: Queued at the start of `run()` (e.g. first `Generate` for each source).  
  - **`visualize`**: If `True`, builds a PDF of frames under `output_dir`.  
  - **`simulation_variables`**: Plain `dict[str, Any]` for model-wide counters or parameters you set in simulation setup.

- **`add_component` / `remove_component`** — Register components by `component_id`.

- **`add_event(event)`** — Push onto the priority queue.

- **`run(on_step=None)`** — Drains the queue; dispatches `component.handle_event(self, event)` for each non-End event. Optional **`on_step(sim_time, event, queue_snapshot)`** after each step (and once for initial state when visualization or callback is used).

- **`get_results()`** — Iterable of registered components (for stats).

- **`get_graph()`** — `(node_ids, edges)` using each component’s **`outputs`** list.

### Components (`src/core/components.py`)

#### Base: `Component(component_id, type, track_state=False)`

- **`outputs` / `inputs`** — Wiring lists (`SingleIOComponent` enforces a single downstream for the main chain).
- **`state`**: `dict[str, Any]` — per-block mutable state.
- **`state_history`**: When **`track_state=True`**, after **each** successful handler, a snapshot `(sim_time, dict(state))` is appended (shallow copy of `state`).
- **`set_handleable_event(event_type, handler)`** — Registers an **`EventHandler`** (see below).
- **`handle_event(engine, event)`** — Invokes the handler for `event.type`, then records state history if `track_state`.

**`EventHandler`** (defined in `src/core/components.py`):  
`Callable[[Engine, Event, Component], None]`

The third argument is **always the concrete component instance** receiving the event (e.g. `SourceComponent`), so handlers can schedule:

```python
Event(t, component.output.component_id, "Arrival", entity, {})
```

without capturing the block in a closure. Wrong wiring (e.g. calling a source-only default on a non-source) tends to fail fast with **`AttributeError`**.

#### `SingleIOComponent`

- **`output_to(other)` / `disconnect_output_to(other)`** — At most one primary output; **`output`** property returns that peer.
- **`default_handle_departure(engine, event, component)`** — Public default: schedules **`Arrival`** at **`output.component_id`** with the same **`event.entity`**.

#### `SourceComponent(component_id, entity_generator, interval=None, track_state=False)`

- **`entity_generator(engine, event, component) -> entity`** — Called on each **`Generate`**; return value becomes the entity for the internal **`Departure`** → downstream **`Arrival`**. The **`entity`** field on the `Generate` event is not used by the default source logic.
- **`interval`**: If set (`Distribution`), schedules the next **`Generate`** on self at `now + sample()`. If `None`, only startup / manually queued generates drive output.
- Flow: **`Generate`** → **`Departure`** (self) → **`Arrival`** (output). Public **`default_handle_generate`**.

#### `DelayComponent(component_id, delay_interval, capacity=1, track_state=False)`

- **`Arrival`**: Samples delay, queues **`Departure`** at `now + delay`, stores `(departure_time, entity)` in **`content`**.
- **`Departure`**: Removes matching `(time, entity)`, then **`default_handle_departure`**. Public handlers: **`handle_arrival`**, **`handle_departure_delay`**.

#### `SinkComponent(component_id, track_state=False)`

- **`Arrival`**: Appends **`(current_time, event.entity)`** to **`records`**. Public **`sink_handle_arrival`**.

#### `AssertComponent(component_id, condition, fail_handler=None, track_state=False)`

- **`condition(engine, event, component) -> bool`**. If false, **`fail_handler`** runs (default **`assert_fail_drop`**: records drop, no downstream event; **`assert_fail_error`**: raises). If true, forwards **`Arrival`** to output. Public **`assert_handle_arrival`**.

#### `TransformerComponent(component_id, transform_function, track_state=False)`

- **`transform_function(engine, event, component) -> new_entity`**. Schedules **`Departure`** with transformed entity. Public **`transformer_handle_arrival`**.

Default handlers are **public methods** so custom wrappers can delegate, e.g.  
`component.default_handle_generate(engine, event, component)` on a **`SourceComponent`** (ensure the block type matches, or you get **`AttributeError`**).

---

## Building a simulation

1. Create **`Engine`** (optional `startup_events`, `time_limit`, `visualize`, `output_dir`). Optionally fill **`engine.simulation_variables`**.
2. Instantiate components; wire with **`output_to`** (not `connect`).
3. **`engine.add_component(...)`** for each block.
4. **`engine.run()`**.
5. Inspect **`get_records_as_printable_string(engine.get_results())`** or component **`state` / `state_history`**.

Example (see `src/simulations/simple.py`):

```python
from src.core import DelayComponent, Engine, Event, SinkComponent, SourceComponent
from src.modules import get_records_as_printable_string
from src.modules.utils import UniformDistribution

engine = Engine(startup_events=[Event(0, "source", "Generate", None, {})], visualize=True)
source = SourceComponent("source", lambda _e, _evt, _comp: "token", UniformDistribution(0, 10))
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

- **`RANDOM_SEED`** — Seeded at import of `src.modules.utils` for reproducible distributions.  
- **`MAX_SIM_TIME`** — Engine time limit if set.  
- **`VERBOSE`** — `1` / `true` / `yes` / `on` → DEBUG logging.

### Logging (`src/modules/logger.py`)

- **`setup_logging(...)`** — Call once; file under `output/` by default.  
- **`get_logger(name)`** — Use `extra={"sim_time": engine.get_current_time()}` for sim time in the formatted line.

---

## Statistics (`src/modules/stats.py`)

- **`get_records_as_printable_string(components)`** — Intended for **`engine.get_results()`**.
- **`state_key_series_from_history(component, key)`** — Builds **`(time, value)`** from **`state_history`**, one point per time (last snapshot wins when times repeat).
- **`state_history_snapshots(component)`** — Returns **`list[(time, state_dict)]`** from **`state_history`**.
- **`plot_time_series(series, ...)`** — Plots a **`(x, y)`** series; optional dashed **`horizontal_lines`** as **`(y, label)`** tuples.

  1. **Sink records** — For each component with a **`records`** attribute: a titled block, table columns **`idx`**, **`arrival t`**, **`dt`** (inter-arrival), **`entity`** (compact representation; dicts via `pprint`).
  2. **Recorded component states** — For each component with non-empty **`state_history`**: timestamped shallow snapshots of **`state`** (when **`track_state`** was `True` during the run).

If a section has nothing to show, a short placeholder line is printed for that section.

---

## Visualization

With **`visualize=True`** (default), `run()` builds a **`Visualizer`**, calls **`add_frame`** for the initial queue and for each **`Generate` / `Arrival` / `Departure`** step, then **`close()`** to finalize the PDF. On Windows, if the console encoding cannot print Unicode arrows in progress text, set **`PYTHONIOENCODING=utf-8`** or disable console progress as needed.

---

## Extending

- **Custom components**: Subclass **`Component`** or **`SingleIOComponent`**, implement **`output_to` / `disconnect_output_to`**, register handlers with **`set_handleable_event`**, and schedule events with **`engine.add_event(...)`**.
- **Replace or wrap a default handler**: After construction, **`set_handleable_event("Arrival", my_handler)`**. Inside **`my_handler`**, call the original public method on the instance (e.g. **`SinkComponent.sink_handle_arrival(comp, engine, event, comp)`**) so pre/post logic composes without recursion, as long as you did not rebind that same name to your wrapper.
- **Custom distributions**: Subclass **`Distribution`** in **`src/modules/utils.py`** and implement **`sample() -> float`**.
- **Event priority**: Adjust **`priority_for_event_type`** in **`src/core/events.py`**.

---

## Running the examples

From the project root (paths as in `simple.py`):

```bash
uv run python src/simulations/simple.py
```

Additional example:

```bash
uv run python src/simulations/simple2.py
```

Two-mode stockpile / crusher example (tunable constants at top of file; returns report plus crusher; use **`state_key_series_from_history(crusher, "stockpile")`** from **`src.modules.stats`** to plot):

```bash
uv run python src/simulations/drs_crusher.py
```

These write **`output/sim.log`** and, when visualization is on, a new UUID **`output/*.pdf`** per run.
