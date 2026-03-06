# Discrete-Event Simulation — Documentation

A Python framework for discrete-event simulation (DES): events are processed in time order by components that can generate new events and connect to other components.

---

## Overview

- **Engine**: Maintains simulation time, an event queue, and a set of components. It pops events in time order and dispatches each to the component identified by `event.handler_id`.
- **Events**: Dated messages with a type and a handler. Implement `priority_for_event_type()` in `events.py` to break ties when two events have the same time.
- **Components**: React to events (e.g. Generate, Arrival, Departure), schedule new events, and optionally connect to downstream components.
- **Output**: Logs go to `output/` (and optionally console). When visualization is enabled, each run produces a UUID-named PDF in `output/` with one page per event (graph + event queue). Sink components can keep `records`; use `stats.get_records_as_printable_string(engine.get_results())` to format them.

---

## Installation

- **Python**: 3.12+
- **Dependencies**: Install with `uv sync` or `pip install -e .` (see `pyproject.toml`: `python-dotenv`, `matplotlib`, `networkx`).

---

## Project structure

```
discrete-event-simulation/
├── pyproject.toml
├── .env                    # RANDOM_SEED, MAX_SIM_TIME, VERBOSE (optional)
├── docs/
│   └── DOCUMENTATION.md    # This file
├── output/                 # Created at run time: logs, PDFs
│   ├── sim.log
│   └── <uuid>.pdf         # One per run when visualize=True
└── src/
    ├── __init__.py
    ├── engine.py           # Engine, EventQueue
    ├── events.py           # Event, priority_for_event_type
    ├── components.py       # Component, SourceComponent, DelayComponent, SinkComponent
    ├── utils.py            # Distributions (Uniform, Exponential, Constant), RNG seed
    ├── logger.py           # setup_logging, get_logger, sim-time and extras in logs
    ├── stats.py            # get_records_as_printable_string
    ├── visualization.py    # Visualizer (frame-by-frame PDF)
    └── simulations/
        └── simple.py       # Example: source → delay → sink
```

---

## Core concepts

### Events (`src/events.py`)

- **`Event(time, handler_id, type, args, kwargs)`**  
  - `time`: Simulation time at which the event is processed.  
  - `handler_id`: `component_id` of the component that will handle it.  
  - `type`: String (e.g. `"Generate"`, `"Arrival"`, `"Departure"`) used to select the handler and, with `priority_for_event_type()`, to order same-time events.

- **`priority_for_event_type(event_type) -> int`**  
  Override in `events.py` to define tie-breaking when multiple events share the same time (lower value = higher priority).

### Engine (`src/engine.py`)

- **`Engine(time_limit=..., startup_events=..., visualize=True, output_dir="output")`**  
  - `time_limit`: Simulation stops when an "End" event at this time is processed. Can be `None` (no limit).  
  - `startup_events`: Events added at the start of `run()` (e.g. first `Generate` at time 0).  
  - `visualize`: If `True`, a `Visualizer` is created each run and writes a UUID-named PDF to `output_dir`.  
  - `output_dir`: Directory for logs and PDFs (default `"output"`).

- **`add_component(component)`**  
  Registers a component by `component_id` so events with that `handler_id` are dispatched to it.

- **`add_event(event)`**  
  Pushes an event onto the queue (ordered by time, then priority, then insertion order).

- **`run(on_step=None)`**  
  Processes events until the queue is empty or an "End" event is processed. Optionally calls `on_step(time, event, queue_snapshot)` before each handled event (and once for the initial state). When `visualize=True`, the engine creates a `Visualizer` and calls `add_frame(...)` each step, then `close()`.

- **`get_results()`**  
  Returns the values of the engine’s component dict (e.g. for stats).

- **`get_graph()`**  
  Returns `(nodes, edges)` for the component graph (for visualization).

### Components (`src/components.py`)

- **`Component(component_id, type)`**  
  Base: `connect(other)`, `disconnect(other)`, `add_handleable_event(event_type, handler)`, `handle_event(engine, event)`.

- **`SingleOutputComponent`**  
  At most one `connect()`; `self.output` is the connected component. On `Departure` it sends an `Arrival` to `self.output`.

- **`SourceComponent(component_id, interval: Distribution)`**  
  Handles `Generate`: schedules the next `Generate` and an immediate `Arrival` to the single output. Interval is sampled from `interval`.

- **`DelayComponent(component_id, delay_interval: Distribution)`**  
  Handles `Arrival`: samples a delay, schedules a `Departure` at `current_time + delay`, which then sends `Arrival` to its output.

- **`SinkComponent(component_id)`**  
  Handles `Arrival`: appends the event time to `self.records`. Used for statistics.

---

## Building a simulation

1. Create an engine (optionally with `startup_events` and `time_limit`).
2. Create components and connect them (e.g. `source.connect(delay)`, `delay.connect(sink)`).
3. Register components with the engine: `engine.add_component(source)`, etc.
4. Call `engine.run()`.
5. Get results: e.g. `get_records_as_printable_string(engine.get_results())` for sink records.

Example (see `src/simulations/simple.py`):

```python
from src.engine import Engine
from src.components import SourceComponent, DelayComponent, SinkComponent
from src.stats import get_records_as_printable_string
from src.utils import UniformDistribution
from src.events import Event

engine = Engine(startup_events=[Event(0, "source", "Generate", (), {})])
source = SourceComponent("source", UniformDistribution(0, 10))
delay = DelayComponent("delay", UniformDistribution(0, 10))
sink = SinkComponent("sink")
source.connect(delay)
delay.connect(sink)
engine.add_component(source)
engine.add_component(delay)
engine.add_component(sink)
engine.run()
print(get_records_as_printable_string(engine.get_results()))
```

---

## Configuration

### Environment (`.env`)

- **`RANDOM_SEED`**  
  If set, the RNG is seeded once at import of `utils` so runs are reproducible.

- **`MAX_SIM_TIME`**  
  If set, used as the engine’s time limit (simulation stops at an "End" event at this time). Can be overridden by passing `time_limit` to `Engine(...)`.

- **`VERBOSE`**  
  If set to `1`, `true`, `yes`, or `on`, logging level is set to DEBUG (see logger).

### Logging (`src/logger.py`)

- **`setup_logging(level=..., log_file="sim.log", output_dir="output", console=False, ...)`**  
  Call once at startup. Logs go to `output/<log_file>` by default; set `console=True` to also print to the terminal.

- **`get_logger(name)`**  
  Returns a logger (e.g. per component). Use `log.info("...", extra={"sim_time": engine.get_current_time()})` to include simulation time and other extras in the formatted line.

---

## Statistics

- **`get_records_as_printable_string(components)`**  
  Iterates over `components` (e.g. `engine.get_results()`). Any object with a `records` attribute is treated as a sink: prints `component_id: [list of records]`. Returns `"(no sink records)\n"` if none found.

---

## Visualization

When `Engine(..., visualize=True)` (default), each `run()`:

1. Creates a **`Visualizer`** (from `src/visualization.py`) with the current component graph and `output_dir`.
2. Calls **`add_frame(time_val, event, queue_snapshot)`** for the initial state and after each event is processed.
3. Calls **`close()`** at the end; the PDF path is logged.

The PDF filename is **UUID-based** (e.g. `output/a1b2c3d4-....pdf`) so runs do not overwrite each other. Each page shows:

- Component graph (fixed layout), current simulation time in the title, and the component handling the event highlighted in green.
- Event queue for that step (formatted list).

Progress is printed to the terminal: one line per frame (timestamp, frame index, sim time, event) and a final line with the path and frame count.

---

## Extending

- **Custom components**: Subclass `Component` or `SingleOutputComponent`, implement `add_handleable_event` for your event types, and in handlers call `engine.add_event(...)` as needed.
- **Custom distributions**: Subclass `Distribution` in `utils.py` and implement `sample() -> float`.
- **Event priority**: Implement `priority_for_event_type(event_type)` in `events.py` to return an integer (lower = higher priority) for tie-breaking.

---

## Running the example

From the project root, with `src` and project root on `PYTHONPATH` (e.g. as in `simple.py`):

```bash
uv run python src/simulations/simple.py
```

Or run as a module:

```bash
uv run python -m src.simulations.simple
```

This runs the simple source → delay → sink simulation, writes logs to `output/sim.log`, and writes a new UUID-named PDF to `output/` for the frame-by-frame visualization.
