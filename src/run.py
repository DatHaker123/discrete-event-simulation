from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import logging
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from src.core import Engine
from src.modules import (
    get_records_as_printable_string,
    plot_time_series,
    setup_logging,
    state_history_snapshots,
    state_key_series_from_history,
)


def _resolve_simulation_path(file_arg: str) -> Path | None:
    raw = Path(file_arg)
    simulations_dir = Path(__file__).resolve().parent / "simulations"

    # Absolute or explicit relative paths keep their original meaning.
    if raw.is_absolute() or raw.exists() or any(sep in file_arg for sep in ("/", "\\")) or raw.suffix == ".py":
        if raw.exists():
            return raw.resolve()
        if raw.is_absolute():
            return None
        if raw.suffix == ".py":
            fallback = simulations_dir / raw.name
            return fallback.resolve() if fallback.exists() else None
        return None

    # Bare names are assumed to live under src/simulations.
    direct = simulations_dir / raw
    if direct.exists():
        return direct.resolve()

    with_suffix = simulations_dir / f"{file_arg}.py"
    if with_suffix.exists():
        return with_suffix.resolve()

    return None


def _resolve_module(file_arg: str) -> ModuleType:
    module_path = _resolve_simulation_path(file_arg)
    if module_path is not None:
        module_name = f"simulation_entry_{module_path.stem}_{abs(hash(str(module_path)))}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module from file: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(file_arg)


def _resolve_simulation_callable(module: ModuleType, function_name: str | None) -> Callable[..., Any]:
    if function_name:
        fn = getattr(module, function_name, None)
        if fn is None or not callable(fn):
            raise ValueError(f"Function '{function_name}' was not found or is not callable in {module.__name__}.")
        return fn

    preferred_names = (
        "drs_crusher_simulation",
        "simple_simulation",
        "run_simulation",
        "simulation",
    )
    for name in preferred_names:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn

    discovered = [
        getattr(module, name)
        for name in dir(module)
        if name.endswith("_simulation") and callable(getattr(module, name))
    ]
    if len(discovered) == 1:
        return discovered[0]
    if len(discovered) > 1:
        raise ValueError(
            f"Multiple simulation callables found in {module.__name__}; use --function to choose one."
        )
    raise ValueError(
        f"No simulation callable found in {module.__name__}. Expected one of: {preferred_names} or '*_simulation'."
    )


def _invoke_simulation(sim_fn: Callable[..., Any], visualize: bool) -> Any:
    signature = inspect.signature(sim_fn)
    if "visualize" in signature.parameters:
        return sim_fn(visualize=visualize)
    return sim_fn()


def _print_stockpile_sample(series: list[tuple[float, float]]) -> None:
    print("\n# stockpile vs time (t, stockpile) - sample for plotting")
    for t, s in series[:25]:
        print(f"{t:.4f}\t{s:.4f}")
    if len(series) > 25:
        print("...")
    for t, s in series[-12:]:
        print(f"{t:.4f}\t{s:.4f}")


def _extract_mode_change_times(component: Any, mode_key: str) -> list[float]:
    rows = state_history_snapshots(component)
    if not rows:
        return []
    last_mode: Any = None
    initialized = False
    change_times: list[float] = []
    for t, snap in rows:
        if not isinstance(snap, dict) or mode_key not in snap:
            continue
        current_mode = snap[mode_key]
        if not initialized:
            last_mode = current_mode
            initialized = True
            continue
        if current_mode != last_mode:
            change_times.append(float(t))
            last_mode = current_mode
    return change_times


def _extract_mode_transitions(component: Any, mode_key: str) -> list[tuple[float, Any, Any]]:
    rows = state_history_snapshots(component)
    if not rows:
        return []
    last_mode: Any = None
    initialized = False
    transitions: list[tuple[float, Any, Any]] = []
    for t, snap in rows:
        if not isinstance(snap, dict) or mode_key not in snap:
            continue
        current_mode = snap[mode_key]
        if not initialized:
            last_mode = current_mode
            initialized = True
            continue
        if current_mode != last_mode:
            transitions.append((float(t), last_mode, current_mode))
            last_mode = current_mode
    return transitions


def _resolve_stockpile_bounds(module: ModuleType, target_component_id: str) -> tuple[float, float] | None:
    # 1) explicit generic override for plotting target
    high = getattr(module, "STOCKPILE_HIGH", None)
    low = getattr(module, "STOCKPILE_LOW", None)
    if isinstance(high, (int, float)) and isinstance(low, (int, float)):
        return float(high), float(low)

    # 2) legacy generic names (single-stockpile simulations)
    high = getattr(module, "HIGH_STOCK", None)
    low = getattr(module, "LOW_STOCK", None)
    if isinstance(high, (int, float)) and isinstance(low, (int, float)):
        return float(high), float(low)

    # 3) per-component names, e.g. GRINDER_HIGH_STOCK / GRINDER_LOW_STOCK
    prefix = target_component_id.upper()
    high = getattr(module, f"{prefix}_HIGH_STOCK", None)
    low = getattr(module, f"{prefix}_LOW_STOCK", None)
    if isinstance(high, (int, float)) and isinstance(low, (int, float)):
        return float(high), float(low)

    return None


def _maybe_process_stockpile(
    engine: Engine,
    module: ModuleType,
    plot: bool,
    output_dir: Path,
    plot_target: str | None = None,
) -> None:
    components = list(engine.get_results())
    target_component_id = str(plot_target or getattr(module, "STOCKPILE_COMPONENT_ID", "crusher"))
    target_component = next((c for c in components if c.component_id == target_component_id), None)
    if target_component is None:
        return
    if not getattr(target_component, "track_state", False):
        return
    series_key = str(getattr(module, "STOCKPILE_STATE_KEY", "stockpile"))
    series = state_key_series_from_history(target_component, series_key)
    if not series:
        return

    print(f"\n# stockpile component: {target_component_id}")
    _print_stockpile_sample(series)

    if not plot:
        return

    horizontal_lines: tuple[tuple[float, str], ...] | None = None
    bounds = _resolve_stockpile_bounds(module, target_component_id)
    if bounds is not None:
        high_stock, low_stock = bounds
        horizontal_lines = ((high_stock, "high"), (low_stock, "low"))

    mode_change_component_id = str(getattr(module, "MODE_CHANGE_COMPONENT_ID", target_component_id))
    mode_change_state_key = str(getattr(module, "MODE_CHANGE_STATE_KEY", "mode"))
    mode_component = next(
        (c for c in components if c.component_id == mode_change_component_id),
        None,
    )
    vertical_lines: list[float] | None = None
    if mode_component is not None and getattr(mode_component, "track_state", False):
        vertical_lines = _extract_mode_change_times(mode_component, mode_change_state_key)

    mode_transition_bars_cfg = None
    bars_by_target = getattr(module, "MODE_TRANSITION_BARS_BY_TARGET", None)
    if isinstance(bars_by_target, dict):
        mode_transition_bars_cfg = bars_by_target.get(target_component_id)
    if mode_transition_bars_cfg is None:
        mode_transition_bars_cfg = getattr(module, "MODE_TRANSITION_BARS", None)
    default_y_min = float(getattr(module, "MODE_TRANSITION_Y_MIN", min(v for _, v in series)))
    default_y_max = float(getattr(module, "MODE_TRANSITION_Y_MAX", max(v for _, v in series)))
    vertical_bars: list[tuple[float, float, float, str, str | None]] | None = None
    if isinstance(mode_transition_bars_cfg, (list, tuple)):
        bars: list[tuple[float, float, float, str, str | None]] = []
        for cfg in mode_transition_bars_cfg:
            if not isinstance(cfg, dict):
                continue
            cid = str(cfg.get("component_id", target_component_id))
            comp = next((c for c in components if c.component_id == cid), None)
            if comp is None or not getattr(comp, "track_state", False):
                continue
            mode_key = str(cfg.get("mode_key", "mode"))
            from_mode = cfg.get("from_mode")
            to_mode = cfg.get("to_mode")
            color = str(cfg.get("color", "red"))
            label = cfg.get("label")
            y_min = float(cfg.get("y_min", default_y_min))
            y_max = float(cfg.get("y_max", default_y_max))
            for t, prev_mode, curr_mode in _extract_mode_transitions(comp, mode_key):
                if from_mode is not None and prev_mode != from_mode:
                    continue
                if to_mode is not None and curr_mode != to_mode:
                    continue
                bars.append((t, y_min, y_max, color, str(label) if label is not None else None))
        vertical_bars = bars if bars else None
        if vertical_bars is not None:
            # If explicit transition bars are provided, prefer them over generic red markers.
            vertical_lines = None

    output_path = output_dir / f"{Path(getattr(module, '__file__', module.__name__)).stem}_stockpile_{uuid.uuid4()}.png"
    plot_time_series(
        series,
        x_label="time",
        y_label=f"{series_key} (tonnes)",
        title=f"{target_component_id} {series_key} vs time",
        line_label=series_key,
        horizontal_lines=horizontal_lines,
        vertical_lines=vertical_lines,
        vertical_bars=vertical_bars,
        save_path=output_path,
        show=True,
    )
    print(f"\nSaved figure to {output_path}")


def _run_module(
    module: ModuleType,
    visualize: bool,
    plot: bool,
    function_name: str | None,
    plot_target: str | None = None,
) -> int:
    sim_fn = _resolve_simulation_callable(module, function_name)
    result = _invoke_simulation(sim_fn, visualize)

    if isinstance(result, Engine):
        components = result.get_results()
        print(get_records_as_printable_string(components))
        output_dir = Path(getattr(result, "output_dir", "output"))
        _maybe_process_stockpile(
            result,
            module,
            plot=plot,
            output_dir=output_dir,
            plot_target=plot_target,
        )
        return 0

    print(result)
    return 0


def _build_parser(require_file: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run simulation modules through a central CLI.")
    parser.add_argument(
        "--file",
        required=require_file,
        help="Simulation file under src/simulations by default (e.g. drs_crusher_4_threshold_crossing_intended_design.py), or a full path / dotted module path.",
    )
    parser.add_argument("--function", help="Optional simulation function name to call inside the module.")
    parser.add_argument("--viz", action="store_true", help="Enable PDF visualization.")
    parser.add_argument(
        "--plot",
        nargs="?",
        const="auto",
        choices=("auto", "crusher", "grinder"),
        default=None,
        help="Enable stockpile plotting; optional target component (crusher|grinder).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Logging level for setup_logging().",
    )
    parser.add_argument("--log-file", default="sim.log", help="Log file name under output directory.")
    parser.add_argument("--console", action="store_true", help="Also write logs to the console.")
    return parser


def run_cli(argv: list[str] | None = None, default_file: str | None = None) -> int:
    parser = _build_parser(require_file=default_file is None)
    args = parser.parse_args(argv)

    file_arg = args.file or default_file
    if file_arg is None:
        parser.error("--file is required unless default_file is provided.")

    setup_logging(
        level=getattr(logging, args.log_level),
        log_file=args.log_file,
        output_dir="output",
        console=args.console,
    )

    module = _resolve_module(file_arg)
    plot_enabled = args.plot is not None
    plot_target = None if args.plot in (None, "auto") else str(args.plot)

    return _run_module(
        module,
        visualize=args.viz,
        plot=plot_enabled,
        function_name=args.function,
        plot_target=plot_target,
    )


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
