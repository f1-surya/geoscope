from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPL_IGNORE_SYSTEM_FONTS", "1")

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import pandas as pd


PALETTES = {
    "Scientific": ["#E64B35", "#4DBBD5", "#00A087", "#F39B7F", "#8491B4", "#3C5488"],
    "Colorblind-safe": ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9"],
    "Muted": ["#6B7280", "#8DA0CB", "#66C2A5", "#FC8D62", "#E78AC3", "#A6D854"],
    "High contrast": ["#000000", "#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2"],
    "Monochrome": ["#111827", "#374151", "#6B7280", "#9CA3AF", "#D1D5DB", "#E5E7EB"],
}


def create_plot(data: pd.DataFrame, group_column: str, palette: list[str], output: Path, title: str = "", group_order: list[str] | None = None) -> None:
    genes = list(data["gene_symbol"].dropna().unique())
    groups = group_order or list(data[group_column].astype(str).dropna().unique())
    colors = {group: palette[index % len(palette)] for index, group in enumerate(groups)}
    fig, axes = plt.subplots(max(1, len(genes)), 1, figsize=(8, max(4, 3.4 * len(genes))), squeeze=False)
    for axis, gene in zip(axes[:, 0], genes):
        subset = data[data["gene_symbol"] == gene]
        positions = list(range(len(groups)))
        values = [subset[subset[group_column].astype(str) == group]["value"].dropna().to_numpy() for group in groups]
        axis.violinplot(values, positions=positions, showmeans=False, showmedians=False, showextrema=False)
        for position, group, group_values in zip(positions, groups, values):
            axis.boxplot(group_values, positions=[position], widths=0.15, patch_artist=True, boxprops={"facecolor": "white"}, medianprops={"color": "black"}, flierprops={"marker": ""})
            jitter = (pd.Series(range(len(group_values))) % 7 - 3) / 30
            axis.scatter([position + float(value) for value in jitter], group_values, s=13, alpha=0.6, color=colors[group], edgecolors="black", linewidths=0.2)
        axis.set_title(gene, loc="left", fontweight="bold")
        axis.set_xticks(positions, groups, rotation=30, ha="right")
        axis.set_ylabel("Expression")
        axis.grid(axis="y", alpha=0.2)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)
