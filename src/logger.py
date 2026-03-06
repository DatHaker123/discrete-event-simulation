"""
Logging module for the discrete-event simulation.

To include simulation time in a log line, pass it explicitly via extra:

    log.info("Arrival", extra={"sim_time": engine.get_current_time()})

The formatter will render it as [t=12.5] in the output. No context or engine wiring.

How to use:
    # At startup (so logs also go to output/sim.log). Set VERBOSE=1 in env for DEBUG.
    from src.logger import setup_logging
    setup_logging(log_file="sim.log", output_dir="output")

    # When logging (with sim time):
    from src.logger import get_logger
    log = get_logger("my_component_id")
    log.info("Arrival", extra={"sim_time": engine.get_current_time()})
"""

import logging
import os
import sys
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None: ...

# Standard LogRecord attribute names (so we don't treat them as "extra")
_LOG_RECORD_ATTRS = frozenset(
    {
        "name", "msg", "args", "created", "filename", "funcName", "levelname",
        "levelno", "lineno", "module", "msecs", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "exc_info", "exc_text",
        "thread", "threadName", "message", "taskName",
    }
)


class SimTimeFormatter(logging.Formatter):
    """
    Formatter that reads sim_time and other extra fields from the log record.
    %(sim_time)s -> e.g. "[t=10.25] "; %(extras)s -> e.g. " event_type=Generate delay=0.5".
    """

    def format(self, record: logging.LogRecord) -> str:
        t = getattr(record, "sim_time", None)
        if t is not None and isinstance(t, (int, float)):
            record.sim_time = f"[t={t:.4f}] "
        else:
            record.sim_time = ""

        # Build extras string from any extra={...} keys (excluding sim_time)
        extras_parts = []
        for k, v in record.__dict__.items():
            if k not in _LOG_RECORD_ATTRS and k != "sim_time":
                extras_parts.append(f" {k}={v}")
        record.extras = "".join(extras_parts) if extras_parts else ""
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the given name (e.g. module or component id).
    Uses the root 'simulation' logger so levels and handlers are shared.
    """
    return logging.getLogger(f"simulation.{name}")


def _level_from_env() -> int | None:
    """If VERBOSE is set (1, true, yes), return DEBUG; else None (use caller default)."""
    load_dotenv()
    v = os.getenv("VERBOSE", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return logging.DEBUG
    return None


def setup_logging(
    level: int | None = None,
    log_file: Optional[str] = "sim.log",
    output_dir: str = "output",
    console: bool = False,
    include_sim_time: bool = True,
    fmt: Optional[str] = None,
) -> None:
    """
    Configure logging for the simulation. Call once at startup.

    Log level is VERBOSE-aware: if env VERBOSE=1 (or true/yes/on), level becomes DEBUG.
    Otherwise the given level is used (default INFO).

    Args:
        level: Logging level (e.g. logging.DEBUG, logging.INFO). Default INFO unless VERBOSE is set.
        log_file: If set, write logs to this file under output_dir (default: output/sim.log).
        output_dir: Folder for log files; created if it does not exist. Ignored if log_file is None.
        console: If True, also log to the terminal. Default False (file only).
        include_sim_time: If True, use a formatter that shows [t=...] when sim time is set.
        fmt: Custom format string. If None, a default is used.
    """
    load_dotenv()
    if level is None:
        level = _level_from_env() or logging.INFO
    else:
        env_level = _level_from_env()
        if env_level is not None:
            level = env_level
    root = logging.getLogger("simulation")
    root.setLevel(level)

    if fmt is None:
        if include_sim_time:
            fmt = "%(asctime)s %(sim_time)s%(levelname)s %(name)s:%(extras)s %(message)s"
        else:
            fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if include_sim_time:
        formatter = SimTimeFormatter(fmt, datefmt="%H:%M:%S")
    else:
        formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")

    # SimTimeFormatter sets record.sim_time in format(); no record_factory so
    # extra={"sim_time": t} doesn't conflict with an existing record attribute.

    # Console handler (only if requested)
    if console and not root.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    # File handler: write to output_dir/log_file
    if log_file:
        os.makedirs(output_dir, exist_ok=True)
        log_path = os.path.join(output_dir, log_file)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def log_event(
    logger: logging.Logger,
    event_type: str,
    component_id: str,
    sim_time: Optional[float] = None,
    **kwargs,
) -> None:
    """
    Log an event with optional sim_time (shown as [t=...] in output).
    Example: log_event(log, "Arrival", "sink_1", sim_time=engine.get_current_time())
    """
    extra = {"sim_time": sim_time} if sim_time is not None else {}
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
    msg = f"{event_type} @ {component_id}" + (f" {extra_info}" if extra_info else "")
    logger.info(msg, extra=extra)
