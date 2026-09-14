from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

# PyInstaller windowed builds (Windows, and macOS .app) leave sys.stdout and
# sys.stderr as None. uvicorn and other libraries call sys.stdout.isatty(), so
# give the streams a real target before importing anything that might use them.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from .logging_config import configure_logging
from .paths import ensure_data_dirs

LOG_PATH = configure_logging(ensure_data_dirs()["logs"])
logger = logging.getLogger("geoscope")

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .analysis import analyze
from .export import export_report, export_table
from .geo.acquisition import load_dataset, load_dataset_info, load_platform, validate_accession
from .geo.parsing import assemble_long, build_mapping, clean_gene_values, detect_assignment_column
from .geo.soft import platform_cache_paths
from .plotting import PALETTES, create_plot
from .progress import progress_tracker
from .storage import Store

BASE = Path(__file__).parent
STATIC_DIR = (BASE / "static").resolve()
store = Store()
app = FastAPI(title="GEOscope", version="0.1.0")


class AnalysisRequest(BaseModel):
    accession: str
    platform_index: int = 0
    assignment_column: str = "gene_assignment"
    value_column: str | None = None
    genes: list[str] = Field(min_length=1)
    group_column: str
    selected_samples: list[str] = []
    palette: str = "Scientific"
    colors: list[str] | None = None


@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(BASE / "templates" / "index.html")


@app.get("/analysis/new", response_class=FileResponse)
def new_analysis_page():
    return FileResponse(BASE / "templates" / "new-analysis.html")


@app.get("/analysis/{analysis_id}", response_class=FileResponse)
def analysis_page(analysis_id: str):
    if not store.analysis(analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found")
    return FileResponse(BASE / "templates" / "analysis-detail.html")


@app.get("/static/{filename}")
def static_file(filename: str):
    candidate = (STATIC_DIR / filename).resolve()
    if candidate != STATIC_DIR and STATIC_DIR not in candidate.parents:
        raise HTTPException(status_code=404, detail="Not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(candidate)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/shutdown")
def shutdown(request: Request):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(status_code=403, detail="Shutdown is only available locally")
    server = getattr(app.state, "server", None)
    logger.info("Shutdown requested")
    if server is not None:
        server.should_exit = True
    return {"status": "stopping"}


@app.get("/api/history")
def history():
    return [dict(row) | {"config": json.loads(row["config"])} for row in store.analyses()]


@app.get("/api/palettes")
def palettes():
    return PALETTES


@app.get("/api/datasets/{accession}/info")
def dataset_info(accession: str):
    try:
        accession = validate_accession(accession)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return load_dataset_info(accession, store)


@app.get("/api/datasets/progress/{accession}")
def dataset_progress(accession: str):
    try:
        key = validate_accession(accession)
    except ValueError:
        key = accession.strip().upper()
    snapshot = progress_tracker.snapshot(key)
    return snapshot if snapshot else {"active": False, "done": True}


@app.post("/api/datasets/load")
def dataset_load(payload: dict):
    try:
        accession = validate_accession(payload.get("accession", ""))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reporter = progress_tracker.reporter(accession, accession)
    logger.info("Loading dataset %s", accession)
    try:
        result = load_dataset(accession, store, progress=reporter)
    except (ValueError, RuntimeError) as exc:
        logger.warning("Could not load dataset %s: %s", accession, exc)
        reporter.fail(str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error loading dataset %s", accession)
        reporter.fail(str(exc))
        raise
    reporter.succeed()
    return result


@app.get("/api/datasets/{accession}/platforms/{platform_index}")
def dataset_platform(accession: str, platform_index: int, assignment_column: str | None = None, value_column: str | None = None):
    try:
        accession = validate_accession(accession)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reporter = progress_tracker.reporter(accession, accession)
    logger.info("Preparing platform %s for %s", platform_index, accession)
    try:
        row = store.dataset(accession)
        if not row:
            raise ValueError("Load the dataset before selecting a platform.")
        dataset_path = Path(row["path"])
        meta = load_platform(dataset_path, platform_index, store.paths["raw"], value_column, progress=reporter)
        paths = platform_cache_paths(dataset_path, platform_index)
        available_columns = [column for column in meta.get("annotation_columns", []) if column != "probe_id"]
        selected_column = assignment_column or detect_assignment_column(available_columns)
        if selected_column is None or selected_column not in available_columns:
            if assignment_column is None:
                reporter.succeed()
                return {
                    "requires_annotation_column": True,
                    "annotation_columns": available_columns,
                }
            raise ValueError(f"Platform annotation has no '{selected_column}' gene assignment column")

        annotation = pd.read_parquet(paths["annotation"], columns=["probe_id", selected_column])
        mapped = build_mapping(annotation, selected_column)
        phenotype = pd.read_parquet(paths["phenotype"])
        samples = sorted(phenotype["sample"].dropna().astype(str).unique().tolist())
        phenotype_columns = [column for column in phenotype.columns if column not in ("sample", "geo_accession")]
        phenotype_records = json.loads(phenotype[["sample", *phenotype_columns]].to_json(orient="records"))
        genes = sorted(mapped["gene_symbol"].dropna().unique().tolist())
        reporter.succeed()
        return {
            "assignment_column": selected_column,
            "annotation_columns": available_columns,
            "samples": samples,
            "phenotype_fields": phenotype_columns,
            "phenotype_values": phenotype_records,
            "genes": genes,
            "rows": len(mapped) * len(samples),
            "value_column": meta.get("value_column"),
            "value_columns": meta.get("value_columns", []),
        }
    except Exception as exc:
        logger.exception("Could not prepare platform %s for %s", platform_index, accession)
        reporter.fail(str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyses")
def create_analysis(request: AnalysisRequest):
    try:
        accession = validate_accession(request.accession)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reporter = progress_tracker.reporter(accession, accession)
    logger.info(
        "Starting analysis for %s: genes=%s group=%s samples=%s",
        accession,
        request.genes,
        request.group_column,
        len(request.selected_samples),
    )
    try:
        reporter.stage("prepare", "Loading selected expression data")
        row = store.dataset(accession)
        if not row:
            raise ValueError("Load the dataset before starting an analysis.")
        dataset_path = Path(row["path"])
        meta = load_platform(dataset_path, request.platform_index, store.paths["raw"], request.value_column)
        paths = platform_cache_paths(dataset_path, request.platform_index)
        annotation = pd.read_parquet(paths["annotation"], columns=["probe_id", request.assignment_column])
        mapped = build_mapping(annotation, request.assignment_column, request.genes)
        if mapped.empty:
            raise ValueError("No probes map to the selected genes.")
        probe_ids = mapped["probe_id"].dropna().unique().tolist()
        # Row-group statistics on the probe-sorted expression cache let Parquet
        # skip unrelated probes instead of loading the whole matrix.
        expression = pd.read_parquet(paths["expression"], filters=[("probe_id", "in", probe_ids)])
        phenotype = pd.read_parquet(paths["phenotype"])
        data = assemble_long(expression, mapped, phenotype, meta.get("layout", "wide"))
        data = clean_gene_values(data, request.genes)
        reporter.stage("analysis", "Running statistical tests")
        result = analyze(data, request.genes, request.group_column, request.selected_samples or None, progress=reporter)
        analysis_id = uuid.uuid4().hex
        result_dir = store.paths["analyses"] / analysis_id
        result_dir.mkdir(parents=True, exist_ok=True)
        result["data"].to_parquet(result_dir / "observations.parquet", index=False)
        result_json = {key: value for key, value in result.items() if key != "data"}
        (result_dir / "results.json").write_text(json.dumps(result_json, default=str), encoding="utf-8")
        palette = request.colors or PALETTES.get(request.palette, PALETTES["Scientific"])
        groups = list(data[request.group_column].astype(str).dropna().unique())
        plot_path = result_dir / "plot.png"
        reporter.stage("plot", "Rendering chart")
        create_plot(result["data"], request.group_column, palette, plot_path, f"{accession} | {', '.join(request.genes)}", groups)
        config = request.model_dump() | {"method": result["method"], "plot": str(plot_path), "groups": groups, "colors": palette}
        store.save_analysis(analysis_id, accession, config, result_dir)
        reporter.succeed()
        logger.info("Completed analysis %s for %s using %s", analysis_id, accession, result["method"])
        return {"id": analysis_id, "method": result["method"], "results": result_json["results"], "pairwise": result_json["pairwise"], "plot": f"/api/analyses/{analysis_id}/plot"}
    except Exception as exc:
        logger.exception("Analysis failed for %s", accession)
        reporter.fail(str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/analyses/{analysis_id}/plot")
def analysis_plot(analysis_id: str):
    row = store.analysis(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return FileResponse(Path(row["result_path"]) / "plot.png")


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str):
    row = store.analysis(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    result_path = Path(row["result_path"])
    result_file = result_path / "results.json"
    results = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {"results": [], "pairwise": []}
    config = json.loads(row["config"])
    if not config.get("groups") or not config.get("colors"):
        observations = pd.read_parquet(result_path / "observations.parquet")
        groups = list(observations[config["group_column"]].astype(str).dropna().unique())
        config["groups"] = config.get("groups") or groups
        config["colors"] = config.get("colors") or PALETTES.get(config.get("palette", "Scientific"), PALETTES["Scientific"])
    return {
        "id": analysis_id,
        "config": config,
        "results": results.get("results", []),
        "pairwise": results.get("pairwise", []),
        "method": results.get("method"),
        "plot": f"/api/analyses/{analysis_id}/plot",
    }


@app.patch("/api/analyses/{analysis_id}/chart")
def update_chart(analysis_id: str, payload: dict):
    row = store.analysis(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    config = json.loads(row["config"])
    palette = payload.get("colors") or PALETTES.get(payload.get("palette", "Scientific"), PALETTES["Scientific"])
    result_dir = Path(row["result_path"])
    data = pd.read_parquet(result_dir / "observations.parquet")
    create_plot(data, config["group_column"], palette, result_dir / "plot.png", f"{config['accession']} | {', '.join(config['genes'])}", config.get("groups"))
    config["palette"] = payload.get("palette", config.get("palette", "Scientific"))
    config["colors"] = payload.get("colors")
    store.update_analysis_config(analysis_id, config)
    return {"plot": f"/api/analyses/{analysis_id}/plot?refresh=1"}


@app.get("/api/analyses/{analysis_id}/export/{format_name}")
def analysis_export(analysis_id: str, format_name: str):
    row = store.analysis(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    result_dir = Path(row["result_path"])
    try:
        data = pd.read_parquet(result_dir / "observations.parquet")
        if format_name in {"csv", "tsv", "xlsx"}:
            target = result_dir / f"results.{format_name}"
            export_table(data, target, format_name)
        elif format_name == "pdf":
            target = result_dir / "report.pdf"
            export_report(target, json.loads(row["config"]), data, result_dir / "plot.png")
        elif format_name in {"png", "svg"}:
            target = result_dir / f"plot.{format_name}"
            if format_name == "png":
                target.write_bytes((result_dir / "plot.png").read_bytes())
            else:
                config = json.loads(row["config"])
                create_plot(data, config["group_column"], config.get("colors") or PALETTES[config.get("palette", "Scientific")], target, config["accession"])
        else:
            raise HTTPException(status_code=400, detail="Unsupported export format")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Export %s failed for analysis %s", format_name, analysis_id)
        raise HTTPException(status_code=400, detail=f"Export failed: {exc}") from exc
    return FileResponse(target, filename=target.name)


def _clean_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    return env


def _notify(message: str) -> None:
    """Show a message box on Windows, where a windowed build has no console."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "GEOscope", 0x40)
    except Exception:
        logger.debug("Could not display message box", exc_info=True)


def _open_browser(url: str) -> bool:
    if sys.platform == "win32":
        try:
            os.startfile(url)
            logger.info("Opened browser via os.startfile")
            return True
        except OSError:
            logger.warning("os.startfile failed for %s", url, exc_info=True)
            if webbrowser.open(url):
                return True
            _notify(f"GEOscope is running, but the browser did not open automatically.\n\nOpen {url} manually.")
            return False
    command = ["open", url] if sys.platform == "darwin" else ["xdg-open", url]
    if shutil.which(command[0]):
        try:
            subprocess.Popen(
                command,
                env=_clean_subprocess_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Opened browser via %s", command[0])
            return True
        except OSError:
            logger.warning("Could not launch %s", command[0], exc_info=True)
    return webbrowser.open(url)


def _announce(url: str) -> None:
    print()
    print(f"GEOscope {app.version}")
    print(f"  Web UI   {url}")
    print(f"  Data dir {store.paths['root']}")
    print(f"  Log file {LOG_PATH}")
    print("  Stop     Press Ctrl+C")
    print()


def run() -> None:
    import signal

    logger.info(
        "GEOscope %s starting (frozen=%s, python=%s, platform=%s)",
        app.version,
        getattr(sys, "frozen", False),
        sys.version.split()[0],
        sys.platform,
    )
    logger.info("Data directory: %s", store.paths["root"])
    logger.info("Log file: %s", LOG_PATH)

    # log_config=None keeps uvicorn from installing its own stderr-only handlers
    # (and from calling sys.stdout.isatty()), so all logs reach our file handler.
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)
    app.state.server = server

    def request_shutdown(signum, frame):
        logger.info("Received signal %s, shutting down", signum)
        server.should_exit = True

    previous_handlers: list[tuple[int, object]] = []
    for signum in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if signum is None:
            continue
        try:
            previous_handlers.append((signum, signal.getsignal(signum)))
            signal.signal(signum, request_shutdown)
        except (ValueError, OSError):
            pass

    print("Starting GEOscope ...")
    thread = threading.Thread(target=server.run, name="geoscope-server", daemon=True)
    thread.start()

    while not server.started and thread.is_alive():
        thread.join(timeout=0.05)

    if not server.started:
        logger.error("GEOscope failed to start; see the log file for details")
        print("GEOscope failed to start.", file=sys.stderr)
        _notify(f"GEOscope failed to start.\n\nSee the log for details:\n{LOG_PATH}")
        return

    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    logger.info("Serving at %s", url)
    _announce(url)

    try:
        _open_browser(url)
    except Exception:
        logger.exception("Unexpected error opening the browser")

    try:
        while thread.is_alive():
            thread.join(timeout=0.2)
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")
        server.should_exit = True
    finally:
        server.should_exit = True
        thread.join()
        for signum, handler in previous_handlers:
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                pass
        logger.info("GEOscope stopped")
        print("GEOscope stopped.")


if __name__ == "__main__":
    run()
