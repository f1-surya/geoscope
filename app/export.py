from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def export_table(frame: pd.DataFrame, path: Path, format_name: str) -> None:
    if format_name == "csv":
        frame.to_csv(path, index=False)
    elif format_name == "tsv":
        frame.to_csv(path, index=False, sep="\t")
    elif format_name == "xlsx":
        frame.to_excel(path, index=False)
    else:
        raise ValueError(f"Unsupported table export: {format_name}")


def export_report(path: Path, configuration: dict[str, Any], results: pd.DataFrame, plot_path: Path | None = None) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt

    with PdfPages(path) as pdf:
        figure = plt.figure(figsize=(8.3, 11.7))
        figure.text(0.08, 0.94, "GEOscope scientific report", fontsize=18, weight="bold")
        figure.text(0.08, 0.88, json.dumps(configuration, indent=2, default=str), family="monospace", va="top", fontsize=8)
        pdf.savefig(figure, bbox_inches="tight")
        plt.close(figure)
        if plot_path and plot_path.exists():
            image = plt.figure(figsize=(8.3, 11.7))
            image.figimage(plt.imread(plot_path), xo=25, yo=100, resize=True)
            pdf.savefig(image, bbox_inches="tight")
            plt.close(image)
