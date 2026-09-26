# GEOscope

GEOscope is a local web application for exploring gene expression datasets from
NCBI's [Gene Expression Omnibus](https://www.ncbi.nlm.nih.gov/geo/) (GEO) and
running non-parametric group comparisons for selected genes. It downloads a GEO
series, extracts sample phenotype metadata and platform annotations, and presents
the whole workflow in a browser UI — no R or Quarto needed at runtime.

The analysis pipeline mirrors the workflow in `paridhi_TALL_GSEIDs_Notebook.qmd`.

## Features

- **Load any GEO series** by accession (for example `GSE48558`). Series metadata
  is read from NCBI E-utilities, expression data from the series SOFT family file.
- **Multi-platform support** with selection of the platform, gene assignment
  column, and expression value column.
- **Sample and group selection** driven by phenotype fields from the series.
- **Gene selection** with search across all annotated gene symbols.
- **Statistics** per gene:
  - Two groups: two-sided Wilcoxon rank-sum (Mann-Whitney U).
  - Three or more groups: Kruskal-Wallis omnibus plus pairwise Wilcoxon
    rank-sum tests with Benjamini-Hochberg FDR correction.
- **Plots** rendered as violin/box plots with six built-in palettes, including a
  colorblind-safe option and custom colors.
- **Exports**: CSV, TSV, XLSX, a PDF report, and PNG/SVG charts.
- **Local caching** of datasets, platform matrices, and analyses as Parquet, plus
  a storage page to review and delete cached datasets.
- **Private by design**: the server binds to `127.0.0.1` on a random port and the
  only network traffic is to NCBI.

## Requirements

- Python 3.10 or newer (source install) — or a packaged executable
- Internet access to `ftp.ncbi.nlm.nih.gov` and `eutils.ncbi.nlm.nih.gov`

## Quick start

```bash
git clone https://github.com/f1-surya/geoscope.git
cd geoscope
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/geoscope
```

On Windows use `.venv\Scripts\python.exe` and `.venv\Scripts\geoscope.exe`.

GEOscope starts a local server, prints the URL, and opens it in your default
browser. Use the **Quit** link or `Ctrl+C` in the terminal to stop it.

## Usage

1. Enter a GEO series accession on the home page and select **Start analysis**.
2. **Dataset** — select **Load dataset** to download and cache the series, then
   choose a platform. If the platform offers several annotation or numeric
   columns, pick the gene assignment and expression value columns.
3. **Samples** — choose a phenotype field, then include or exclude individual
   samples to define the comparison groups.
4. **Genes** — search for and select one or more genes to analyze.
5. **Analysis** — pick a chart palette and run the analysis.
6. **Results** — review p-values, group summaries, and pairwise comparisons,
   refine the chart palette, and download tables, charts, or a PDF report.

Previous analyses are listed on the home page and can be reopened at any time.

## Data locations

All state lives in a per-user application-data directory:

| Platform | Location |
| --- | --- |
| Linux | `~/.local/share/GEOscope` (or `$XDG_DATA_HOME/GEOscope`) |
| macOS | `~/Library/Application Support/GEOscope` |
| Windows | `%LOCALAPPDATA%\GEOscope` |

Set `GEOSCOPE_DATA_DIR` to override the location. The directory contains the
SQLite database, cached `datasets/`, generated `analyses/`, downloaded `raw/`
files, `artifacts/`, and `logs/` (including a log of every run).

Optional: set `GEOSCOPE_EMAIL` to your email address so NCBI can contact you if
your request volume is unusually high.

## Supported datasets

GEOscope works with series that embed per-sample expression tables in the SOFT
family file. Series distributed only as supplementary files (for example, raw
count matrices or Excel workbooks) are not supported and are reported as such
after download.

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
```

Tests live in `tests/` and cover parsing, statistics, storage, paths, logging,
and the HTTP API. No formatter or linter is configured; match the surrounding
style and avoid unrelated reformatting.

## Building a native executable

Build on the target operating system; Python executables are not portable
between operating systems.

```bash
python -m pip install -e '.[build]'
pyinstaller build/geoscope.spec
```

The `build` GitHub Actions workflow runs the test suite and produces packaged
artifacts for Linux, Windows, and macOS.

## License

GEOscope is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

GEOscope is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the [LICENSE](LICENSE) file for details.

Copyright (C) 2026 Balasurya Ganesamoorthi