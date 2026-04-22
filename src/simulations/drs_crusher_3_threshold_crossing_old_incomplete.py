## DRS-style stockpile: uniform hopper rate (one announcement) -> crusher (mode rules via operation_mode) -> sink
#
# Source is a ``SourceComponent`` with ``interval=None``: only external ``Generate`` events drive it.
# The engine queues one ``Generate`` at t=0 whose ``entity`` carries the hopper rate; no further
# Generates are scheduled. The crusher stores
# the hopper discharge rate in ``state["source_rate_tonnes_per_unit_time"]`` and advances feed/crush
# on self-scheduled ``HopperTick`` events. Based on drs_crusher_2; deterministic.

# Due to structural changes in the operation_mode module, this simulation is no longer valid.
# It is kept here for reference.

import sys
import uuid
from pathlib import Path
from typing import Any, Callable

_root = Path(__file__).resolve().parent.parent.parent
_src = _root / "src"
for p in (_src, _root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import logging

from src.core import (
    Component,
    Engine,
    Entity,
    Event,
    SinkComponent,
    SourceComponent,
    TransformerComponent,
)
from src.modules import (
    get_records_as_printable_string,
    plot_time_series,
    setup_logging,
    state_key_series_from_history,
)
from src.modules.operation_mode import OperationModeConstraint, OperationModeResolver, OperationModeRule, OperationMode
from src.modules.utils import ConstantDistribution


# --- Tuning: uniform hopper (constant discharge rate per unit time) ---
# One rate announcement at startup; crusher applies rate * tick interval each HopperTick.
HOPPER_TICK_INTERVAL = 1.0
SOURCE_RATE_TONNES_PER_UNIT_TIME = 2.8

# --- Tuning: crusher throughput (tonnes per processing step, mode-dependent) ---
SLOW_CRUSH = ConstantDistribution(1.25)  # midpoint of former Uniform(0.9, 1.6)
FAST_CRUSH = ConstantDistribution(5.35)  # midpoint of former Uniform(4.2, 6.5)


# Modes embed tuning in ``data``; rules return these objects—handlers index keys they define.
MODE_SLOW = OperationMode("slow", {"crush_speed": SLOW_CRUSH})
MODE_FAST = OperationMode("fast", {"crush_speed": FAST_CRUSH})

# --- Tuning: stockpile hysteresis (mode switches when projected level crosses these) ---
HIGH_STOCK = 20.0
LOW_STOCK = 9.0

# --- Simulation horizon ---
TIME_LIMIT = 220.0

# --- Processing model: multiplicative factor on stock before comparing to capacity ---
SWELL_FACTOR = 1.1

# --- Initial component.state seeds (handlers only mutate dynamics after this) ---
INITIAL_SOURCE_STATE: dict[str, Any] = {
    "generate_handled": False,
}

INITIAL_CRUSHER_STATE: dict[str, Any] = {
    "stockpile": 0.0,
    "mode_name": MODE_SLOW.name,
    "total_raw_in": 0.0,
    "total_crushed_out": 0.0,
    # Filled once from the hopper rate message; mutable if the model later supports rate changes.
    "source_rate_tonnes_per_unit_time": 0.0,
}

# class ThresholdBasedCrusher(TransformerComponent):
#     """
#     Receives the initial ``Arrival`` with ``source_rate_tonnes_per_unit_time``, then runs the
#     stockpile/crush step on each ``HopperTick`` (feed = rate * tick interval).
#     """

#     def __init__(
#         self,
#         component_id: str,
#         arrival_rate_tonnes_per_unit_time: float,
#         crush_transform: Callable[[Engine, Event, Component], Entity],
#         *,
#         track_state: bool = False,
#     ):
#         super().__init__(component_id, crush_transform, track_state=track_state)
#         self.set_handleable_event("Arrival", self.initial_rate_arrival_handler)
#         self.set_handleable_event("Departure", self.default_handle_departure)

#     def rate_arrival_handler(self, _engine: Engine, _event: Event, _component: Component) -> None:
#         self.state["arrival_rate_tonnes_per_unit_time"] = arrival_rate_tonnes_per_unit_time

#     def initial_rate_arrival_handler(self, _engine: Engine, event: Event, component: Component) -> None:
#         ent = event.entity
#         if "arrival_rate_tonnes_per_unit_time" not in ent:
#             raise ValueError(
#                 f"Crusher expected initial arrival rate announcement, got entity keys: {list(ent.keys())}"
#             )
#         component.state["arrival_rate_tonnes_per_unit_time"] = float(ent["arrival_rate_tonnes_per_unit_time"])



def drs_crusher_simulation(visualize: bool = False) -> tuple[]:
    """
    Wire source → crusher → sink, run the engine, return a text report and the crusher
    (for plotting ``state_history``). Sections below mirror the setup order.
    """
    # --- Engine ---
    # One external Generate only; SourceComponent with interval=None does not self-schedule more.
    hopper_rate_entity: Entity = {"source_rate_tonnes_per_unit_time": SOURCE_RATE_TONNES_PER_UNIT_TIME}

    engine = Engine(
        visualize=visualize,
        time_limit=TIME_LIMIT,
    )
    engine.add_startup_event(Event(0, "source", "Generate", {}, {}))

    # --- Source (driven only by startup_events Generate; interval=None) ---
    hopper_source = SourceComponent(
        "hopper_source",
        lambda _e, _ev, _c: hopper_rate_entity,
        interval=None,
        track_state=True,
    )
    hopper_source.state.update(INITIAL_SOURCE_STATE)

    initial_rate_entity: Entity = {"arrival_rate_tonnes_per_unit_time": SOURCE_RATE_TONNES_PER_UNIT_TIME}
    def rate_update_handler(engine: Engine, _event: Event, component: Component) -> None:
        current_time = engine.get_current_time()
        arrival_event = Event(current_time, component.component_id, "ArrivalRateUpdate", initial_rate_entity, {}) 
        engine.add_event(arrival_event)

    hopper_source.set_handleable_event("Departure", rate_update_handler)


    # --- Mode rules (operation_mode) ---
    mode_resolver: OperationModeResolver[OperationMode] = OperationModeResolver()

    stockpile_low = OperationModeConstraint(
        name="stockpile_at_or_below_low",
        check=lambda _eng, ev, comp: float(comp.state["stockpile"])
        + float(ev.entity.get("raw_tonnes", 0.0))
        <= LOW_STOCK,
    )
    stockpile_high = OperationModeConstraint(
        name="stockpile_at_or_above_high",
        check=lambda _eng, ev, comp: float(comp.state["stockpile"])
        + float(ev.entity.get("raw_tonnes", 0.0))
        >= HIGH_STOCK,
    )

    slow_mode_rule = OperationModeRule(
        name="switch_to_slow_at_low_stock",
        mode=MODE_SLOW,
        priority=10,
        constraints=[stockpile_low],
    )
    fast_mode_rule = OperationModeRule(
        name="switch_to_fast_at_high_stock",
        mode=MODE_FAST,
        priority=20,
        constraints=[stockpile_high],
    )

    mode_resolver.add_rule(slow_mode_rule)
    mode_resolver.add_rule(fast_mode_rule)

    # --- Crusher: each hopper step feeds raw_in = source_rate * tick_interval ---
    def crush_transform(_engine: Engine, event: Event, comp: Component) -> Entity:
        st = comp.state
        raw_in = float(event.entity.get("raw_tonnes", 0.0))
        stock_before = float(st["stockpile"])

        stock_after_feed = stock_before + raw_in

        current_name = str(st["mode_name"])
        default_mode = MODE_FAST if current_name == MODE_FAST.name else MODE_SLOW
        selected_mode = mode_resolver.resolve(_engine, event, comp, default=default_mode)
        if selected_mode is None:
            selected_mode = default_mode
        st["mode_name"] = selected_mode.name

        capacity = selected_mode.data["crush_speed"].sample()
        crushed = min(stock_after_feed * SWELL_FACTOR, capacity)

        stock_after = stock_after_feed - crushed
        st["stockpile"] = stock_after

        st["total_raw_in"] = float(st["total_raw_in"]) + raw_in
        st["total_crushed_out"] = float(st["total_crushed_out"]) + crushed

        entity: Entity = {
            "crushed_tonnes": crushed,
            "stockpile_after": stock_after,
            "mode": selected_mode.name,
            "raw_in": raw_in,
        }
        return entity

    crusher = TransformerComponent(
        "crusher",
        crush_transform,
        track_state=True,
    )
    crusher.state.update(INITIAL_CRUSHER_STATE)

    def handle_rate_update(_engine: Engine, event: Event, component: Component) -> None:
        st = component.state
        st["source_rate_tonnes_per_unit_time"] = float(event.entity.get("arrival_rate_tonnes_per_unit_time", 0.0))

        current_time = _engine.get_current_time()
        variable = st["stockpile"]
        rate_of_change = st["source_rate_tonnes_per_unit_time"]

        mode_resolver_internal = mode_resolver

        remaining_capacity = st["source_rate_tonnes_per_unit_time"] - st["stockpile"]
        if remaining_capacity > 0:
            next_change_time = engine.get_current_time() + remaining_capacity / st["source_rate_tonnes_per_unit_time"]
            engine.add_event(Event(next_change_time, component.component_id, "RateUpdate", {
                "arrival_rate_tonnes_per_unit_time": st["source_rate_tonnes_per_unit_time"]
            }, {}))

    crusher.set_handleable_event("ArrivalRateUpdate", handle_rate_update)

    # --- Sink ---
    sink = SinkComponent("sink", track_state=False)

    # --- Topology and registration ---
    hopper_source.output_to(crusher)
    crusher.output_to(sink)

    for c in (hopper_source, crusher, sink):
        engine.add_component(c)

    # --- Run ---
    engine.run()
    return get_records_as_printable_string(engine.get_results()), crusher


# --- CLI: run simulation, print report and stockpile samples; optional --plot ---
if __name__ == "__main__":
    setup_logging(level=logging.INFO, log_file="sim.log", output_dir="output")
    report, crusher = drs_crusher_simulation(visualize=False)
    print(report)
    series = state_key_series_from_history(crusher, "stockpile")
    print("\n# stockpile vs time (t, stockpile) - sample for plotting")
    for t, s in series[:25]:
        print(f"{t:.4f}\t{s:.4f}")
    if len(series) > 25:
        print("...")
    for t, s in series[-12:]:
        print(f"{t:.4f}\t{s:.4f}")

    if "--plot" in sys.argv:
        out = _root / "output" / f"drs_crusher_stockpile_with_utils_{uuid.uuid4()}.png"
        plot_time_series(
            series,
            x_label="time",
            y_label="stockpile (tonnes)",
            title="Crusher stockpile vs time",
            line_label="stockpile",
            horizontal_lines=((HIGH_STOCK, "high"), (LOW_STOCK, "low")),
            save_path=out,
            show=True,
        )
        print(f"\nSaved figure to {out}")
