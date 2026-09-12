from __future__ import annotations

import json
import sys
import threading
import uuid
import webbrowser
from pathlib import Path

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .analysis import analyze
from .export import export_report, export_table
from .geo.acquisition import load_dataset, load_platform, validate_accession
from .geo.parsing import assemble_long, build_mapping, clean_gene_values, detect_assignment_column
from .geo.soft import platform_cache_paths
from .plotting import PALETTES, create_plot
from .storage import Store

BASE = Path(__file__).parent
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
    return FileResponse(BASE / "static" / filename)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/history")
def history():
    return [dict(row) | {"config": json.loads(row["config"])} for row in store.analyses()]


@app.get("/api/palettes")
def palettes():
    return PALETTES


@app.post("/api/datasets/load")
def dataset_load(payload: dict):
    try:
        return load_dataset(payload.get("accession", ""), store)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/datasets/{accession}/platforms/{platform_index}")
def dataset_platform(accession: str, platform_index: int, assignment_column: str | None = None, value_column: str | None = None):
    try:
        accession = validate_accession(accession)
        row = store.dataset(accession)
        if not row:
            raise ValueError("Load the dataset before selecting a platform.")
        dataset_path = Path(row["path"])
        meta = load_platform(dataset_path, platform_index, store.paths["raw"], value_column)
        paths = platform_cache_paths(dataset_path, platform_index)
        available_columns = [column for column in meta.get("annotation_columns", []) if column != "probe_id"]
        selected_column = assignment_column or detect_assignment_column(available_columns)
        if selected_column is None or selected_column not in available_columns:
            if assignment_column is None:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyses")
def create_analysis(request: AnalysisRequest):
    try:
        accession = validate_accession(request.accession)
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
        result = analyze(data, request.genes, request.group_column, request.selected_samples or None)
        analysis_id = uuid.uuid4().hex
        result_dir = store.paths["analyses"] / analysis_id
        result_dir.mkdir(parents=True, exist_ok=True)
        result["data"].to_parquet(result_dir / "observations.parquet", index=False)
        result_json = {key: value for key, value in result.items() if key != "data"}
        (result_dir / "results.json").write_text(json.dumps(result_json, default=str), encoding="utf-8")
        palette = request.colors or PALETTES.get(request.palette, PALETTES["Scientific"])
        groups = list(data[request.group_column].astype(str).dropna().unique())
        plot_path = result_dir / "plot.png"
        create_plot(result["data"], request.group_column, palette, plot_path, f"{accession} | {', '.join(request.genes)}", groups)
        config = request.model_dump() | {"method": result["method"], "plot": str(plot_path), "groups": groups, "colors": palette}
        store.save_analysis(analysis_id, accession, config, result_dir)
        return {"id": analysis_id, "method": result["method"], "results": result_json["results"], "pairwise": result_json["pairwise"], "plot": f"/api/analyses/{analysis_id}/plot"}
    except Exception as exc:
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
    return FileResponse(target, filename=target.name)


def _announce(url: str) -> None:
    print()
    print(f"GEOscope {app.version}")
    print(f"  Web UI   {url}")
    print(f"  Data dir {store.paths['root']}")
    print("  Stop     Press Ctrl+C")
    print()


def run() -> None:
    import signal

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)

    def request_shutdown(signum, frame):
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
        print("GEOscope failed to start.", file=sys.stderr)
        return

    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    _announce(url)

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        while thread.is_alive():
            thread.join(timeout=0.2)
    except KeyboardInterrupt:
        server.should_exit = True
    finally:
        server.should_exit = True
        thread.join()
        for signum, handler in previous_handlers:
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                pass
        print("GEOscope stopped.")


if __name__ == "__main__":
    run()
