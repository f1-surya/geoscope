import pandas as pd
import pytest

from app.analysis.statistics import analyze
from app.geo.parsing import detect_assignment_column, parse_assignment, prepare_expression_data


def test_parse_assignment_matches_quarto_delimiters():
    assert parse_assignment("x // CD5 /// y // CD7") == ["CD5", "CD7"]
    assert parse_assignment("---") == []


def test_parse_assignment_handles_raw_array_symbols():
    assert parse_assignment("DDR1 /// MIR4640") == ["DDR1", "MIR4640"]
    assert parse_assignment("CD5") == ["CD5"]
    assert parse_assignment("NM_1 // CD5 // protein") == ["CD5"]
    assert parse_assignment("") == []
    assert parse_assignment(None) == []
    assert parse_assignment(float("nan")) == []


def test_detect_assignment_column_prefers_gene_assignment_then_symbol():
    assert detect_assignment_column(["ID", "gene_assignment", "Gene Symbol"]) == "gene_assignment"
    assert detect_assignment_column(["ID", "Gene Symbol", "Gene Title"]) == "Gene Symbol"
    assert detect_assignment_column(["ID", "Gene Title"]) is None


def test_prepare_expression_data_joins_metadata():
    expression = pd.DataFrame({"S1": [1.0, 2.0], "S2": [2.0, 4.0]}, index=["p1", "p2"])
    annotation = pd.DataFrame({"category": ["main", "main"], "gene_assignment": ["x // CD5", "x // CD7"]}, index=["p1", "p2"])
    phenotype = pd.DataFrame({"phenotype:ch1": ["A", "B"]}, index=["S1", "S2"])
    result = prepare_expression_data(expression, phenotype, annotation)
    assert set(result["gene_symbol"]) == {"CD5", "CD7"}
    assert set(result["sample"]) == {"S1", "S2"}
    assert len(result) == 4


def test_prepare_expression_data_uses_selected_assignment_column():
    expression = pd.DataFrame({"S1": [1.0]}, index=["p1"])
    annotation = pd.DataFrame({"probe_name": ["x // CD8"]}, index=["p1"])
    phenotype = pd.DataFrame(index=["S1"])
    result = prepare_expression_data(expression, phenotype, annotation, "probe_name")
    assert result.loc[0, "gene_symbol"] == "CD8"


def test_prepare_expression_data_filters_probes_before_melt():
    expression = pd.DataFrame({"S1": [1.0, 2.0], "S2": [2.0, 4.0]}, index=["p1", "p2"])
    annotation = pd.DataFrame(
        {"gene_assignment": ["x // CD5", "x // CD7"]},
        index=["p1", "p2"],
    )
    phenotype = pd.DataFrame(index=["S1", "S2"])

    result = prepare_expression_data(expression, phenotype, annotation, genes=["CD7"])

    assert len(result) == 2
    assert set(result["gene_symbol"]) == {"CD7"}
    assert set(result["probe_id"]) == {"p2"}


def test_prepare_expression_data_rejects_missing_assignment_column():
    expression = pd.DataFrame({"S1": [1.0]}, index=["p1"])
    annotation = pd.DataFrame({"probe_name": ["x // CD8"]}, index=["p1"])
    with pytest.raises(ValueError, match="gene_assignment"):
        prepare_expression_data(expression, pd.DataFrame(index=["S1"]), annotation)


def test_two_group_analysis_uses_rank_sum():
    data = pd.DataFrame({"gene_symbol": ["CD5"] * 6, "sample": list("ABCDEF"), "value": [1, 2, 2, 8, 9, 10], "group": ["A", "A", "A", "B", "B", "B"]})
    result = analyze(data, ["CD5"], "group")
    assert result["method"].startswith("Wilcoxon")
    assert result["pairwise"][0]["p_value"] < 1


def test_analysis_rejects_small_groups():
    data = pd.DataFrame({"gene_symbol": ["CD5", "CD5"], "sample": ["A", "B"], "value": [1, 2], "group": ["A", "B"]})
    with pytest.raises(ValueError, match="at least two"):
        analyze(data, ["CD5"], "group")
