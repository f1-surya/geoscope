# Repository Guidelines

## Project Structure & Module Organization

`app/` contains the FastAPI application. Keep HTTP entry points in `app/main.py` and supporting concerns in focused modules: GEO download/parsing in `app/geo/`, statistical analysis in `app/analysis/`, plotting in `app/plotting.py`, exports in `app/export.py`, and persistence/path handling in `app/storage.py` and `app/paths.py`. Browser assets live in `app/static/`; Jinja templates live in `app/templates/`. Put automated tests in `tests/`, mirroring the area under test (for example, `tests/test_platform_loading.py`). `build/geoscope.spec` defines the PyInstaller package, while the `.qmd` notebook is a reference for the analysis workflow.

## Build, Test, and Development Commands

Create an isolated environment and install development dependencies:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/geoscope
```

`pytest` runs the test suite; `geoscope` starts the local application. To produce a native executable on the current operating system, install `.[build]` and run `pyinstaller build/geoscope.spec`.

## Coding Style & Naming Conventions

Use Python 3.10+ and four-space indentation. Follow existing Python conventions: `snake_case` for functions, modules, and variables; `PascalCase` for classes; and concise, descriptive test names beginning with `test_`. Prefer small functions with explicit inputs and return values, particularly around data parsing and analysis. No formatter or linter is currently configured; preserve the surrounding style and avoid unrelated reformatting. Keep JavaScript and CSS changes scoped to the relevant files in `app/static/`.

## Testing Guidelines

Write pytest tests for changed behavior and regression cases. Use `tmp_path` for filesystem fixtures and small in-memory pandas DataFrames or compact SOFT samples for data-processing tests. Test observable results and validation errors; run `.venv/bin/pytest` before submitting.

## Commit & Pull Request Guidelines

The available history uses short, imperative summaries (for example, `Init`); follow that pattern, such as `Add platform cache validation`. Keep commits focused. Pull requests should describe the behavior change, list tests run, link relevant issues, and include screenshots for changes to templates, JavaScript, or CSS.

## Configuration & Data

Do not commit downloaded GEO data, generated Parquet files, SQLite databases, or user-specific application data. The application stores these artifacts in the platform-specific per-user data directory and binds locally by design.
