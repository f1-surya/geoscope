from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ENTRY_RE = re.compile(r"^\^(\w+)\s*=\s*(.*?)\s*$")
META_PREFIX_RE = re.compile(r"^[A-Za-z]*?_")

PROBE_COLUMN_CANDIDATES = (
    "id_ref",
    "probe_id",
    "probe set id",
    "probeset_id",
    "probe set",
    "id",
    "spot_id",
)

VALUE_COLUMN_EXCLUDE = ("p-value", "pvalue", "detection", "call", "present", "absent")

DEFAULT_RAM_BUDGET = 1_500_000_000
ANNOTATION_FLUSH_ROWS = 4096


def open_soft(path: Path):
    with open(path, "rb") as handle:
        magic = handle.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def _strip_metadata_prefix(key: str) -> str:
    return META_PREFIX_RE.sub("", key, count=1)


def _parse_entry(line: str) -> tuple[str, str] | None:
    match = ENTRY_RE.match(line)
    if not match:
        return None
    return match.group(1).strip().upper(), match.group(2).strip()


class SoftHandler:
    """Base callback handler for :func:`scan_soft`."""

    def on_entry_start(self, entry_type: str, name: str) -> None:
        pass

    def on_metadata(self, entry_type: str, name: str, key: str, value: str) -> None:
        pass

    def on_table_header(self, entry_type: str, name: str, columns: list[str]) -> None:
        pass

    def on_table_line(self, entry_type: str, name: str, line: str) -> None:
        pass

    def on_entry_end(self, entry_type: str, name: str) -> None:
        pass


def scan_soft(path: Path, handler: SoftHandler) -> None:
    """Stream a SOFT file, dispatching metadata and table lines to ``handler``.

    Tables are never buffered by the scanner itself, so memory stays bounded by
    whatever the handler chooses to keep.
    """
    entry_type = ""
    entry_name = ""
    in_table = False
    saw_columns = False

    with open_soft(path) as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            if line.startswith("^"):
                if entry_type:
                    handler.on_entry_end(entry_type, entry_name)
                in_table = False
                saw_columns = False
                parsed = _parse_entry(line)
                if parsed is None:
                    entry_type, entry_name = "", ""
                    continue
                entry_type, entry_name = parsed
                handler.on_entry_start(entry_type, entry_name)
                continue
            if line.startswith("!"):
                key, _, value = line[1:].partition("=")
                key = key.strip()
                lowered = key.lower()
                if lowered.endswith("_table_begin"):
                    in_table = True
                    saw_columns = False
                    continue
                if lowered.endswith("_table_end"):
                    in_table = False
                    saw_columns = False
                    continue
                handler.on_metadata(entry_type, entry_name, key, value.strip())
                continue
            if line.startswith("#"):
                continue
            if not in_table and entry_type in {"SAMPLE", "PLATFORM"}:
                # Some older SOFT files omit the *_table_begin markers.
                in_table = True
                saw_columns = False
            if not in_table:
                continue
            if not saw_columns:
                columns = [cell.strip() for cell in line.split("\t")]
                saw_columns = True
                handler.on_table_header(entry_type, entry_name, columns)
                continue
            handler.on_table_line(entry_type, entry_name, line)
        if entry_type:
            handler.on_entry_end(entry_type, entry_name)


def detect_probe_column(columns: Iterable[str]) -> int:
    lowered = [column.strip().lower() for column in columns]
    for candidate in PROBE_COLUMN_CANDIDATES:
        if candidate in lowered:
            return lowered.index(candidate)
    return 0


def detect_value_column(columns: list[str], first_cells: list[str], probe_index: int, override: str | None) -> int:
    normalized = [column.strip() for column in columns]
    lowered = [column.lower() for column in normalized]

    if override:
        for index, column in enumerate(normalized):
            if column.lower() == override.lower():
                return index
        raise ValueError(f"Expression value column '{override}' was not found in the sample table")

    if "value" in lowered:
        return lowered.index("value")

    numeric = [index for index, cell in enumerate(first_cells) if index != probe_index and _is_number(cell)]
    preferred = [
        index
        for index in numeric
        if any(token in lowered[index] for token in ("signal", "intensity", "expression", "count"))
    ]
    candidates = preferred or numeric or [index for index in range(len(columns)) if index != probe_index]
    if not candidates:
        raise ValueError("The sample table has no expression value column")
    return candidates[0]


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


@dataclass
class SeriesInfo:
    accession: str
    title: str
    sample_ids: list[str]
    platforms: list[str]
    phenotype: pd.DataFrame
    supplementary_only: bool = False


class _MetadataHandler(SoftHandler):
    def __init__(self) -> None:
        self.series: dict[str, list[str]] = {}
        self.samples: dict[str, dict[str, list[str]]] = {}
        self.sample_order: list[str] = []
        self.platforms: list[str] = []
        self.had_sample_table = False

    def on_entry_start(self, entry_type: str, name: str) -> None:
        if entry_type == "SAMPLE" and name not in self.samples:
            self.samples[name] = {}
            self.sample_order.append(name)

    def on_metadata(self, entry_type: str, name: str, key: str, value: str) -> None:
        if entry_type == "SERIES":
            self.series.setdefault(key, []).append(value)
        elif entry_type == "SAMPLE":
            row = self.samples.setdefault(name, {})
            row.setdefault(_strip_metadata_prefix(key), []).append(value)
            if key.lower().endswith("platform_id") and value and value not in self.platforms:
                self.platforms.append(value)

    def on_table_header(self, entry_type: str, name: str, columns: list[str]) -> None:
        if entry_type == "SAMPLE":
            self.had_sample_table = True


def read_series_metadata(path: Path, accession: str | None = None) -> SeriesInfo:
    handler = _MetadataHandler()
    scan_soft(path, handler)

    if not accession:
        accession = (handler.series.get("Series_geo_accession") or [""])[0]
    if not accession:
        accession = path.name.split("_")[0].upper()

    title = (handler.series.get("Series_title") or [accession])[0]
    platforms = list(handler.platforms)
    if not platforms:
        platforms = list(dict.fromkeys(handler.series.get("Series_platform_id", [])))
    if not platforms:
        platforms = ["unknown"]

    rows: dict[str, dict[str, Any]] = {}
    for name in handler.sample_order:
        record: dict[str, Any] = {}
        for key, values in handler.samples.get(name, {}).items():
            record[key] = values[0] if len(values) == 1 else " /// ".join(values)
        record.setdefault("platform_id", platforms[0])
        rows[name] = record

    phenotype = pd.DataFrame.from_dict(rows, orient="index")
    phenotype.index.name = "sample"
    phenotype = phenotype.reset_index()

    return SeriesInfo(
        accession=accession,
        title=title,
        sample_ids=list(handler.sample_order),
        platforms=platforms,
        phenotype=phenotype,
        supplementary_only=not handler.had_sample_table,
    )


def platform_cache_paths(dataset_path: Path, platform_index: int) -> dict[str, Path]:
    return {
        "annotation": dataset_path / f"platform-{platform_index}-annotation.parquet",
        "expression": dataset_path / f"platform-{platform_index}-expression.parquet",
        "phenotype": dataset_path / f"platform-{platform_index}-phenotype.parquet",
        "meta": dataset_path / f"platform-{platform_index}-meta.json",
    }


class _PlatformBuilder(SoftHandler):
    def __init__(
        self,
        platform_id: str,
        sample_ids: list[str],
        annotation_path: Path,
        value_column: str | None = None,
        ram_budget: int = DEFAULT_RAM_BUDGET,
    ) -> None:
        self.platform_id = platform_id
        self.sample_ids = list(sample_ids)
        self.sample_pos = {name: index for index, name in enumerate(self.sample_ids)}
        self.annotation_path = annotation_path
        self.value_column = value_column
        self.ram_budget = ram_budget

        self.found_platform = False
        self.annotation_columns: list[str] = []
        self.probe_ids: list[str] = []
        self.probe_index: pd.Index | None = None
        self.matrix: np.ndarray | None = None
        self.layout = "wide"
        self.resolved_value_column: str | None = None
        self.value_columns: list[str] = []

        self._annotation_writer: pq.ParquetWriter | None = None
        self._annotation_buffer: list[list[str]] = []
        self._annotation_sources: list[int] = []
        self._annotation_finished = False

        self._long_buffer: list[tuple[str, str, float]] = []

        self._current_sample: str | None = None
        self._sample_header: list[str] | None = None
        self._sample_lines: list[str] = []

    # -- platform annotation ------------------------------------------------
    def on_table_header(self, entry_type: str, name: str, columns: list[str]) -> None:
        if entry_type == "PLATFORM" and name == self.platform_id and not self.found_platform:
            self._start_annotation(columns)
        elif entry_type == "SAMPLE" and self._current_sample is not None:
            self._sample_header = columns

    def on_table_line(self, entry_type: str, name: str, line: str) -> None:
        if entry_type == "PLATFORM" and name == self.platform_id and self._annotation_writer is not None:
            self._annotation_row(line)
        elif entry_type == "SAMPLE" and self._current_sample is not None:
            self._sample_lines.append(line)

    def on_entry_start(self, entry_type: str, name: str) -> None:
        if entry_type == "SAMPLE":
            self._current_sample = name if name in self.sample_pos else None
            self._sample_header = None
            self._sample_lines = []

    def on_entry_end(self, entry_type: str, name: str) -> None:
        if entry_type == "PLATFORM" and name == self.platform_id and self.found_platform:
            self._finish_annotation()
        elif entry_type == "SAMPLE" and self._current_sample is not None:
            self._finish_sample()
            self._current_sample = None
            self._sample_lines = []

    def _start_annotation(self, columns: list[str]) -> None:
        self.found_platform = True
        probe_source = detect_probe_column(columns)
        names: list[str] = []
        sources: list[int] = []
        for index, column in enumerate(columns):
            name = "probe_id" if index == probe_source else (column or f"column_{index}")
            while name in names:
                name = f"{name}_"
            names.append(name)
            sources.append(index)
        self.annotation_columns = names
        self._annotation_sources = sources
        schema = pa.schema([(name, pa.string()) for name in names])
        self.annotation_path.parent.mkdir(parents=True, exist_ok=True)
        self._annotation_writer = pq.ParquetWriter(self.annotation_path, schema, compression="zstd")

    def _annotation_row(self, line: str) -> None:
        cells = line.split("\t")
        row = [cells[source].strip() if source < len(cells) else "" for source in self._annotation_sources]
        self.probe_ids.append(row[0])
        self._annotation_buffer.append(row)
        if len(self._annotation_buffer) >= ANNOTATION_FLUSH_ROWS:
            self._flush_annotation()

    def _flush_annotation(self) -> None:
        if not self._annotation_buffer or self._annotation_writer is None:
            return
        arrays = {
            name: pa.array([row[index] for row in self._annotation_buffer], type=pa.string())
            for index, name in enumerate(self.annotation_columns)
        }
        self._annotation_writer.write_table(pa.table(arrays))
        self._annotation_buffer.clear()

    def _finish_annotation(self) -> None:
        if self._annotation_finished:
            return
        self._annotation_finished = True
        self._flush_annotation()
        if self._annotation_writer is not None:
            self._annotation_writer.close()
            self._annotation_writer = None
        self.probe_index = pd.Index(self.probe_ids)
        estimated = len(self.probe_ids) * len(self.sample_ids) * 4
        if estimated > self.ram_budget:
            self.layout = "long"
            self.matrix = None
        else:
            self.matrix = np.full((len(self.probe_ids), len(self.sample_ids)), np.nan, dtype=np.float32)

    # -- sample tables ------------------------------------------------------
    def _finish_sample(self) -> None:
        if self._current_sample is None or not self._sample_lines or self.probe_index is None:
            return
        header = self._sample_header or []
        first_cells = self._sample_lines[0].split("\t")
        try:
            probe_index = detect_probe_column(header) if header else 0
            value_index = detect_value_column(header, first_cells, probe_index, self.value_column)
        except ValueError:
            self._sample_lines = []
            return
        if header:
            self.resolved_value_column = header[value_index] if value_index < len(header) else str(value_index)
            if not self.value_columns:
                candidates = [
                    header[index]
                    for index in range(len(header))
                    if index != probe_index
                    and _is_number(first_cells[index] if index < len(first_cells) else "")
                    and not any(token in header[index].lower() for token in VALUE_COLUMN_EXCLUDE)
                ]
                if self.resolved_value_column not in candidates:
                    candidates.insert(0, self.resolved_value_column)
                self.value_columns = candidates
        text = "\n".join(self._sample_lines)
        try:
            frame = pd.read_csv(
                StringIO(text),
                sep="\t",
                header=None,
                usecols=[probe_index, value_index],
                dtype=str,
                keep_default_na=False,
                na_values=[""],
                engine="c",
            )
        except Exception:
            self._sample_lines = []
            return
        probes = frame[probe_index].astype(str).to_numpy()
        values = pd.to_numeric(frame[value_index], errors="coerce").to_numpy(dtype=np.float32)
        positions = self.probe_index.get_indexer(probes)
        valid = positions >= 0
        if not valid.any():
            self._sample_lines = []
            return
        if self.layout == "long":
            sample = self._current_sample
            self._long_buffer.extend(
                (self.probe_ids[position], sample, float(value))
                for position, value in zip(positions[valid], values[valid])
                if not np.isnan(value)
            )
        else:
            column = self.sample_pos[self._current_sample]
            self.matrix[positions[valid], column] = values[valid]
        self._sample_lines = []

    def write_expression(self, path: Path) -> None:
        if self.layout == "long":
            schema = pa.schema([("probe_id", pa.string()), ("sample", pa.string()), ("value", pa.float32())])
            with pq.ParquetWriter(path, schema, compression="zstd") as writer:
                batch_size = 1_000_000
                for start in range(0, len(self._long_buffer), batch_size):
                    chunk = self._long_buffer[start : start + batch_size]
                    writer.write_table(
                        pa.table(
                            {
                                "probe_id": pa.array([row[0] for row in chunk], type=pa.string()),
                                "sample": pa.array([row[1] for row in chunk], type=pa.string()),
                                "value": pa.array([row[2] for row in chunk], type=pa.float32()),
                            }
                        )
                    )
            self._long_buffer = []
            return
        order = np.argsort(np.asarray(self.probe_ids, dtype=object))
        ordered_probes = [self.probe_ids[index] for index in order]
        expr = pd.DataFrame(self.matrix[order, :], columns=self.sample_ids)
        expr.insert(0, "probe_id", ordered_probes)
        table = pa.Table.from_pandas(expr, preserve_index=False)
        pq.write_table(table, path, row_group_size=4096, compression="zstd")


def build_platform_cache(
    series_path: Path,
    platform_id: str,
    sample_ids: list[str],
    phenotype: pd.DataFrame,
    platform_index: int,
    dataset_path: Path,
    value_column: str | None = None,
    gpl_soft_path: Path | None = None,
) -> dict[str, Any]:
    """Stream one platform of a series into bounded, reusable Parquet caches."""
    paths = platform_cache_paths(dataset_path, platform_index)
    builder = _PlatformBuilder(platform_id, sample_ids, paths["annotation"], value_column=value_column)
    scan_soft(series_path, builder)

    if not builder.found_platform:
        if not sample_ids:
            raise ValueError("This series does not contain per-sample expression tables.")
        if gpl_soft_path is None:
            raise ValueError(f"Series does not embed annotation for platform {platform_id}.")
        annotation_builder = _PlatformBuilder(platform_id, [], paths["annotation"], value_column=value_column)
        scan_soft(gpl_soft_path, annotation_builder)
        if not annotation_builder.found_platform:
            raise ValueError(f"Could not find annotation for platform {platform_id}.")
        builder.found_platform = True
        builder.annotation_columns = annotation_builder.annotation_columns
        builder.probe_ids = annotation_builder.probe_ids
        builder.probe_index = pd.Index(builder.probe_ids)
        builder.matrix = np.full((len(builder.probe_ids), len(builder.sample_ids)), np.nan, dtype=np.float32)
        builder.layout = "wide"
        scan_soft(series_path, builder)

    if not builder.found_platform:
        raise ValueError("This series does not contain per-sample expression tables.")

    builder.write_expression(paths["expression"])

    subset = phenotype
    if "sample" in phenotype.columns:
        subset = phenotype[phenotype["sample"].isin(set(sample_ids))]
    subset.to_parquet(paths["phenotype"], index=False)

    meta = {
        "platform_id": platform_id,
        "platform_index": platform_index,
        "value_column": builder.resolved_value_column or value_column or "value",
        "value_columns": builder.value_columns,
        "annotation_columns": builder.annotation_columns,
        "layout": builder.layout,
        "probe_count": len(builder.probe_ids),
        "sample_count": len(sample_ids),
        "rows": len(builder.probe_ids) * len(sample_ids),
    }
    paths["meta"].write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
