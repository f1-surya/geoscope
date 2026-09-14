from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import certifi
import pandas as pd

from ..storage import Store
from .soft import (
    build_platform_cache,
    platform_cache_paths,
    read_series_metadata,
)

logger = logging.getLogger("geoscope.geo")


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


def _build_ssl_context() -> ssl.SSLContext:
    """Trust the OS certificate store plus certifi's public roots.

    Frozen builds bundle their own OpenSSL, whose compiled-in CA paths come
    from the build machine and are often absent at runtime. Layering certifi
    on top of the default context keeps platform/enterprise roots working
    while guaranteeing a usable trust store on Linux, macOS, and Windows.
    """
    context = ssl.create_default_context()
    try:
        context.load_verify_locations(cafile=certifi.where())
    except (OSError, ssl.SSLError):
        logger.warning("Could not load bundled certifi roots; relying on the OS trust store", exc_info=True)
    try:
        roots = context.cert_store_stats().get("x509_ca", 0)
    except Exception:
        roots = "unknown"
    logger.info("SSL context ready with %s trusted CA certificates", roots)
    return context


_SSL_CONTEXT = _build_ssl_context()


def _download_file(url: str, target: Path, progress: Any | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        logger.debug("Using cached download %s", target)
        return target
    partial = target.with_suffix(target.suffix + ".part")
    last_error: Exception | None = None
    logger.info("Downloading %s", url)
    for attempt in range(3):
        try:
            if partial.exists():
                partial.unlink()
            request = urllib.request.Request(url, headers={"User-Agent": "GEOscope/0.1"})
            with urllib.request.urlopen(request, timeout=120, context=_SSL_CONTEXT) as response, partial.open("wb") as output:
                length = response.headers.get("Content-Length")
                total = int(length) if length and length.isdigit() else None
                downloaded = 0
                if progress is not None:
                    progress.bytes(0, total)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress.bytes(downloaded, total)
            if partial.stat().st_size == 0:
                raise RuntimeError("NCBI returned an empty GEO file")
            partial.replace(target)
            logger.info("Downloaded %s (%d bytes)", target.name, target.stat().st_size)
            return target
        except Exception as exc:
            last_error = exc
            logger.warning("Download attempt %d/3 failed for %s: %s", attempt + 1, url, exc)
            time.sleep(2**attempt)
    logger.error("Giving up downloading %s", url)
    raise RuntimeError(f"HTTPS download failed for {url}: {last_error}") from last_error


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUTILS_TIMEOUT = 15
MAX_SUMMARY_SAMPLES = 200


def _eutils_json(endpoint: str, params: dict[str, str]) -> dict[str, Any]:
    query = {"retmode": "json", "tool": "geoscope", **params}
    email = os.environ.get("GEOSCOPE_EMAIL")
    if email:
        query["email"] = email
    url = f"{EUTILS_BASE}/{endpoint}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"User-Agent": "GEOscope/0.1"})
    with urllib.request.urlopen(request, timeout=EUTILS_TIMEOUT, context=_SSL_CONTEXT) as response:
        return json.loads(response.read().decode("utf-8"))


def _esummary_record(uid: str) -> dict[str, Any] | None:
    result = _eutils_json("esummary.fcgi", {"db": "gds", "id": uid}).get("result", {})
    record = result.get(uid)
    if record:
        return record
    return next((value for key, value in result.items() if key != "uids" and isinstance(value, dict)), None)


def _esearch_uid(accession: str) -> str | None:
    ids = _eutils_json("esearch.fcgi", {"db": "gds", "term": f"{accession}[Accession]"}).get("esearchresult", {}).get("idlist", [])
    for candidate in ids:
        if candidate.startswith("200") and candidate[3:] == accession[3:]:
            return candidate
    return ids[0] if ids else None


def _format_platform(value: Any) -> str:
    text = str(value).strip()
    return text if text.upper().startswith("GPL") else f"GPL{text}"


def _normalize_summary(record: dict[str, Any]) -> dict[str, Any]:
    gpl = record.get("gpl")
    samples = record.get("samples") or []
    return {
        "accession": record.get("accession"),
        "title": record.get("title"),
        "summary": record.get("summary"),
        "organism": record.get("taxon"),
        "experiment_type": record.get("gdstype"),
        "platforms": [_format_platform(gpl)] if gpl else [],
        "sample_count": record.get("n_samples"),
        "samples": [
            {"accession": sample.get("accession"), "title": sample.get("title")}
            for sample in samples[:MAX_SUMMARY_SAMPLES]
            if isinstance(sample, dict)
        ],
        "public_date": record.get("pdat"),
        "pubmed_ids": record.get("pubmedids") or [],
        "bioproject": record.get("bioproject"),
        "ftp_link": record.get("ftplink"),
        "supplementary_type": record.get("suppfile"),
        "relations": [
            relation.get("targetobject")
            for relation in (record.get("extrelations") or [])
            if isinstance(relation, dict) and relation.get("targetobject")
        ],
    }


def fetch_series_summary(accession: str) -> dict[str, Any]:
    """Fetch lightweight GEO series metadata from NCBI E-utilities.

    The ``gds`` summary is available without downloading the expression
    matrix, so callers can display dataset details while acquisition runs.
    """
    accession = validate_accession(accession)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            uid = str(200000000 + int(accession[3:]))
            record = _esummary_record(uid)
            if not record or record.get("accession") != accession:
                uid = _esearch_uid(accession)
                record = _esummary_record(uid) if uid else None
            if not record:
                raise RuntimeError(f"GEO did not return a summary for {accession}")
            return _normalize_summary(record)
        except Exception as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"Could not fetch GEO metadata for {accession}: {last_error}") from last_error


def dataset_info(metadata: dict[str, Any]) -> dict[str, Any]:
    """Normalize stored dataset metadata and GEO summary into one view."""
    geo = metadata.get("geo") or {}
    platform_ids: list[str] = []
    for platform in metadata.get("platforms") or []:
        identifier = platform.get("id") if isinstance(platform, dict) else platform
        if identifier:
            platform_ids.append(str(identifier))
    if not platform_ids:
        platform_ids = [str(value) for value in (geo.get("platforms") or []) if value]
    sample_count = metadata.get("sample_count")
    if sample_count is None:
        sample_count = geo.get("sample_count")
    return {
        "accession": metadata.get("accession") or geo.get("accession"),
        "title": metadata.get("title") or geo.get("title"),
        "summary": geo.get("summary") or metadata.get("summary") or "",
        "overall_design": metadata.get("overall_design") or geo.get("overall_design") or "",
        "organism": metadata.get("organism") or geo.get("organism") or "",
        "experiment_type": metadata.get("experiment_type") or geo.get("experiment_type") or "",
        "platform_ids": platform_ids,
        "sample_count": sample_count,
        "probe_count": metadata.get("probe_count"),
        "samples": geo.get("samples") or [],
        "public_date": geo.get("public_date") or "",
        "submission_date": metadata.get("submission_date") or "",
        "last_update_date": metadata.get("last_update_date") or geo.get("last_update_date") or "",
        "pubmed_ids": metadata.get("pubmed_ids") or geo.get("pubmed_ids") or [],
        "contributors": metadata.get("contributors") or [],
        "bioproject": geo.get("bioproject") or "",
        "ftp_link": geo.get("ftp_link") or "",
        "supplementary_type": geo.get("supplementary_type") or "",
        "relations": metadata.get("relations") or geo.get("relations") or [],
    }


def _persist_metadata(store: Store, accession: str, dataset_path: Path, metadata: dict[str, Any]) -> None:
    (dataset_path / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    store.update_dataset_metadata(accession, metadata)


def _ensure_geo_summary(accession: str, metadata: dict[str, Any], dataset_path: Path, store: Store) -> None:
    if metadata.get("geo"):
        return
    try:
        metadata["geo"] = fetch_series_summary(accession)
    except Exception:
        return
    _persist_metadata(store, accession, dataset_path, metadata)


def load_dataset_info(accession: str, store: Store) -> dict[str, Any]:
    """Best-effort dataset metadata for display, cached locally when possible."""
    accession = validate_accession(accession)
    existing = store.dataset(accession)
    if existing:
        metadata = json.loads(existing["metadata"])
        dataset_path = Path(existing["path"])
        _ensure_geo_summary(accession, metadata, dataset_path, store)
        return {"available": True, "info": dataset_info(metadata)}
    try:
        geo = fetch_series_summary(accession)
    except Exception:
        return {"available": False, "accession": accession, "info": {}}
    return {"available": True, "info": dataset_info({"accession": accession, "geo": geo})}


def _download_soft(accession: str, raw_dir: Path, progress: Any | None = None) -> Path:
    return _download_file(_series_soft_url(accession), raw_dir / f"{accession}_family.soft.gz", progress)


def _download_platform_soft(platform_id: str, raw_dir: Path, progress: Any | None = None) -> Path:
    return _download_file(_platform_soft_url(platform_id), raw_dir / f"{platform_id}_family.soft.gz", progress)


def _read_metadata(dataset_path: Path) -> dict[str, Any]:
    return json.loads((dataset_path / "metadata.json").read_text(encoding="utf-8"))


def load_dataset(accession: str, store: Store, progress: Any | None = None) -> dict[str, Any]:
    accession = validate_accession(accession)
    existing = store.dataset(accession)
    if existing:
        path = Path(existing["path"])
        if path.exists() and (path / "phenotype.parquet").exists():
            logger.info("Using cached dataset %s at %s", accession, path)
            metadata = json.loads(existing["metadata"])
            _ensure_geo_summary(accession, metadata, path, store)
            if progress is not None:
                progress.stage("cached", f"Using cached dataset {accession}")
                progress.info(
                    **{
                        key: value
                        for key, value in (
                            ("title", metadata.get("title")),
                            ("sample_count", metadata.get("sample_count")),
                            ("organism", metadata.get("organism")),
                            ("experiment_type", metadata.get("experiment_type")),
                            ("pubmed_ids", metadata.get("pubmed_ids")),
                        )
                        if value
                    }
                )
            return {**metadata, "cached": True, "path": str(path), "info": dataset_info(metadata)}

    raw_dir = store.paths["raw"]
    dataset_dir = store.paths["datasets"] / accession
    dataset_dir.mkdir(parents=True, exist_ok=True)
    if progress is not None:
        progress.info(accession=accession)
        progress.stage("download", f"Downloading {accession} from GEO")
    try:
        soft_file = _download_soft(accession, raw_dir, progress)
    except Exception as exc:
        raise RuntimeError(f"Could not download {accession} from GEO: {exc}") from exc

    if progress is not None:
        progress.stage("metadata", "Parsing series metadata")
    try:
        info = read_series_metadata(soft_file, accession, progress=progress)
    except Exception as exc:
        raise RuntimeError(f"Could not parse {accession}: {exc}") from exc

    if not info.sample_ids:
        raise RuntimeError(f"{accession} does not contain sample metadata.")
    if info.supplementary_only:
        raise RuntimeError(
            f"{accession} does not embed per-sample expression tables. "
            "Series distributed only as supplementary files are not supported."
        )

    if progress is not None:
        progress.info(accession=info.accession or accession, title=info.title, sample_count=len(info.sample_ids), platforms=info.platforms)
        progress.stage("save", "Saving dataset metadata")
    info.phenotype.to_parquet(dataset_dir / "phenotype.parquet", index=False)
    platforms = [{"index": index, "id": platform} for index, platform in enumerate(info.platforms)]
    try:
        geo_summary = fetch_series_summary(accession)
    except Exception:
        geo_summary = {}
    metadata = {
        "accession": info.accession or accession,
        "title": info.title,
        "platforms": platforms,
        "sample_count": len(info.sample_ids),
        "cached": False,
        "summary": info.summary,
        "overall_design": info.overall_design,
        "experiment_type": info.experiment_type,
        "submission_date": info.submission_date,
        "last_update_date": info.last_update_date,
        "pubmed_ids": info.pubmed_ids,
        "contributors": info.contributors,
        "organism": info.organism,
        "relations": info.relations,
        "geo": geo_summary,
    }
    (dataset_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    store.save_dataset(accession, dataset_dir, metadata)
    logger.info(
        "Saved dataset %s: %d samples, platforms=%s",
        accession,
        len(info.sample_ids),
        [platform["id"] for platform in platforms],
    )
    return {**metadata, "path": str(dataset_dir), "info": dataset_info(metadata)}


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
    progress: Any | None = None,
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
        logger.debug("Using cached platform %s for %s", platform_id, dataset_path.name)
        return cached_meta

    logger.info("Building platform cache for %s (%s), %d samples", platform_id, dataset_path.name, len(sample_ids))
    if progress is not None:
        progress.stage("platform", f"Parsing platform {platform_id}")
    try:
        return build_platform_cache(
            series_path=_series_file(dataset_path, metadata["accession"], raw_dir, progress),
            platform_id=platform_id,
            sample_ids=sample_ids,
            phenotype=phenotype,
            platform_index=platform_index,
            dataset_path=dataset_path,
            value_column=value_column,
            progress=progress,
        )
    except ValueError as exc:
        if "does not embed annotation" not in str(exc):
            raise
        if progress is not None:
            progress.stage("annotation", f"Downloading platform annotation {platform_id}")
        gpl_soft = _download_platform_soft(platform_id, raw_dir, progress)
        if progress is not None:
            progress.stage("platform", f"Parsing platform {platform_id}")
        return build_platform_cache(
            series_path=_series_file(dataset_path, metadata["accession"], raw_dir, progress),
            platform_id=platform_id,
            sample_ids=sample_ids,
            phenotype=phenotype,
            platform_index=platform_index,
            dataset_path=dataset_path,
            value_column=value_column,
            gpl_soft_path=gpl_soft,
            progress=progress,
        )


def _series_file(dataset_path: Path, accession: str, raw_dir: Path, progress: Any | None = None) -> Path:
    target = raw_dir / f"{accession}_family.soft.gz"
    if target.exists():
        return target
    return _download_soft(accession, raw_dir, progress)
