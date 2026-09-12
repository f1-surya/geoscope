# GEOscope

GEOscope is a local FastAPI application for exploring GEO expression datasets and reproducing the analysis in `paridhi_TALL_GSEIDs_Notebook.qmd` without R or Quarto at runtime.

## Development

```text
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/geoscope
```

On Windows, use `.venv\\Scripts\\python.exe` and `.venv\\Scripts\\geoscope.exe`.

The application stores its SQLite database, dataset cache, Parquet tables, and generated artifacts in the platform's per-user application-data location. It binds only to localhost and opens the default browser automatically.

## Packaging

Build on the target operating system; native Python executables are not interchangeable between operating systems:

```text
python -m pip install -e '.[build]'
pyinstaller build/geoscope.spec
```

The GitHub Actions workflow builds independently on Linux, Windows, and macOS.
