from __future__ import annotations

import logging
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu
from statsmodels.stats.multitest import multipletests

logger = logging.getLogger("geoscope.analysis")


def _groups(data: pd.DataFrame, group_column: str, selected_samples: list[str] | None) -> pd.DataFrame:
    result = data.copy()
    if selected_samples:
        result = result[result["sample"].isin(selected_samples)]
    result = result.dropna(subset=[group_column, "value"])
    result[group_column] = result[group_column].astype(str)
    return result


def _test(values: pd.DataFrame, group_column: str) -> tuple[str, float, list[dict[str, Any]]]:
    groups = {name: part["value"].to_numpy(dtype=float) for name, part in values.groupby(group_column)}
    groups = {name: vals for name, vals in groups.items() if len(vals)}
    if len(groups) < 2:
        raise ValueError("At least two groups with numeric observations are required.")
    if any(len(vals) < 2 for vals in groups.values()):
        raise ValueError("Each comparison group needs at least two observations.")
    names = list(groups)
    if len(names) == 2:
        statistic, pvalue = mannwhitneyu(groups[names[0]], groups[names[1]], alternative="two-sided")
        return "Wilcoxon rank-sum (Mann-Whitney U), two-sided", float(pvalue), [{"group_a": names[0], "group_b": names[1], "p_value": float(pvalue), "adjusted_p_value": float(pvalue)}]
    statistic, omnibus = kruskal(*(groups[name] for name in names))
    pairs = list(combinations(names, 2))
    raw = [mannwhitneyu(groups[a], groups[b], alternative="two-sided").pvalue for a, b in pairs]
    adjusted = multipletests(raw, method="fdr_bh")[1]
    pairwise = [{"group_a": a, "group_b": b, "p_value": float(p), "adjusted_p_value": float(q)} for (a, b), p, q in zip(pairs, raw, adjusted)]
    return "Kruskal-Wallis omnibus; pairwise Wilcoxon rank-sum with Benjamini-Hochberg correction", float(omnibus), pairwise


def analyze(
    data: pd.DataFrame,
    genes: list[str],
    group_column: str,
    selected_samples: list[str] | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    if group_column not in data.columns:
        raise ValueError(f"Phenotype field '{group_column}' is not available.")
    filtered = _groups(data[data["gene_symbol"].isin(genes)], group_column, selected_samples)
    if filtered.empty:
        raise ValueError("No numeric expression values remain for the selected genes and samples.")
    results = []
    pairwise = []
    grouped = list(filtered.groupby("gene_symbol", sort=True))
    logger.debug("Analyzing %d genes across groups of %s", len(grouped), group_column)
    for index, (gene, gene_data) in enumerate(grouped, start=1):
        method, omnibus, comparisons = _test(gene_data, group_column)
        summary = gene_data.groupby(group_column)["value"].agg(["count", "mean", "median", "std"]).reset_index().rename(columns={group_column: "group"})
        results.append({"gene": gene, "method": method, "p_value": omnibus, "summary": summary.to_dict("records")})
        pairwise.extend({"gene": gene, **comparison} for comparison in comparisons)
        if progress is not None:
            progress.fraction(index / len(grouped), f"{index}/{len(grouped)} genes")
    return {"results": results, "pairwise": pairwise, "method": results[0]["method"], "data": filtered}
