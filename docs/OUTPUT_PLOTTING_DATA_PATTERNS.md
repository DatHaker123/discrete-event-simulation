# Output, Plotting, and Data Patterns

This guide explains how to get high-quality simulation output by designing state recording intentionally, then plotting from that state.

The most important idea: **good plots come from good state snapshots**.

---

## Output Surfaces in This Codebase

There are three primary output surfaces:

1. **Sink records** (`SinkComponent.records`)
   - Event-level entities at terminal points.
2. **State history** (`component.state_history`)
   - Time series snapshots from tracked components.
3. **Visualization frames** (`--viz`)
   - Event-queue and topology evolution over time.

For trend analysis, prefer **state_history** over sink-only records.

---

## State Recording Model

When `track_state=True`:
- the framework stores an initial snapshot at `t=-1`,
- each handled event records another snapshot,
- each snapshot is a shallow copy of `component.state`.

This implies:
- `component.state` should hold exactly what you want analyzed later,
- complex live internals should be transformed into snapshot-safe fields.

---

## Recommended Pattern: `set_state_updater`

Use `set_state_updater` to derive plot-ready fields right before snapshot.

Example:

```python
from copy import deepcopy

def queue_state_updater(ctx):
    c = ctx.component
    c.state["size"] = len(c.buffer)
    c.state["ready_credits"] = c.ready_credits
    c.state["entities"] = deepcopy(c.buffer)

queue.set_state_updater(queue_state_updater)
```

Why this pattern works:
- keeps handlers focused on behavior,
- keeps output logic centralized,
- makes plotting/stat extraction straightforward.

---

## Designing Plot-Ready State

For each tracked component, define:

1. **Primary metric** (what you will plot)
   - examples: `stockpile`, `size`, `processed_tonnes_step`
2. **Control context** (why metric changed)
   - examples: `mode`, `ready_credits`, threshold flags
3. **Audit fields** (debug)
   - examples: `last_event_type`, `scheduled_departures`

Suggested conventions:
- numeric fields for y-series (`float`/`int`),
- stable key names across simulations,
- keep per-snapshot payload size reasonable.

---

## SimulationPlot Usage Pattern

`SimulationPlot` expects:
- `state_history`,
- a numeric `y_key`.

Basic usage:

```python
from src.modules.sim_output import SimulationPlot

plotter = SimulationPlot(
    state_history=target_component.state_history,
    y_key="stockpile",
    name="crusher stockpile vs time",
)
plotter.add_horizontal_line(20.0, label="high", color="C3")
plotter.add_horizontal_line(9.0, label="low", color="C2")
plotter.plot_mode_changes()
plotter.render(output_name_prefix="crusher_stockpile", show=True)
```

---

## Choosing Between `--viz` and `--plot`

Use `--viz` when:
- debugging event order,
- validating queue/resource handshakes,
- checking topology connectivity and propagation.

Use `--plot` when:
- analyzing trends and control behavior,
- comparing regimes across time,
- tuning thresholds/capacities/rates.

Use both when:
- a trend looks wrong and you need event-level root cause.

---

## Patterns by Simulation Type

### DES flow models

Track:
- queue sizes,
- delay occupancy,
- release/acquire counters.

Inspect:
- sink records for correctness,
- state history for bottlenecks.

### DRS tickwise

Track:
- `stockpile`,
- `mode`,
- `processed_tonnes_step`,
- totals in/out.

Inspect:
- oscillation shape,
- mode switching cadence,
- stage coupling effects.

### DRS threshold-crossing

Track:
- inventory level and last update time,
- in/out rates,
- active mode.

Inspect:
- predicted crossing behavior,
- sparse event scheduling correctness,
- stability around threshold boundaries.

---

## Anti-Patterns to Avoid

1. **Only recording sink outputs for dynamic-control models**
   - loses internal causality.
2. **Putting framework internals directly into `state` in many handlers**
   - leads to drift and inconsistency.
3. **Mixing analysis math directly into every handler**
   - makes behavior and output concerns hard to separate.
4. **Tracking huge mutable objects without copying**
   - can make snapshots misleading if references mutate later.

---

## Practical Template

Use this template whenever adding a new simulation:

1. Pick 1-2 target metrics to plot.
2. Define an initial `state` schema with those keys.
3. Add `set_state_updater` for derived snapshot fields.
4. Add optional `post_run(engine, options)` with `SimulationPlot`.
5. Verify with:
   - run without flags (sanity),
   - run with `--viz` (event debug),
   - run with `--plot` (trend quality).

