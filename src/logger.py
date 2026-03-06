"""
Logging module for the discrete-event simulation.

To include simulation time in a log line, pass it explicitly via extra:

    log.info("Arrival", extra={"sim_time": engine.get_current_time()})

The formatter will render it as [t=12.5] in the output. No context or engine wiring.

How to use:
    # At startup (so logs also go to output/sim.log):
    from src.logger import setup_logging
    setup_logging(level=logging.INFO, log_file="sim.log", output_dir="output")

    # When logging (with sim time):
    from src.logger import get_logger
    log = get_logger("my_component_id")
    log.info("Arrival", extra={"sim_time": engine.get_current_time()})
"""

import logging
import os
import sys
from typing import Optional

class SimTimeFormatter(logging.Formatter):
    """
    Formatter that reads sim_time from the log record (set via extra={"sim_time": t}).
    Use %(sim_time)s in your format string; it becomes e.g. "[t=10.25] " or "".
    """

    def format(self, record: logging.LogRecord) -> str:
        t = getattr(record, "sim_time", None)
        if t is not None and isinstance(t, (int, float)):
            record.sim_time = f"[t={t:.4f}] "
        else:
            record.sim_time = ""
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the given name (e.g. module or component id).
    Uses the root 'simulation' logger so levels and handlers are shared.
    """
    return logging.getLogger(f"simulation.{name}")


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = "sim.log",
    output_dir: str = "output",
    include_sim_time: bool = True,
    fmt: Optional[str] = None,
) -> None:
    """
    Configure logging for the simulation. Call once at startup.

    Args:
        level: Logging level (e.g. logging.DEBUG, logging.INFO).
        log_file: If set, write logs to this file under output_dir (default: output/sim.log).
        output_dir: Folder for log files; created if it does not exist. Ignored if log_file is None.
        include_sim_time: If True, use a formatter that shows [t=...] when sim time is set.
        fmt: Custom format string. If None, a default is used.
    """
    root = logging.getLogger("simulation")
    root.setLevel(level)

    if fmt is None:
        if include_sim_time:
            fmt = "%(asctime)s %(sim_time)s%(levelname)s %(name)s: %(message)s"
        else:
            fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if include_sim_time:
        formatter = SimTimeFormatter(fmt, datefmt="%H:%M:%S")
    else:
        formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")

    # Ensure sim_time exists on records when using SimTimeFormatter
    if include_sim_time:
        old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            if not hasattr(record, "sim_time"):
                record.sim_time = ""
            return record

        logging.setLogRecordFactory(record_factory)

    # Console handler
    if not root.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(level)
        console.setFormatter(formatter)
        root.addHandler(console)

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
