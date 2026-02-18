import base64

import pandas as pd
import pytest

from testgen.ui.views.dialogs.import_metadata_dialog import (
    DESCRIPTION_MAX_LENGTH,
    TAG_MAX_LENGTH,
    _build_preview_props,
    _extract_metadata_fields,
    _parse_csv,
    _set_row_status,
    _truncate_fields,
)

pytestmark = pytest.mark.unit


def _make_base64_csv(csv_text: str) -> str:
    encoded = base64.b64encode(csv_text.encode()).decode()
    return f"data:text/csv;base64,{encoded}"


def _make_series(data: dict) -> pd.Series:
    return pd.Series(data)


# --- _parse_csv ---


def test_parse_csv_basic_table_and_column():
    content = _make_base64_csv("Table,Column,Description\nmy_table,,Table desc\nmy_table,col1,Col desc\n")
    result = _parse_csv(content)
    assert "error" not in result
    df = result["df"]
    assert len(df) == 2
    assert list(df["table_name"]) == ["my_table", "my_table"]
    assert list(df["column_name"]) == ["", "col1"]


def test_parse_csv_missing_table_column():
    content = _make_base64_csv("Column,Description\ncol1,desc\n")
    result = _parse_csv(content)
    assert result["error"] == "CSV must contain a 'Table' column."


def test_parse_csv_empty():
    content = _make_base64_csv("Table,Column\n")
    result = _parse_csv(content)
    assert result["error"] == "CSV file is empty."


def test_parse_csv_invalid_base64():
    result = _parse_csv("data:text/csv;base64,!!!invalid!!!")
    assert "error" in result
    assert "Could not parse CSV file" in result["error"]


def test_parse_csv_header_normalization_underscores():
    content = _make_base64_csv("Table,Critical_Data_Element\nmy_table,Yes\n")
    result = _parse_csv(content)
    assert "error" not in result
    assert "critical_data_element" in result["df"].columns


def test_parse_csv_header_normalization_spaces():
    content = _make_base64_csv("Table,Critical Data Element\nmy_table,Yes\n")
    result = _parse_csv(content)
    assert "error" not in result
    assert "critical_data_element" in result["df"].columns


def test_parse_csv_header_cde_alias():
    content = _make_base64_csv("Table,CDE\nmy_table,Yes\n")
    result = _parse_csv(content)
    assert "error" not in result
    assert "critical_data_element" in result["df"].columns


def test_parse_csv_header_case_insensitive():
    content = _make_base64_csv("TABLE,DESCRIPTION\nmy_table,desc\n")
    result = _parse_csv(content)
    assert "error" not in result
    assert "description" in result["df"].columns


def test_parse_csv_extra_columns_ignored():
    content = _make_base64_csv("Table,Description,UnknownCol\nmy_table,desc,ignored\n")
    result = _parse_csv(content)
    assert "error" not in result
    assert "UnknownCol" not in result["df"].columns


def test_parse_csv_whitespace_stripped():
    content = _make_base64_csv("Table,Description\n  my_table  ,  desc  \n")
    result = _parse_csv(content)
    df = result["df"]
    assert df.iloc[0]["table_name"] == "my_table"
    assert df.iloc[0]["description"] == "desc"


def test_parse_csv_duplicate_table_rows():
    content = _make_base64_csv("Table,Description\nmy_table,first\nmy_table,second\n")
    result = _parse_csv(content)
    assert len(result["duplicate_rows"]) == 1
    assert len(result["df"]) == 1
    assert result["df"].iloc[0]["description"] == "second"


def test_parse_csv_duplicate_column_rows():
    content = _make_base64_csv("Table,Column,Description\nt,c,first\nt,c,second\n")
    result = _parse_csv(content)
    assert len(result["duplicate_rows"]) == 1
    assert result["df"].iloc[0]["description"] == "second"


def test_parse_csv_no_column_header_adds_empty():
    content = _make_base64_csv("Table,Description\nmy_table,desc\n")
    result = _parse_csv(content)
    assert "column_name" in result["df"].columns
    assert result["df"].iloc[0]["column_name"] == ""


# --- _extract_metadata_fields ---


@pytest.mark.parametrize("val", ["Yes", "yes", "Y", "y", "True", "true", "1"])
def test_extract_cde_true_values(val):
    fields, bad_cde = _extract_metadata_fields(_make_series({"critical_data_element": val}), "keep")
    assert fields["critical_data_element"] is True
    assert bad_cde == 0


@pytest.mark.parametrize("val", ["No", "no", "N", "n", "False", "false", "0"])
def test_extract_cde_false_values(val):
    fields, bad_cde = _extract_metadata_fields(_make_series({"critical_data_element": val}), "keep")
    assert fields["critical_data_element"] is False
    assert bad_cde == 0


def test_extract_cde_blank_keep():
    fields, bad_cde = _extract_metadata_fields(_make_series({"critical_data_element": ""}), "keep")
    assert "critical_data_element" not in fields
    assert bad_cde == 0


def test_extract_cde_blank_clear():
    fields, bad_cde = _extract_metadata_fields(_make_series({"critical_data_element": ""}), "clear")
    assert fields["critical_data_element"] is None
    assert bad_cde == 0


def test_extract_cde_unrecognized():
    fields, bad_cde = _extract_metadata_fields(_make_series({"critical_data_element": "Maybe"}), "keep")
    assert "critical_data_element" not in fields
    assert bad_cde == 1


def test_extract_text_field_with_value():
    fields, _ = _extract_metadata_fields(_make_series({"description": "test desc"}), "keep")
    assert fields["description"] == "test desc"


def test_extract_text_field_blank_keep():
    fields, _ = _extract_metadata_fields(_make_series({"description": ""}), "keep")
    assert "description" not in fields


def test_extract_text_field_blank_clear():
    fields, _ = _extract_metadata_fields(_make_series({"description": ""}), "clear")
    assert fields["description"] == ""


def test_extract_missing_column_skipped():
    fields, _ = _extract_metadata_fields(_make_series({"description": "test"}), "keep")
    assert "data_source" not in fields


def test_extract_tag_field_with_value():
    fields, _ = _extract_metadata_fields(_make_series({"data_source": "ERP"}), "keep")
    assert fields["data_source"] == "ERP"


# --- _truncate_fields ---


def test_truncate_no_truncation_needed():
    fields = {"description": "short", "data_source": "ERP"}
    result, truncated = _truncate_fields(fields)
    assert truncated == []
    assert result["description"] == "short"


def test_truncate_tag_at_max():
    fields = {"data_source": "x" * (TAG_MAX_LENGTH + 10)}
    result, truncated = _truncate_fields(fields)
    assert truncated == ["data_source"]
    assert len(result["data_source"]) == TAG_MAX_LENGTH


def test_truncate_description_at_max():
    fields = {"description": "x" * (DESCRIPTION_MAX_LENGTH + 10)}
    result, truncated = _truncate_fields(fields)
    assert truncated == ["description"]
    assert len(result["description"]) == DESCRIPTION_MAX_LENGTH


def test_truncate_boolean_fields_skipped():
    fields = {"critical_data_element": True}
    result, truncated = _truncate_fields(fields)
    assert truncated == []
    assert result["critical_data_element"] is True


def test_truncate_multiple_fields():
    fields = {"data_source": "x" * 50, "source_system": "y" * 50}
    _, truncated = _truncate_fields(fields)
    assert "data_source" in truncated
    assert "source_system" in truncated


# --- _set_row_status ---


def test_set_row_status_ok():
    row = {}
    _set_row_status(row, bad_cde=0, truncated=[])
    assert row["_status"] == "ok"
    assert row["_status_detail"] == ""
    assert row["_truncated_fields"] == []


def test_set_row_status_error_bad_cde():
    row = {}
    _set_row_status(row, bad_cde=1, truncated=[])
    assert row["_status"] == "error"
    assert "Unrecognized CDE" in row["_status_detail"]


def test_set_row_status_warning_truncated():
    row = {}
    _set_row_status(row, bad_cde=0, truncated=["data_source"])
    assert row["_status"] == "warning"
    assert "truncated" in row["_status_detail"]
    assert "data_source" in row["_status_detail"]


def test_set_row_status_error_precedence():
    row = {}
    _set_row_status(row, bad_cde=1, truncated=["data_source"])
    assert row["_status"] == "error"
    assert "CDE" in row["_status_detail"]
    assert "truncated" in row["_status_detail"]


# --- _build_preview_props ---


def test_preview_props_basic():
    preview = {
        "table_rows": [{"table_id": "1", "table_name": "t1", "description": "desc"}],
        "column_rows": [],
        "preview_rows": [
            {"table_name": "t1", "column_name": "", "description": "desc", "_status": "ok", "_status_detail": "", "_truncated_fields": []},
        ],
        "metadata_columns": ["description"],
    }
    result = _build_preview_props(preview)
    assert result["table_count"] == 1
    assert result["column_count"] == 0
    assert len(result["preview_rows"]) == 1
    assert result["preview_rows"][0]["description"] == "desc"


def test_preview_props_cde_true():
    preview = {
        "table_rows": [{"table_id": "1", "table_name": "t", "critical_data_element": True}],
        "column_rows": [],
        "preview_rows": [
            {"table_name": "t", "column_name": "", "critical_data_element": True, "_status": "ok", "_status_detail": "", "_truncated_fields": []},
        ],
        "metadata_columns": ["critical_data_element"],
    }
    result = _build_preview_props(preview)
    assert result["preview_rows"][0]["critical_data_element"] == "Yes"


def test_preview_props_cde_false():
    preview = {
        "table_rows": [{"table_id": "1", "table_name": "t", "critical_data_element": False}],
        "column_rows": [],
        "preview_rows": [
            {"table_name": "t", "column_name": "", "critical_data_element": False, "_status": "ok", "_status_detail": "", "_truncated_fields": []},
        ],
        "metadata_columns": ["critical_data_element"],
    }
    result = _build_preview_props(preview)
    assert result["preview_rows"][0]["critical_data_element"] == "No"


def test_preview_props_cde_none():
    preview = {
        "table_rows": [],
        "column_rows": [],
        "preview_rows": [
            {"table_name": "t", "column_name": "", "critical_data_element": None, "_status": "ok", "_status_detail": "", "_truncated_fields": []},
        ],
        "metadata_columns": ["critical_data_element"],
    }
    result = _build_preview_props(preview)
    assert result["preview_rows"][0]["critical_data_element"] == ""


def test_preview_props_unmatched_preserved():
    preview = {
        "table_rows": [],
        "column_rows": [],
        "preview_rows": [
            {"table_name": "fake", "column_name": "", "_status": "unmatched", "_status_detail": "Table not found", "_truncated_fields": []},
        ],
        "metadata_columns": ["description"],
    }
    result = _build_preview_props(preview)
    assert result["preview_rows"][0]["_status"] == "unmatched"
