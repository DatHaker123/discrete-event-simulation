from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core import Engine


@dataclass(frozen=True)
class RunOptions:
    """CLI/runtime options that simulations may use for custom post-run output."""

    plot: bool = False


def print_series_sample(series: list[tuple[float, float]], *, label: str = "series") -> None:
    print(f"\n# {label} sample (t, value)")
    for t, s in series[:25]:
        print(f"{t:.4f}\t{s:.4f}")
    if len(series) > 25:
        print("...")
    for t, s in series[-12:]:
        print(f"{t:.4f}\t{s:.4f}")


class SimulationPlot:
    """Minimal, immediate-draw state-history plot helper."""

    def __init__(
        self,
        *,
        state_history: list[tuple[float, dict[str, Any]]],
        y_key: str,
        name: str | None = None,
    ) -> None:
        import matplotlib.pyplot as plt

        self.state_history = state_history
        self.y_key = y_key
        self.name = name or y_key
        self.x_label = "time"
        self.y_label = y_key

        by_t: dict[float, float] = {}
        for t, snap in self.state_history:
            if isinstance(snap, dict) and y_key in snap:
                by_t[float(t)] = float(snap[y_key])
        self.series = sorted(by_t.items())
        self.x_values = [x for x, _ in self.series]
        self.y_values = [y for _, y in self.series]

        self.fig, self.ax = plt.subplots(figsize=(8, 3))
        if self.series:
            self.ax.plot(self.x_values, self.y_values, color="C0", lw=1.2, label=self.y_key)

    def add_horizontal_line(self, y: float, *, color: str = "C3", label: str | None = None) -> "SimulationPlot":
        self.ax.axhline(float(y), color=color, ls="--", lw=0.9, alpha=0.85, label=label)
        return self

    def add_vertical_line(self, x: float, *, color: str = "red", label: str | None = None) -> "SimulationPlot":
        self.ax.axvline(float(x), color=color, ls="-", lw=0.8, alpha=0.35, label=label)
        return self

    def add_trace(
        self,
        series: list[tuple[float, float]],
        *,
        color: str | None = None,
        label: str | None = None,
    ) -> "SimulationPlot":
        if series:
            xs, ys = zip(*series)
            self.ax.plot(xs, ys, lw=1.0, alpha=0.9, color=(color or "C1"), label=label)
        return self

    def plot_mode_changes(self) -> "SimulationPlot":
        """
        Plot all mode transitions from this plot's state history.

        Assumes mode is tracked under the ``mode`` key, verifies presence, and assigns
        deterministic colors per (from_mode -> to_mode) pair.
        """
        if not self.series:
            return self
        if not self.state_history:
            return self
        if not all(isinstance(snap, dict) and "mode" in snap for _, snap in self.state_history):
            return self

        palette = ("gold", "darkgoldenrod", "plum", "purple", "teal", "firebrick", "olive", "navy")
        mode_to_color: dict[str, str] = {}
        color_cycle = itertools.cycle(palette)
        used_labels: set[str] = set()
        last_mode: Any = None
        initialized = False

        for t, snap in self.state_history:
            current_mode = snap["mode"]
            if not initialized:
                mode_label = str(current_mode)
                if mode_label not in mode_to_color:
                    mode_to_color[mode_label] = next(color_cycle)
                start_label = f"mode={mode_label}"
                self.add_vertical_line(float(t), color=mode_to_color[mode_label], label=start_label)
                used_labels.add(mode_label)
                last_mode = current_mode
                initialized = True
                continue
            if current_mode == last_mode:
                continue
            mode_label = str(current_mode)
            if mode_label not in mode_to_color:
                mode_to_color[mode_label] = next(color_cycle)
            display_label = f"mode={mode_label}"
            legend_label = display_label if mode_label not in used_labels else None
            if legend_label is not None:
                used_labels.add(mode_label)
            self.add_vertical_line(float(t), color=mode_to_color[mode_label], label=legend_label)
            last_mode = current_mode
        return self

    def render(
        self,
        *,
        output_name_prefix: str = "plot",
        show: bool = True,
    ) -> Path | None:
        if not self.series:
            return None
        self.ax.set_xlabel(self.x_label)
        self.ax.set_ylabel(self.y_label)
        self.ax.set_title(self.name)
        handles, _labels = self.ax.get_legend_handles_labels()
        if handles:
            self.ax.legend(loc="upper right", fontsize=8)
        self.fig.tight_layout()
        output_dir = Path("output")
        output_path = output_dir / f"{output_name_prefix}_{uuid.uuid4()}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.fig.savefig(output_path, dpi=120)
        import matplotlib.pyplot as plt

        if show:
            plt.show()
        else:
            plt.close(self.fig)
        return output_path

