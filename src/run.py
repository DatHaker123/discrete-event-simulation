from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from src.core import Engine
from src.modules import RunOptions, setup_logging


def _resolve_simulation_path(file_arg: str) -> Path | None:
    raw = Path(file_arg)
    simulations_dir = Path(__file__).resolve().parent / "simulations"

    if raw.is_absolute() or raw.exists() or any(sep in file_arg for sep in ("/", "\\")) or raw.suffix == ".py":
        if raw.exists():
            return raw.resolve()
        if raw.is_absolute():
            return None
        if raw.suffix == ".py":
            fallback = simulations_dir / raw.name
            return fallback.resolve() if fallback.exists() else None
        return None

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
        raise ValueError(f"Multiple simulation callables found in {module.__name__}; use --function to choose one.")
    raise ValueError(
        f"No simulation callable found in {module.__name__}. Expected one of: {preferred_names} or '*_simulation'."
    )


def _resolve_post_run_hook(module: ModuleType) -> Callable[..., Any] | None:
    for name in ("post_run", "simulation_post_run"):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    return None


def _invoke_simulation(sim_fn: Callable[..., Any], visualize: bool) -> Any:
    signature = inspect.signature(sim_fn)
    if "visualize" in signature.parameters:
        return sim_fn(visualize=visualize)
    return sim_fn()


def _invoke_post_run_hook(
    hook_fn: Callable[..., Any],
    *,
    engine: Engine,
    module: ModuleType,
    options: RunOptions,
) -> None:
    signature = inspect.signature(hook_fn)
    kwargs: dict[str, Any] = {}
    for param_name in signature.parameters:
        if param_name in ("engine", "sim", "simulation", "result"):
            kwargs[param_name] = engine
        elif param_name in ("module", "sim_module"):
            kwargs[param_name] = module
        elif param_name in ("options", "run_options"):
            kwargs[param_name] = options
    hook_fn(**kwargs)


def _run_module(
    module: ModuleType,
    visualize: bool,
    function_name: str | None,
    options: RunOptions,
) -> int:
    sim_fn = _resolve_simulation_callable(module, function_name)
    result = _invoke_simulation(sim_fn, visualize)

    if isinstance(result, Engine):
        hook_fn = _resolve_post_run_hook(module)
        if hook_fn is not None:
            _invoke_post_run_hook(hook_fn, engine=result, module=module, options=options)
        else:
            print("Simulation completed (no simulation-defined post_run hook).")
        return 0

    print(result)
    return 0


def _build_parser(require_file: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run simulation modules through a central CLI.")
    parser.add_argument(
        "--file",
        required=require_file,
        help="Simulation file under src/simulations by default, or a full path / dotted module path.",
    )
    parser.add_argument("--function", help="Optional simulation function name to call inside the module.")
    parser.add_argument("--viz", action="store_true", help="Enable PDF visualization.")
    parser.add_argument("--plot", action="store_true", help="Enable plotting in simulation-defined post_run hook.")
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
    options = RunOptions(
        plot=bool(args.plot),
    )

    return _run_module(
        module,
        visualize=args.viz,
        function_name=args.function,
        options=options,
    )


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
