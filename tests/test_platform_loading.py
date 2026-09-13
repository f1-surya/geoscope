import gzip
import json

import pandas as pd

from app.geo.soft import build_platform_cache, platform_cache_paths, read_series_metadata


def _write_soft(path, text):
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)


GEOQUERY_SERIES = """^DATABASE = GeoMiame
!Database_name = GEO
^SERIES = GSE_TEST
!Series_title = Test series
!Series_geo_accession = GSE_TEST
!Series_sample_id = GSM1
!Series_sample_id = GSM2
^PLATFORM = GPL1
!Platform_title = GEOquery style platform
!platform_table_begin
ID\tGB_ACC\tgene_assignment\tcategory
p1\tNM_1\tx // CD5\ty\tmain
p2\tNM_2\tx // CD7\ty\tmain
p3\tNM_3\t---\ty\tcontrol
!platform_table_end
^SAMPLE = GSM1
!Sample_title = sample one
!Sample_platform_id = GPL1
!sample_table_begin
ID_REF\tVALUE
p1\t1.5
p2\t2.5
p3\t3.5
!sample_table_end
^SAMPLE = GSM2
!Sample_title = sample two
!Sample_platform_id = GPL1
!sample_table_begin
ID_REF\tVALUE
p1\t4.0
p2\t5.0
p3\t6.0
!sample_table_end
"""

AFFY_SERIES = """^SERIES = GSE_AFFY
!Series_title = Affy series
!Series_geo_accession = GSE_AFFY
^PLATFORM = GPL2
!Platform_title = Affymetrix platform
!platform_table_begin
ID\tGene Symbol\tGene Title
p1\tCD5 /// CD7\tsome title
p2\tCD8\tsome title
!platform_table_end
^SAMPLE = GSM3
!Sample_title = affy sample
!Sample_platform_id = GPL2
!sample_table_begin
ID_REF\tVALUE_DS\tDETECTION P-VALUE\tVALUE
p1\t99.0\t0.01\t1.5
p2\t88.0\t0.02\t2.5
!sample_table_end
"""

MULTI_PLATFORM_SERIES = """^SERIES = GSE_MULTI
!Series_title = Multi platform
!Series_geo_accession = GSE_MULTI
^PLATFORM = GPLA
!platform_table_begin
ID\tgene_assignment
a1\tx // AAA
a2\tx // BBB
!platform_table_end
^PLATFORM = GPLB
!platform_table_begin
ID\tgene_assignment
b1\tx // CCC
b2\tx // DDD
!platform_table_end
^SAMPLE = GSMA
!Sample_platform_id = GPLA
!sample_table_begin
ID_REF\tVALUE
a1\t1.0
a2\t2.0
!sample_table_end
^SAMPLE = GSMB
!Sample_platform_id = GPLB
!sample_table_begin
ID_REF\tVALUE
b1\t3.0
b2\t4.0
!sample_table_end
"""

MISSING_ANNOTATION_SERIES = """^SERIES = GSE_NOANN
!Series_title = No annotation
!Series_geo_accession = GSE_NOANN
^SAMPLE = GSMX
!Sample_platform_id = GPLX
!sample_table_begin
ID_REF\tVALUE
p1\t1.0
p2\t2.0
!sample_table_end
"""

GPLX_SOFT = """^PLATFORM = GPLX
!platform_table_begin
ID\tgene_assignment
p1\tx // GENE1
p2\tx // GENE2
!platform_table_end
"""


def test_read_series_metadata_streams_samples_and_platforms(tmp_path):
    soft = tmp_path / "GSE_TEST_family.soft.gz"
    _write_soft(soft, GEOQUERY_SERIES)

    info = read_series_metadata(soft, "GSE_TEST")

    assert info.title == "Test series"
    assert info.sample_ids == ["GSM1", "GSM2"]
    assert info.platforms == ["GPL1"]
    assert set(info.phenotype["title"]) == {"sample one", "sample two"}
    assert list(info.phenotype["sample"]) == ["GSM1", "GSM2"]


def test_build_platform_cache_geoquery_style(tmp_path):
    soft = tmp_path / "GSE_TEST_family.soft.gz"
    _write_soft(soft, GEOQUERY_SERIES)
    info = read_series_metadata(soft, "GSE_TEST")

    meta = build_platform_cache(soft, "GPL1", info.sample_ids, info.phenotype, 0, tmp_path)

    paths = platform_cache_paths(tmp_path, 0)
    expression = pd.read_parquet(paths["expression"])
    assert expression["probe_id"].tolist() == ["p1", "p2", "p3"]
    assert expression["GSM1"].tolist() == [1.5, 2.5, 3.5]
    assert expression["GSM2"].tolist() == [4.0, 5.0, 6.0]
    assert meta["layout"] == "wide"
    assert meta["value_column"] == "VALUE"

    annotation = pd.read_parquet(paths["annotation"])
    assert "gene_assignment" in annotation.columns
    assert "category" in annotation.columns


def test_build_platform_cache_prefers_value_and_parses_raw_symbols(tmp_path):
    soft = tmp_path / "GSE_AFFY_family.soft.gz"
    _write_soft(soft, AFFY_SERIES)
    info = read_series_metadata(soft, "GSE_AFFY")

    meta = build_platform_cache(soft, "GPL2", info.sample_ids, info.phenotype, 0, tmp_path)

    paths = platform_cache_paths(tmp_path, 0)
    expression = pd.read_parquet(paths["expression"])
    assert expression["GSM3"].tolist() == [1.5, 2.5]
    assert meta["value_column"] == "VALUE"
    assert "VALUE_DS" in meta["value_columns"]

    annotation = pd.read_parquet(paths["annotation"])
    assert "Gene Symbol" in annotation.columns


def test_build_platform_cache_selects_only_target_platform_samples(tmp_path):
    soft = tmp_path / "GSE_MULTI_family.soft.gz"
    _write_soft(soft, MULTI_PLATFORM_SERIES)
    info = read_series_metadata(soft, "GSE_MULTI")

    meta = build_platform_cache(soft, "GPLB", ["GSMB"], info.phenotype, 1, tmp_path)

    paths = platform_cache_paths(tmp_path, 1)
    expression = pd.read_parquet(paths["expression"])
    assert expression["probe_id"].tolist() == ["b1", "b2"]
    assert "GSMB" in expression.columns
    assert "GSMA" not in expression.columns
    assert meta["probe_count"] == 2


def test_missing_annotation_uses_downloaded_platform(tmp_path):
    soft = tmp_path / "GSE_NOANN_family.soft.gz"
    _write_soft(soft, MISSING_ANNOTATION_SERIES)
    gpl = tmp_path / "GPLX_family.soft.gz"
    _write_soft(gpl, GPLX_SOFT)
    info = read_series_metadata(soft, "GSE_NOANN")

    meta = build_platform_cache(soft, "GPLX", info.sample_ids, info.phenotype, 0, tmp_path, gpl_soft_path=gpl)

    paths = platform_cache_paths(tmp_path, 0)
    expression = pd.read_parquet(paths["expression"])
    assert expression["GSMX"].tolist() == [1.0, 2.0]
    annotation = pd.read_parquet(paths["annotation"])
    assert "gene_assignment" in annotation.columns
    assert meta["probe_count"] == 2


def test_build_platform_cache_requires_annotation(tmp_path):
    soft = tmp_path / "GSE_NOANN_family.soft.gz"
    _write_soft(soft, MISSING_ANNOTATION_SERIES)
    info = read_series_metadata(soft, "GSE_NOANN")

    try:
        build_platform_cache(soft, "GPLX", info.sample_ids, info.phenotype, 0, tmp_path)
    except ValueError as exc:
        assert "does not embed annotation" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cache_meta_records_schema(tmp_path):
    soft = tmp_path / "GSE_TEST_family.soft.gz"
    _write_soft(soft, GEOQUERY_SERIES)
    info = read_series_metadata(soft, "GSE_TEST")

    build_platform_cache(soft, "GPL1", info.sample_ids, info.phenotype, 0, tmp_path)
    meta = json.loads((tmp_path / "platform-0-meta.json").read_text())
    assert meta["probe_count"] == 3
    assert meta["sample_count"] == 2
    assert "probe_id" in meta["annotation_columns"]


class _Recorder:
    def __init__(self):
        self.fractions = []
        self.infos = []

    def stage(self, *args, **kwargs):
        pass

    def bytes(self, *args, **kwargs):
        pass

    def fraction(self, value, detail=None):
        self.fractions.append(value)

    def info(self, **fields):
        self.infos.append(fields)


def test_read_series_metadata_reports_progress(tmp_path):
    soft = tmp_path / "GSE_TEST_family.soft.gz"
    _write_soft(soft, GEOQUERY_SERIES)
    recorder = _Recorder()

    read_series_metadata(soft, "GSE_TEST", progress=recorder)

    assert recorder.fractions[-1] == 1.0
    assert any("title" in info for info in recorder.infos)


def test_build_platform_cache_reports_sample_progress(tmp_path):
    soft = tmp_path / "GSE_TEST_family.soft.gz"
    _write_soft(soft, GEOQUERY_SERIES)
    info = read_series_metadata(soft, "GSE_TEST")
    recorder = _Recorder()

    build_platform_cache(soft, "GPL1", info.sample_ids, info.phenotype, 0, tmp_path, progress=recorder)

    assert recorder.fractions[-1] == 1.0
    assert any(info.get("probe_count") == 3 for info in recorder.infos)

