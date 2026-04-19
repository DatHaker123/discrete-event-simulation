from __future__ import annotations

import pprint
from pathlib import Path
from typing import Any, Iterable, Sequence


def state_key_series_from_history(component: Any, key: str) -> list[tuple[float, float]]:
    """
    Build ``(time, value)`` from a component's ``state_history``, keeping one point per time
    (last snapshot at each time wins). Only snapshots that contain ``key`` are used.
    """
    history = getattr(component, "state_history", None)
    if not history:
        return []
    by_t: dict[float, float] = {}
    for t, snap in history:
        if isinstance(snap, dict) and key in snap:
            by_t[float(t)] = float(snap[key])
    return sorted(by_t.items())


def state_history_snapshots(component: Any) -> list[tuple[float, dict[str, Any]]]:
    """Return a copy of ``(time, state_dict)`` rows from ``component.state_history``."""
    history = getattr(component, "state_history", None)
    if not history:
        return []
    return list(history)


def plot_time_series(
    series: list[tuple[float, float]],
    *,
    x_label: str = "time",
    y_label: str = "value",
    title: str = "",
    line_label: str | None = "series",
    horizontal_lines: Sequence[tuple[float, str]] | None = None,
    save_path: Path | str | None = None,
    show: bool = True,
    figsize: tuple[float, float] = (8, 3),
    dpi: int = 120,
) -> None:
    """
    Plot a single ``(x, y)`` series (e.g. time vs a state variable). Optional dashed horizontal
    reference lines ``(y, label)`` each get a default color from the matplotlib cycle.
    """
    import matplotlib.pyplot as plt

    if not series:
        return
    xs, ys = zip(*series)
    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(xs, ys, color="C0", lw=1.2, label=line_label if line_label else None)
    if horizontal_lines:
        h_colors = ("C3", "C2", "C4", "C5", "C1")
        for i, (y, hlabel) in enumerate(horizontal_lines):
            ax.axhline(
                y, color=h_colors[i % len(h_colors)], ls="--", lw=0.9, alpha=0.85, label=hlabel
            )
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    if title:
        ax.set_title(title)
    if line_label or horizontal_lines:
        ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    if save_path is not None:
        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=dpi)
    if show:
        plt.show()
    else:
        plt.close(fig)


def _format_sink_entity_one_line(entity: Any, max_len: int = 76) -> str:
    """Single-line representation for table cells; truncates long payloads."""
    if isinstance(entity, (dict, list, tuple, set)):
        s = pprint.pformat(entity, width=100, compact=True, sort_dicts=True)
    else:
        s = repr(entity)
    s = " ".join(s.split())
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _format_sink_component_block(cid: str, records: list) -> str:
    lines: list[str] = [f"  {cid}  ({len(records)} arrival(s))"]

    if not records:
        lines.append("    (empty)")
        return "\n".join(lines)

    lines.extend(
        [
            "",
            f"    {'idx':>4}  {'arrival t':>12}  {'dt':>10}  entity",
            f"    {'-' * 4}  {'-' * 12}  {'-' * 10}  {'-' * 40}",
        ]
    )

    prev_t: float | None = None
    for i, rec in enumerate(records):
        if isinstance(rec, tuple) and len(rec) >= 2:
            t, ent = float(rec[0]), rec[1]
            if prev_t is None:
                dt_s = f"{'—':>10}"
            else:
                dt_s = f"{t - prev_t:10.4f}"
            prev_t = t
            ent_s = _format_sink_entity_one_line(ent)
            lines.append(f"    {i:4d}  {t:12.4f}  {dt_s}  {ent_s}")
        else:
            lines.append(f"    {i:4d}  {'(bad row)':>12}  {'—':>10}  {rec!r}")

    return "\n".join(lines)


def get_records_as_printable_string(components: Iterable) -> str:
    """Format sink ``records`` and non-empty ``state_history`` from components for printing."""
    parts: list[str] = []

    sink_blocks: list[str] = []
    for component in components:
        records = getattr(component, "records", None)
        if records is not None:
            cid = getattr(component, "component_id", id(component))
            sink_blocks.append(_format_sink_component_block(cid, records))

    if sink_blocks:
        parts.append("Sink records\n" + "\n\n".join(sink_blocks))
    else:
        parts.append("(no sink records)")

    state_blocks: list[str] = []
    for component in components:
        history = getattr(component, "state_history", None)
        if not history:
            continue
        cid = getattr(component, "component_id", id(component))
        lines = [f"  {cid}  ({len(history)} snapshot(s)):"]
        for t, snap in history:
            lines.append(f"    t = {t:10.4f}")
            snap_str = pprint.pformat(snap, width=88, sort_dicts=True)
            for snap_line in snap_str.splitlines():
                lines.append(f"      {snap_line}")
        state_blocks.append("\n".join(lines))

    if state_blocks:
        parts.append("Recorded component states\n" + "\n\n".join(state_blocks))
    else:
        parts.append("(no recorded component states)")

    return "\n\n".join(parts) + "\n"
