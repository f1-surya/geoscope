from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

from ..storage import Store
from .soft import (
    build_platform_cache,
    platform_cache_paths,
    read_series_metadata,
)


def validate_accession(accession: str) -> str:
    normalized = accession.strip().upper()
    if not re.fullmatch(r"GSE\d+", normalized):
        raise ValueError("Enter a GEO series accession such as GSE48558.")
    return normalized


def _series_soft_url(accession: str) -> str:
    range_subdir = re.sub(r"\d{1,3}$", "nnn", accession)
    return f"https://ftp.ncbi.nlm.nih.gov/geo/series/{range_subdir}/{accession}/soft/{accession}_family.soft.gz"


def _platform_soft_url(platform_id: str) -> str:
    range_subdir = re.sub(r"\d{1,3}$", "nnn", platform_id)
    return f"https://ftp.ncbi.nlm.nih.gov/geo/platforms/{range_subdir}/{platform_id}/soft/{platform_id}_family.soft.gz"


def _download_file(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return target
    partial = target.with_suffix(target.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            if partial.exists():
                partial.unlink()
            request = urllib.request.Request(url, headers={"User-Agent": "GEOscope/0.1"})
            with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            if partial.stat().st_size == 0:
                raise RuntimeError("NCBI returned an empty GEO file")
            partial.replace(target)
            return target
        except Exception as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"HTTPS download failed for {url}: {last_error}") from last_error


def _download_soft(accession: str, raw_dir: Path) -> Path:
    return _download_file(_series_soft_url(accession), raw_dir / f"{accession}_family.soft.gz")


def _download_platform_soft(platform_id: str, raw_dir: Path) -> Path:
    return _download_file(_platform_soft_url(platform_id), raw_dir / f"{platform_id}_family.soft.gz")


def _read_metadata(dataset_path: Path) -> dict[str, Any]:
    return json.loads((dataset_path / "metadata.json").read_text(encoding="utf-8"))


def load_dataset(accession: str, store: Store) -> dict[str, Any]:
    accession = validate_accession(accession)
    existing = store.dataset(accession)
    if existing:
        path = Path(existing["path"])
        if path.exists() and (path / "phenotype.parquet").exists():
            return {**json.loads(existing["metadata"]), "cached": True, "path": str(path)}

    raw_dir = store.paths["raw"]
    dataset_dir = store.paths["datasets"] / accession
    dataset_dir.mkdir(parents=True, exist_ok=True)
    try:
        soft_file = _download_soft(accession, raw_dir)
    except Exception as exc:
        raise RuntimeError(f"Could not download {accession} from GEO: {exc}") from exc

    try:
        info = read_series_metadata(soft_file, accession)
    except Exception as exc:
        raise RuntimeError(f"Could not parse {accession}: {exc}") from exc

    if not info.sample_ids:
        raise RuntimeError(f"{accession} does not contain sample metadata.")
    if info.supplementary_only:
        raise RuntimeError(
            f"{accession} does not embed per-sample expression tables. "
            "Series distributed only as supplementary files are not supported."
        )

    info.phenotype.to_parquet(dataset_dir / "phenotype.parquet", index=False)
    platforms = [{"index": index, "id": platform} for index, platform in enumerate(info.platforms)]
    metadata = {
        "accession": info.accession or accession,
        "title": info.title,
        "platforms": platforms,
        "sample_count": len(info.sample_ids),
        "cached": False,
    }
    (dataset_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    store.save_dataset(accession, dataset_dir, metadata)
    return {**metadata, "path": str(dataset_dir)}


def _platform_samples(phenotype: pd.DataFrame, platform_id: str) -> list[str]:
    if "platform_id" in phenotype.columns and platform_id != "unknown":
        selected = phenotype[phenotype["platform_id"].astype(str) == platform_id]
        if not selected.empty:
            return selected["sample"].astype(str).tolist()
    return phenotype["sample"].astype(str).tolist()


def load_platform(
    dataset_path: Path,
    platform_index: int,
    raw_dir: Path,
    value_column: str | None = None,
) -> dict[str, Any]:
    metadata = _read_metadata(dataset_path)
    platforms = metadata.get("platforms", [])
    if platform_index < 0 or platform_index >= len(platforms):
        raise ValueError("Selected platform is not available in this dataset.")
    platform_id = platforms[platform_index]["id"]

    phenotype_path = dataset_path / "phenotype.parquet"
    if not phenotype_path.exists():
        raise ValueError("Dataset is missing cached phenotype metadata; reload the dataset.")
    phenotype = pd.read_parquet(phenotype_path)
    sample_ids = _platform_samples(phenotype, platform_id)

    paths = platform_cache_paths(dataset_path, platform_index)
    cached_meta = json.loads(paths["meta"].read_text(encoding="utf-8")) if paths["meta"].exists() else None
    up_to_date = (
        cached_meta is not None
        and paths["annotation"].exists()
        and paths["expression"].exists()
        and paths["phenotype"].exists()
        and (value_column is None or cached_meta.get("value_column") == value_column)
    )
    if up_to_date:
        return cached_meta

    try:
        return build_platform_cache(
            series_path=_series_file(dataset_path, metadata["accession"], raw_dir),
            platform_id=platform_id,
            sample_ids=sample_ids,
            phenotype=phenotype,
            platform_index=platform_index,
            dataset_path=dataset_path,
            value_column=value_column,
        )
    except ValueError as exc:
        if "does not embed annotation" not in str(exc):
            raise
        gpl_soft = _download_platform_soft(platform_id, raw_dir)
        return build_platform_cache(
            series_path=_series_file(dataset_path, metadata["accession"], raw_dir),
            platform_id=platform_id,
            sample_ids=sample_ids,
            phenotype=phenotype,
            platform_index=platform_index,
            dataset_path=dataset_path,
            value_column=value_column,
            gpl_soft_path=gpl_soft,
        )


def _series_file(dataset_path: Path, accession: str, raw_dir: Path) -> Path:
    target = raw_dir / f"{accession}_family.soft.gz"
    if target.exists():
        return target
    return _download_soft(accession, raw_dir)
