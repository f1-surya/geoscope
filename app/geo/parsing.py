from __future__ import annotations

import re
from typing import Any

import pandas as pd


ACCESSION_RE = re.compile(r"^GSE\d+$", re.IGNORECASE)
ASSIGNMENT_SEPARATOR = re.compile(r"\s*///\s*")
RECORD_SEPARATOR = re.compile(r"\s*//\s*")
EMPTY_SYMBOLS = {"", "---", "na", "n/a", "nan", "null", "none"}

ASSIGNMENT_COLUMN_CANDIDATES = (
    "gene_assignment",
    "gene symbol",
    "gene_symbol",
    "genesymbol",
    "gene symbol(s)",
    "symbol",
    "symbols",
    "gene",
    "gene_name",
    "gene name",
)


def parse_assignment(value: Any) -> list[str]:
    """Extract gene symbols from either GEOquery or raw array annotation.

    Handles ``gene_assignment`` records such as ``NM_1 // CD5 // ...`` and raw
    symbol lists such as ``CD5 /// CD7``.
    """
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in EMPTY_SYMBOLS:
        return []
    symbols: list[str] = []
    for entry in ASSIGNMENT_SEPARATOR.split(text):
        entry = entry.strip()
        if not entry or entry.lower() in EMPTY_SYMBOLS:
            continue
        parts = RECORD_SEPARATOR.split(entry)
        symbol = parts[1].strip() if len(parts) >= 2 else entry
        if symbol and symbol.lower() not in EMPTY_SYMBOLS and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def detect_assignment_column(columns: list[str]) -> str | None:
    normalized = {str(column).strip().lower(): str(column) for column in columns}
    for candidate in ASSIGNMENT_COLUMN_CANDIDATES:
        if candidate in normalized:
            return normalized[candidate]
    for column in columns:
        if "symbol" in str(column).lower():
            return str(column)
    return None


def annotation_columns(annotation: pd.DataFrame) -> list[str]:
    """Return annotation fields that can be selected for gene assignment."""
    return [str(column) for column in annotation.columns if str(column) != "probe_id"]


def _with_probe_column(annotation: pd.DataFrame) -> pd.DataFrame:
    if "probe_id" in annotation.columns:
        return annotation.copy()
    table = annotation.copy()
    table.index.name = "probe_id"
    return table.reset_index()


def build_mapping(annotation: pd.DataFrame, assignment_column: str, genes: list[str] | None = None) -> pd.DataFrame:
    """Return unique ``probe_id`` / ``gene_symbol`` pairs from an annotation frame."""
    table = _with_probe_column(annotation)
    if "category" in table.columns:
        table = table[table["category"].astype(str).str.lower().eq("main")]
    if assignment_column not in table.columns:
        raise ValueError(f"Platform annotation has no '{assignment_column}' gene assignment column")
    table = table[["probe_id", assignment_column]].copy()
    table["gene_symbol"] = table[assignment_column].map(parse_assignment)
    table = table.explode("gene_symbol").dropna(subset=["gene_symbol"])
    table = table[["probe_id", "gene_symbol"]].drop_duplicates()
    if genes is not None:
        table = table[table["gene_symbol"].isin(set(genes))]
    return table


def _annotation_table(annotation: pd.DataFrame, assignment_column: str, genes: set[str] | None = None) -> pd.DataFrame:
    return build_mapping(annotation, assignment_column, list(genes) if genes is not None else None)


def prepare_expression_data(
    expression: pd.DataFrame,
    phenotype: pd.DataFrame,
    annotation: pd.DataFrame,
    assignment_column: str = "gene_assignment",
    genes: list[str] | None = None,
) -> pd.DataFrame:
    """Replicate the Quarto long-form expression/annotation/phenotype join."""
    mapped = build_mapping(annotation, assignment_column, genes)
    values = expression.copy()
    if genes is not None:
        values = values[values.index.isin(mapped["probe_id"])]
    values.index.name = "probe_id"
    values = values.reset_index().melt(id_vars="probe_id", var_name="sample", value_name="value")
    values["value"] = pd.to_numeric(values["value"], errors="coerce")
    values = values.merge(mapped, on="probe_id", how="left")
    pheno = phenotype.copy()
    pheno.index.name = "sample"
    pheno = pheno.reset_index()
    return values.merge(pheno, on="sample", how="left")


def assemble_long(
    expression: pd.DataFrame,
    mapped: pd.DataFrame,
    phenotype: pd.DataFrame,
    layout: str = "wide",
) -> pd.DataFrame:
    """Combine a cached expression table with its probe mapping and phenotype."""
    if layout == "long":
        values = expression.copy()
    else:
        values = expression.melt(id_vars="probe_id", var_name="sample", value_name="value")
    values = values.merge(mapped, on="probe_id", how="inner")
    pheno = phenotype.copy()
    if "sample" not in pheno.columns:
        pheno.index.name = "sample"
        pheno = pheno.reset_index()
    return values.merge(pheno, on="sample", how="left")


def clean_gene_values(data: pd.DataFrame, genes: list[str]) -> pd.DataFrame:
    selected = data[data["gene_symbol"].isin(genes)].copy()
    return selected.dropna(subset=["value", "gene_symbol"])
