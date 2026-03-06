"""
Frame-by-frame visualization: the engine creates a Visualizer per run and calls add_frame
for each step; the Visualizer writes one PDF page per frame as the simulation runs.
"""

import os
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.backends.backend_pdf import PdfPages

if TYPE_CHECKING:
    from engine import Engine

PDF_QUEUE_LINES = 14


def _format_event(e) -> str:
    return f"  t={e.time:.2f}  {e.handler_id:12s}  {e.type}"


class Visualizer:
    """
    Writes one PDF page per simulation frame. Instantiated by the engine at the start of run();
    the engine calls add_frame() each step and close() when the run finishes.
    """

    def __init__(
        self,
        nodes: list,
        edges: list[tuple],
        output_dir: str = "output",
        filename: str | None = None,
    ):
        os.makedirs(output_dir, exist_ok=True)
        if filename is None:
            filename = f"{uuid.uuid4()}.pdf"
        self._path = os.path.join(output_dir, filename)
        self._pdf = PdfPages(self._path)
        self._nodes = list(nodes)
        self._edges = list(edges)
        self._G = nx.DiGraph()
        self._G.add_nodes_from(self._nodes)
        self._G.add_edges_from(self._edges)
        self._pos = nx.spring_layout(self._G, seed=42) if self._nodes else {}
        self._frame_idx = 0
        print(f"Recording frames → {self._path}")

    def add_frame(self, time_val: float, event, queue_snapshot: list) -> None:
        """Append one page to the PDF for this step."""
        highlight_id = event.handler_id if event is not None else None
        idx = self._frame_idx
        self._frame_idx += 1
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        event_desc = f" {event.handler_id} ← {event.type}" if event is not None else " (initial)"
        print(f"[{ts}] frame {idx}  sim t={time_val:.2f}{event_desc}")

        fig, (ax_graph, ax_queue) = plt.subplots(
            1, 2, figsize=(12, 6), gridspec_kw={"width_ratios": [1.2, 1]}
        )
        ax_queue.set_axis_off()

        if self._nodes:
            node_colors = [
                "#2ecc71" if n == highlight_id else "#3498db" for n in self._nodes
            ]
            nx.draw_networkx_nodes(
                self._G, self._pos, ax=ax_graph, node_color=node_colors, node_size=1200
            )
            nx.draw_networkx_edges(
                self._G, self._pos, ax=ax_graph, edge_color="#7f8c8d", arrows=True, arrowsize=20
            )
            nx.draw_networkx_labels(
                self._G, self._pos, ax=ax_graph, labels={n: n for n in self._nodes}, font_size=10
            )
            ax_graph.set_title(f"Component graph — current time t = {time_val:.2f}")
        else:
            ax_graph.set_axis_off()
            ax_graph.text(
                0.5, 0.5, "No components", ha="center", va="center", transform=ax_graph.transAxes
            )
        ax_graph.axis("off")

        queue_lines = [f"Event queue (frame {idx}, t={time_val:.2f}):", ""]
        if not queue_snapshot:
            queue_lines.append("  (empty)")
        else:
            for e in queue_snapshot[:PDF_QUEUE_LINES]:
                queue_lines.append(_format_event(e))
            if len(queue_snapshot) > PDF_QUEUE_LINES:
                queue_lines.append(f"  ... +{len(queue_snapshot) - PDF_QUEUE_LINES} more")
        ax_queue.text(
            0, 1, "\n".join(queue_lines),
            transform=ax_queue.transAxes, fontsize=9,
            verticalalignment="top", fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#ecf0f1", edgecolor="#bdc3c7"),
        )
        fig.suptitle(
            f"Frame {idx}" + (f" — {event.handler_id} ← {event.type}" if event else " — Initial state"),
            y=1.02,
        )
        self._pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    def close(self) -> str:
        """Close the PDF and return the file path."""
        self._pdf.close()
        print(f"Recorded {self._frame_idx} frames → {self._path}")
        return self._path
