import csv
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from testgen.common.test_definition_export_import_service import ImportPayload

pytestmark = pytest.mark.unit

SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "transfer_tests.py"
_spec = importlib.util.spec_from_file_location("transfer_tests", SCRIPT_PATH)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script
_spec.loader.exec_module(script)

MARKER = {"mapping_file": "mapping.csv", "mapped_at": "2026-10-05T00:00:00+00:00"}
GEN_DATE = "2026-09-30T12:00:00"


def _mapping(rows: str) -> Any:
    text = "source_table,source_column,target_table,target_column\n" + dedent(rows).strip() + "\n"
    return script.parse_mapping_rows(csv.DictReader(io.StringIO(text)))


def _test(test_type: str, table: str, column: str | None = None, **fields: Any) -> dict[str, Any]:
    definition: dict[str, Any] = {"test_type": test_type, "last_auto_gen_date": GEN_DATE, "table_name": table}
    if column is not None:
        definition["column_name"] = column
    return {**definition, **fields}


def _document(*definitions: dict[str, Any], **top: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "source": {
            "project_code": "DEFAULT",
            "test_suite": "source_suite",
            "table_group": "source_group",
            "table_group_schema": "src",
            "exported_at": "2026-10-01T00:00:00Z",
        },
        "definitions": list(definitions),
        **top,
    }


def _map(document: dict[str, Any], mapping: Any) -> tuple[dict[str, Any], Any]:
    return script.map_document(document, mapping, MARKER)


def _names(document: dict[str, Any]) -> list[tuple[str, str | None, str | None]]:
    return [(d["test_type"], d.get("table_name"), d.get("column_name")) for d in document["definitions"]]


def test_renames_tables_and_columns_and_copies_everything_else():
    source = _test(
        "Match_Max_Val", "orders", "amt",
        threshold_value="1999.99", skip_errors=3, severity="Warning", custom_metadata={"owner": "finance"},
    )
    document = _document(_test("Match_Row_Ct", "orders", threshold_value="120"), source)
    mapping = _mapping("""
        orders,,sales_orders,
        orders,amt,sales_orders,amount
    """)

    mapped, report = _map(document, mapping)

    assert _names(mapped) == [("Match_Row_Ct", "sales_orders", None), ("Match_Max_Val", "sales_orders", "amount")]
    assert mapped["definitions"][1] == {**source, "table_name": "sales_orders", "column_name": "amount"}
    assert list(mapped["definitions"][1]) == list(source)
    assert "column_name" not in mapped["definitions"][0]
    assert mapped["source"] == document["source"]
    assert report.table_renames == {("orders", "sales_orders"): 2}
    assert report.column_renames == {("orders.amt", "sales_orders.amount"): 1}


def test_does_not_modify_the_input_document():
    document = _document(_test("Match_Null_Ct", "orders", "amt"))
    original = json.loads(json.dumps(document))

    _map(document, _mapping("orders,amt,orders,amount"))

    assert document == original


def test_rules_are_keyed_on_source_names_and_never_chain():
    document = _document(_test("Match_Null_Ct", "t", "status"), _test("Match_Null_Ct", "t", "state"))
    mapping = _mapping("""
        t,status,t,state
        t,state,t,region
    """)

    mapped, _ = _map(document, mapping)

    assert _names(mapped) == [("Match_Null_Ct", "t", "state"), ("Match_Null_Ct", "t", "region")]


def test_column_without_a_row_follows_the_table_rename_and_is_reported():
    document = _document(_test("Match_Null_Ct", "orders", "id"), _test("Match_Null_Ct", "orders", "amt"))
    mapping = _mapping("""
        orders,,sales_orders,
        orders,amt,sales_orders,amount
    """)

    mapped, report = _map(document, mapping)

    assert _names(mapped) == [("Match_Null_Ct", "sales_orders", "id"), ("Match_Null_Ct", "sales_orders", "amount")]
    assert report.followed == {("orders", "sales_orders"): 1}
    assert report.kept == {}


def test_column_row_overrides_the_table_row_target():
    document = _document(_test("Match_Null_Ct", "orders", "note"))
    mapping = _mapping("""
        orders,,sales_orders,
        orders,note,order_notes,note
    """)

    mapped, _ = _map(document, mapping)

    assert _names(mapped) == [("Match_Null_Ct", "order_notes", "note")]


def test_table_drop_drops_only_table_level_tests():
    document = _document(
        _test("Match_Row_Ct", "audit"),
        _test("Match_Column_Ct", "audit"),
        _test("Match_Null_Ct", "audit", "id"),
    )

    mapped, report = _map(document, _mapping("audit,,DROP,"))

    assert _names(mapped) == [("Match_Null_Ct", "audit", "id")]
    assert [test.reason for test in report.dropped] == ["audit mapped to DROP"] * 2


def test_table_drop_all_drops_every_test_on_the_table():
    document = _document(
        _test("Match_Row_Ct", "tmp"),
        _test("Match_Null_Ct", "tmp", "id"),
        _test("Match_Null_Ct", "keep", "id"),
    )

    mapped, report = _map(document, _mapping("tmp,,DROP_ALL,"))

    assert _names(mapped) == [("Match_Null_Ct", "keep", "id")]
    assert len(report.dropped) == 2


def test_column_drop_drops_its_tests_and_the_tables_column_count():
    document = _document(
        _test("Match_Row_Ct", "orders"),
        _test("Match_Column_Ct", "orders"),
        _test("Match_Column_Ct", "customers"),
        _test("Match_Null_Ct", "orders", "legacy"),
        _test("Match_Null_Ct", "orders", "id"),
    )

    mapped, report = _map(document, _mapping("orders,legacy,,DROP"))

    assert _names(mapped) == [
        ("Match_Row_Ct", "orders", None),
        ("Match_Column_Ct", "customers", None),
        ("Match_Null_Ct", "orders", "id"),
    ]
    assert [(test.test_type, test.reason) for test in report.dropped] == [
        ("Match_Column_Ct", "a column of orders is dropped, so the column count no longer matches"),
        ("Match_Null_Ct", "orders.legacy mapped to DROP"),
    ]
    assert report.unmatched_rows == []


def test_keyed_hash_key_column_is_renamed():
    document = _document(_test("Match_Keyed_Hash_Text", "orders", "name", groupby_names="order_id"))
    mapping = _mapping("""
        orders,name,sales_orders,customer_name
        orders,order_id,sales_orders,id
    """)

    mapped, report = _map(document, mapping)

    assert mapped["definitions"][0]["groupby_names"] == "id"
    assert mapped["definitions"][0]["table_name"] == "sales_orders"
    assert report.column_renames[("orders.order_id", "sales_orders.id")] == 1


def test_keyed_hash_is_dropped_with_its_key_column():
    document = _document(
        _test("Match_Keyed_Hash_Num", "orders", "amt", groupby_names="order_id"),
        _test("Match_Null_Ct", "orders", "amt"),
    )

    mapped, report = _map(document, _mapping("orders,order_id,,DROP"))

    assert _names(mapped) == [("Match_Null_Ct", "orders", "amt")]
    assert report.dropped[0].reason == "key column orders.order_id mapped to DROP"


def test_refuses_a_key_column_mapped_to_another_table():
    document = _document(_test("Match_Keyed_Hash_Num", "orders", "amt", groupby_names="order_id"))
    mapping = _mapping("""
        orders,amt,sales,amt
        orders,order_id,order_keys,order_id
    """)

    with pytest.raises(script.MappingRefused, match="maps to table order_keys"):
        _map(document, mapping)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subset_condition", "amt > 0"),
        ("having_condition", "COUNT(*) > 1"),
        ("custom_query", "SELECT 1"),
        ("window_date_column", "order_date"),
        ("match_table_name", "other"),
        ("match_column_names", "id"),
        ("groupby_names", "region"),
    ],
)
def test_refuses_fields_it_cannot_rewrite(field, value):
    document = _document(_test("Match_Null_Ct", "orders", "amt"), _test("Combo_Match", "orders", "id", **{field: value}))

    with pytest.raises(script.MappingRefused, match=rf"test 1 \(Combo_Match on orders.id\): {field}"):
        _map(document, _mapping("orders,,orders2,"))


@pytest.mark.parametrize("key", ["a, b", '"order_id"', "LOWER(id)", " id"])
def test_refuses_a_keyed_hash_key_that_is_not_a_plain_name(key):
    document = _document(_test("Match_Keyed_Hash_Text", "orders", "name", groupby_names=key))

    with pytest.raises(script.MappingRefused, match="groupby_names"):
        _map(document, _mapping("orders,,orders2,"))


def test_blank_unrewritable_fields_are_allowed():
    document = _document(_test("Match_Null_Ct", "orders", "amt", subset_condition="", custom_query="  "))

    mapped, _ = _map(document, _mapping("orders,amt,orders,amount"))

    assert mapped["definitions"][0]["subset_condition"] == ""


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ("a,x,a,z\na,y,a,z", r"a\.x, a\.y -> a\.z"),
        ("a,x,a,y", r"a\.x, a\.y -> a\.y"),
        ("a,,c,\nb,,c,", "a, b -> c"),
    ],
    ids=["two-sources", "onto-pass-through", "tables"],
)
def test_refuses_many_to_one(rows, message):
    document = _document(
        _test("Match_Row_Ct", "a"),
        _test("Match_Row_Ct", "b"),
        _test("Match_Null_Ct", "a", "x"),
        _test("Match_Null_Ct", "a", "y"),
    )

    with pytest.raises(script.MappingRefused, match=message):
        _map(document, _mapping(rows))


def test_allows_two_tables_whose_columns_land_in_one_table_without_colliding():
    document = _document(_test("Match_Null_Ct", "a", "x"), _test("Match_Null_Ct", "b", "y"))

    mapped, _ = _map(document, _mapping("a,,c,\nb,,c,"))

    assert _names(mapped) == [("Match_Null_Ct", "c", "x"), ("Match_Null_Ct", "c", "y")]


def test_marks_its_output_and_refuses_marked_input():
    mapped, _ = _map(_document(_test("Match_Row_Ct", "a")), _mapping("a,,b,"))

    assert mapped[script.MARKER_KEY] == MARKER
    with pytest.raises(script.MappingRefused, match="already been mapped"):
        _map(mapped, _mapping("b,,c,"))


def test_output_imports_like_the_input_apart_from_names():
    document = _document(
        _test("Match_Row_Ct", "orders", threshold_value="120"),
        _test("Match_Max_Val", "orders", "amt", threshold_value="1999.99", lock_refresh=True),
    )

    mapped, _ = _map(document, _mapping("orders,,sales,\norders,amt,sales,amount"))
    payload = ImportPayload.model_validate_json(json.dumps(mapped))
    original = ImportPayload.model_validate_json(json.dumps(document))

    assert payload.version == original.version
    for imported, source in zip(payload.definitions, original.definitions, strict=True):
        assert imported.model_fields_set == source.model_fields_set
        assert imported.model_dump(exclude={"table_name", "column_name"}) == source.model_dump(
            exclude={"table_name", "column_name"}
        )


@pytest.mark.parametrize("version", [2, None, True, "1"])
def test_refuses_unsupported_versions(version):
    document = _document(_test("Match_Row_Ct", "a"), version=version)

    with pytest.raises(script.MappingRefused, match="Unsupported export document version"):
        _map(document, _mapping("a,,b,"))


@pytest.mark.parametrize("document", [[], {"version": 1}, {"version": 1, "definitions": ["x"]}])
def test_refuses_input_that_is_not_an_export_document(document):
    with pytest.raises(script.MappingRefused, match="not a test definition export document"):
        _map(document, _mapping("a,,b,"))


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ("a,x,b,y\na,x,b,z", r"line 3: a\.x is already mapped on line 2"),
        ("a,,b,\na,,c,", "line 3: table a is already mapped on line 2"),
        (",x,b,y", "line 2: source_table is blank"),
        ("a,,,", "line 2: a table row needs a target_table"),
        ("a,,b,c", "line 2: a table row must leave target_column blank"),
        ("a,x,b,", "line 2: a column row needs both"),
        ("a,x,DROP,y", "line 2: a column row is dropped with DROP in target_column"),
        ("a,x ,b,y", "line 2: leading or trailing spaces in source_column"),
        ("a,,DROP_ALL,\na,x,a,y", "line 3: a.x is mapped, but line 2 drops every test on a"),
    ],
)
def test_refuses_malformed_mapping_rows(rows, message):
    with pytest.raises(script.MappingRefused, match=message):
        _mapping(rows)


def test_reports_unmatched_rows_kept_tables_and_followed_columns():
    document = _document(
        _test("Match_Row_Ct", "orders"),
        _test("Match_Null_Ct", "orders", "id"),
        _test("Match_Null_Ct", "orders", "amt"),
        _test("Match_Row_Ct", "customers"),
        _test("Match_Null_Ct", "customers", "id"),
        _test("Match_Null_Ct", "customers", "name"),
    )
    mapping = _mapping("""
        orders,,sales_orders,
        ordrs,amt,orders,amount
    """)

    _, report = _map(document, mapping)
    text = script.format_report(report, Path("in.json"), Path("map.csv"))

    assert "Mapping rows that matched no test (1)\n  line 3: ordrs.amt -> orders.amount\n" in text
    assert "Tables kept as named (1)\n  customers: 3 tests (table-level and 2 columns)\n" in text
    assert ("Columns with no column row that follow their table's rename (1)\n"
            "  orders -> sales_orders: 2 columns, 2 tests\n") in text
    assert "Tests dropped" not in text
    assert "Columns renamed" not in text


def test_main_writes_the_document_and_report(tmp_path):
    (tmp_path / "mapping.csv").write_text("source_table,source_column,target_table,target_column\na,x,b,y\n")
    (tmp_path / "in.json").write_text(json.dumps(_document(_test("Match_Null_Ct", "a", "x"))))

    code = script.main([
        "--mapping", str(tmp_path / "mapping.csv"),
        "--input", str(tmp_path / "in.json"),
        "--output", str(tmp_path / "out.json"),
        "--report", str(tmp_path / "report.txt"),
    ])

    assert code == 0
    output = json.loads((tmp_path / "out.json").read_text())
    assert _names(output) == [("Match_Null_Ct", "b", "y")]
    assert output[script.MARKER_KEY]["mapping_file"] == "mapping.csv"
    assert "a.x -> b.y: 1 test" in (tmp_path / "report.txt").read_text()


def test_main_writes_nothing_on_refusal(tmp_path, capsys):
    (tmp_path / "mapping.csv").write_text("source_table,source_column,target_table,target_column\na,x,b,y\n")
    (tmp_path / "in.json").write_text(json.dumps(_document(_test("Match_Null_Ct", "a", "x"), version=9)))

    code = script.main([
        "--mapping", str(tmp_path / "mapping.csv"),
        "--input", str(tmp_path / "in.json"),
        "--output", str(tmp_path / "out.json"),
        "--report", str(tmp_path / "report.txt"),
    ])

    assert code == 1
    assert not (tmp_path / "out.json").exists()
    assert not (tmp_path / "report.txt").exists()
    assert "Unsupported export document version 9" in capsys.readouterr().err


def test_main_refuses_a_missing_mapping_column(tmp_path, capsys):
    (tmp_path / "mapping.csv").write_text("source_table,target_table\na,b\n")
    (tmp_path / "in.json").write_text(json.dumps(_document()))

    code = script.main([
        "--mapping", str(tmp_path / "mapping.csv"),
        "--input", str(tmp_path / "in.json"),
        "--output", str(tmp_path / "out.json"),
        "--report", str(tmp_path / "report.txt"),
    ])

    assert code == 1
    assert "missing columns: source_column, target_column" in capsys.readouterr().err


def test_skip_unrewritable_leaves_those_tests_out_and_lists_them():
    document = _document(
        _test("Match_Null_Ct", "orders", "amt"),
        _test("CUSTOM", "orders", custom_query="SELECT 1 FROM orders"),
        _test("Dupe_Rows", "orders", groupby_names="id, amt"),
    )

    with pytest.raises(script.MappingRefused, match="pass --skip-unrewritable"):
        _map(document, _mapping("orders,,sales,"))
    mapped, report = script.map_document(document, _mapping("orders,,sales,"), MARKER, skip_unrewritable=True)
    text = script.format_report(report, Path("in.json"), Path("map.csv"))

    assert _names(mapped) == [("Match_Null_Ct", "sales", "amt")]
    assert "test 1 (CUSTOM on orders): custom_query can contain names the script cannot rewrite" in text
    assert "test 2 (Dupe_Rows on orders): groupby_names can contain names the script cannot rewrite" in text


def test_drops_are_grouped_by_reason():
    document = _document(*[_test("Match_Null_Ct", "tmp", f"c{i}") for i in range(5)], _test("Match_Row_Ct", "tmp"))

    _, report = _map(document, _mapping("tmp,,DROP_ALL,"))
    text = script.format_report(report, Path("in.json"), Path("map.csv"))

    assert "Tests dropped (1)\n  tmp mapped to DROP_ALL: 6 tests\n" in text


def test_a_table_collision_folds_the_column_collisions_it_implies():
    document = _document(
        _test("Match_Row_Ct", "a"), _test("Match_Null_Ct", "a", "x"), _test("Match_Null_Ct", "a", "y"),
        _test("Match_Row_Ct", "b"), _test("Match_Null_Ct", "b", "x"), _test("Match_Null_Ct", "b", "y"),
    )

    with pytest.raises(script.MappingRefused) as refusal:
        _map(document, _mapping("a,,c,\nb,,c,"))

    lines = str(refusal.value).splitlines()[1:]
    assert [line.strip() for line in lines] == ["a, b -> c", "and 2 column collisions between the colliding tables above"]


def test_main_skip_unrewritable_flag(tmp_path):
    (tmp_path / "mapping.csv").write_text("source_table,source_column,target_table,target_column\na,,b,\n")
    document = _document(_test("Match_Null_Ct", "a", "x"), _test("CUSTOM", "a", custom_query="SELECT 1"))
    (tmp_path / "in.json").write_text(json.dumps(document))
    args = ["--mapping", str(tmp_path / "mapping.csv"), "--input", str(tmp_path / "in.json"),
            "--output", str(tmp_path / "out.json"), "--report", str(tmp_path / "report.txt")]

    assert script.main(args) == 1
    assert script.main([*args, "--skip-unrewritable"]) == 0
    assert _names(json.loads((tmp_path / "out.json").read_text())) == [("Match_Null_Ct", "b", "x")]


def test_refuses_an_unmapped_key_column_left_behind_by_its_test():
    document = _document(_test("Match_Keyed_Hash_Text", "orders", "name", groupby_names="order_id"))
    mapping = _mapping("""
        orders,,sales,
        orders,name,sales2,name
    """)

    with pytest.raises(script.MappingRefused, match="has no column row and so stays with table sales"):
        _map(document, mapping)


def test_an_unmapped_key_column_follows_its_table_rename():
    document = _document(_test("Match_Keyed_Hash_Text", "orders", "name", groupby_names="order_id"))

    mapped, report = _map(document, _mapping("orders,,sales,"))

    assert mapped["definitions"][0]["groupby_names"] == "order_id"
    assert report.unmapped_keys == {}


def test_column_tests_on_a_dropped_table_row_are_kept_as_named():
    document = _document(_test("Match_Row_Ct", "audit"), _test("Match_Null_Ct", "audit", "id"))

    mapped, report = _map(document, _mapping("audit,,DROP,"))
    text = script.format_report(report, Path("in.json"), Path("map.csv"))

    assert _names(mapped) == [("Match_Null_Ct", "audit", "id")]
    assert "Tables kept as named (1)\n  audit: 1 test (1 column)\n" in text


def test_tests_the_mapping_drops_are_not_refused_as_unrewritable():
    document = _document(_test("CUSTOM", "tmp", custom_query="SELECT 1"), _test("Match_Null_Ct", "keep", "id"))

    mapped, report = _map(document, _mapping("tmp,,DROP_ALL,"))

    assert _names(mapped) == [("Match_Null_Ct", "keep", "id")]
    assert [test.reason for test in report.dropped] == ["tmp mapped to DROP_ALL"]


def test_a_table_named_test_groups_its_drops():
    document = _document(_test("Match_Null_Ct", "test", "a"), _test("Match_Null_Ct", "test", "b"))

    _, report = _map(document, _mapping("test,,DROP_ALL,"))
    text = script.format_report(report, Path("in.json"), Path("map.csv"))

    assert "Tests dropped (1)\n  test mapped to DROP_ALL: 2 tests\n" in text


def test_a_misspelled_drop_row_still_shows_as_matching_no_test():
    document = _document(_test("Match_Column_Ct", "orders"), _test("Match_Null_Ct", "orders", "legacy"))

    mapped, report = _map(document, _mapping("orders,lgacy,,DROP"))

    assert _names(mapped) == [("Match_Null_Ct", "orders", "legacy")]
    assert [row.describe() for row in report.unmatched_rows] == ["line 2: orders.lgacy -> DROP"]


def _cli_args(tmp_path: Path, output: Path | None = None, report: Path | None = None) -> list[str]:
    (tmp_path / "mapping.csv").write_text("source_table,source_column,target_table,target_column\na,x,b,y\n")
    (tmp_path / "in.json").write_text(json.dumps(_document(_test("Match_Null_Ct", "a", "x"))))
    return ["--mapping", str(tmp_path / "mapping.csv"), "--input", str(tmp_path / "in.json"),
            "--output", str(output or tmp_path / "out.json"), "--report", str(report or tmp_path / "report.txt")]


def test_main_refuses_an_output_that_is_the_input_under_another_name(tmp_path):
    args = _cli_args(tmp_path, output=tmp_path / "linked.json")
    os.link(tmp_path / "in.json", tmp_path / "linked.json")
    original = (tmp_path / "in.json").read_text()

    assert script.main(args) == 1
    assert (tmp_path / "in.json").read_text() == original


def test_main_writes_neither_file_when_one_cannot_be_written(tmp_path, capsys):
    args = _cli_args(tmp_path, report=tmp_path / "missing" / "report.txt")

    assert script.main(args) == 1
    assert not (tmp_path / "out.json").exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["in.json", "mapping.csv"]
    assert "Error:" in capsys.readouterr().err


def test_moving_a_column_drops_both_tables_column_count():
    document = _document(
        _test("Match_Column_Ct", "orders"),
        _test("Match_Column_Ct", "notes"),
        _test("Match_Column_Ct", "customers"),
        _test("Match_Null_Ct", "orders", "note"),
    )
    mapping = _mapping("""
        orders,,sales_orders,
        notes,,order_notes,
        orders,note,order_notes,note
    """)

    mapped, report = _map(document, mapping)

    assert _names(mapped) == [("Match_Column_Ct", "customers", None), ("Match_Null_Ct", "order_notes", "note")]
    assert [test.reason for test in report.dropped] == [
        "a column of orders moves to another table, so the column count no longer matches",
        "a column from another table moves into order_notes, so the column count no longer matches",
    ]


def test_moving_a_column_into_a_new_table_drops_only_the_source_tables_column_count():
    document = _document(_test("Match_Column_Ct", "orders"), _test("Match_Null_Ct", "orders", "note"))

    mapped, _ = _map(document, _mapping("orders,note,order_notes,note"))

    assert _names(mapped) == [("Match_Null_Ct", "order_notes", "note")]


def test_a_column_row_into_the_tables_own_destination_is_not_a_move():
    document = _document(_test("Match_Column_Ct", "orders"), _test("Match_Null_Ct", "orders", "note"))
    mapping = _mapping("""
        orders,,sales_orders,
        orders,note,sales_orders,remark
    """)

    mapped, _ = _map(document, mapping)

    assert _names(mapped) == [("Match_Column_Ct", "sales_orders", None), ("Match_Null_Ct", "sales_orders", "remark")]


def test_a_table_row_matches_when_every_column_has_its_own_row():
    document = _document(_test("Match_Null_Ct", "orders", "id"))
    mapping = _mapping("""
        orders,,sales,
        orders,id,sales,order_id
    """)

    _, report = _map(document, mapping)

    assert report.unmatched_rows == []


@pytest.mark.parametrize(
    "rows",
    ["a,,t,\nb,,t,", "a,,t,\nb,,t,\nb,y,t,y", "a,,t,"],
    ids=["both-renamed", "column-row-into-shared-landing", "onto-a-table-that-keeps-its-name"],
)
def test_two_tables_landing_in_one_table_drop_their_column_counts(rows):
    document = _document(
        _test("Match_Column_Ct", "a"),
        _test("Match_Null_Ct", "a", "x"),
        _test("Match_Null_Ct", "t", "z") if rows == "a,,t," else _test("Match_Null_Ct", "b", "y"),
    )

    mapped, report = _map(document, _mapping(rows))

    assert [d["test_type"] for d in mapped["definitions"]] == ["Match_Null_Ct", "Match_Null_Ct"]
    assert [test.reason for test in report.dropped] == [
        "another table also lands in t, so the column count no longer matches",
    ]


def test_a_table_renamed_onto_a_vacated_name_keeps_its_column_count():
    document = _document(_test("Match_Column_Ct", "a"), _test("Match_Null_Ct", "b", "y"))

    mapped, _ = _map(document, _mapping("a,,b,\nb,,c,"))

    assert _names(mapped) == [("Match_Column_Ct", "b", None), ("Match_Null_Ct", "c", "y")]


def test_main_refuses_a_mapping_that_is_not_utf8(tmp_path, capsys):
    args = _cli_args(tmp_path)
    (tmp_path / "mapping.csv").write_bytes(
        "source_table,source_column,target_table,target_column\na,x,b,café\n".encode("cp1252")
    )

    assert script.main(args) == 1
    assert "Mapping file is not UTF-8 text" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()


def test_main_refuses_a_mapping_that_is_not_valid_csv(tmp_path, capsys):
    args = _cli_args(tmp_path)
    (tmp_path / "mapping.csv").write_text(
        f"source_table,source_column,target_table,target_column\na,x,b,{'y' * (csv.field_size_limit() + 1)}\n"
    )

    assert script.main(args) == 1
    assert "Mapping file is not valid CSV" in capsys.readouterr().err


def test_main_refuses_an_input_that_is_not_utf8(tmp_path, capsys):
    args = _cli_args(tmp_path)
    (tmp_path / "in.json").write_bytes(json.dumps(_document(_test("Match_Null_Ct", "café", "x")), ensure_ascii=False).encode("cp1252"))

    assert script.main(args) == 1
    assert "Input is not valid JSON" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_main_writes_files_with_the_mode_a_plain_open_gives(tmp_path):
    args = _cli_args(tmp_path)
    (tmp_path / "report.txt").write_text("previous run\n")
    os.chmod(tmp_path / "report.txt", 0o640)
    umask = os.umask(0o022)
    try:
        assert script.main(args) == 0
    finally:
        os.umask(umask)

    assert (tmp_path / "out.json").stat().st_mode & 0o777 == 0o644
    assert (tmp_path / "report.txt").stat().st_mode & 0o777 == 0o640


SOURCE_SUITE = "11111111-1111-1111-1111-111111111111"
DEST_SUITE = "22222222-2222-2222-2222-222222222222"
API_URL = "https://testgen.example.com"
TOKEN = "secret-token-value"  # noqa: S105


class FakeApi:
    """Stands in for urlopen: records each request and answers from a queue of responses."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: Any, timeout: float) -> Any:
        self.requests.append({
            "method": request.get_method(),
            "url": request.full_url,
            "headers": dict(request.header_items()),
            "body": json.loads(request.data) if request.data else None,
            "timeout": timeout,
        })
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _Response(response if isinstance(response, bytes) else json.dumps(response).encode())


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _http_error(status: int, body: Any) -> HTTPError:
    return HTTPError(API_URL, status, "error", {}, io.BytesIO(json.dumps(body).encode()))  # type: ignore[arg-type]


def _import_result(
    created: int = 0, updated: int = 0, skipped: list[tuple[str, list[int]]] = (), deleted: int = 0
) -> dict[str, Any]:
    items = [
        {"action": "skip", "reason": reason, "tds": [{"idx": idx} for idx in indexes]} for reason, indexes in skipped
    ]
    return {
        "summary": {
            "created": created, "updated": updated, "skipped": sum(len(i) for _, i in skipped), "deleted": deleted,
        },
        "items": items,
    }


def _api_args(tmp_path: Path, *extra: str) -> list[str]:
    (tmp_path / "mapping.csv").write_text("source_table,source_column,target_table,target_column\na,x,b,y\n")
    return ["--mapping", str(tmp_path / "mapping.csv"), "--api-url", API_URL, "--export-from", SOURCE_SUITE,
            "--import-to", DEST_SUITE, "--output", str(tmp_path / "out.json"), "--report", str(tmp_path / "report.txt"),
            *extra]


@pytest.fixture
def api(monkeypatch):
    def install(*responses: Any) -> FakeApi:
        fake = FakeApi(*responses)
        monkeypatch.setattr(script, "_open", fake)
        return fake
    monkeypatch.setenv(script.API_TOKEN_VARIABLE, TOKEN)
    return install


def test_api_exports_maps_and_previews_the_import(tmp_path, api, capsys):
    export = _document(_test("Match_Null_Ct", "a", "x"), _test("Match_Row_Ct", "c"))
    fake = api(export, _import_result(created=1, skipped=[("invalid_table", [1])]))

    assert script.main(_api_args(tmp_path)) == 0

    export_request, import_request = fake.requests
    assert export_request["method"] == "GET"
    assert export_request["url"] == f"{API_URL}/api/v1/test-suites/{SOURCE_SUITE}/test-definition-export"
    assert export_request["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert export_request["timeout"] == script.API_TIMEOUT_SECONDS
    assert import_request["method"] == "POST"
    assert import_request["url"] == f"{API_URL}/api/v1/test-suites/{DEST_SUITE}/test-definition-import"
    assert import_request["body"]["config"] == {
        "mode": "preview", "on_match": "overwrite_all", "on_new": "create_and_lock", "on_absence": "do_nothing",
    }
    output = json.loads((tmp_path / "out.json").read_text())
    assert import_request["body"]["payload"] == output
    assert _names(output) == [("Match_Null_Ct", "b", "y"), ("Match_Row_Ct", "c", None)]

    report = (tmp_path / "report.txt").read_text()
    assert f"Input:   test suite {SOURCE_SUITE} at {API_URL}" in report
    assert f"Import preview into test suite {DEST_SUITE} (nothing imported)" in report
    assert "1 test would be created, 1 test would be skipped" in report
    assert "table not found in the destination table group:\n    c: 1 test" in report
    out = capsys.readouterr().out
    assert "run the same command with --apply" in out
    assert TOKEN not in report + out


def test_api_apply_imports_with_all_or_nothing_semantics(tmp_path, api, capsys):
    fake = api(_document(_test("Match_Null_Ct", "a", "x")), _import_result(created=1))

    assert script.main(_api_args(tmp_path, "--apply")) == 0

    assert [request["method"] for request in fake.requests] == ["GET", "POST"]
    assert fake.requests[1]["body"]["config"]["mode"] == "apply_strict"
    assert f"Import into test suite {DEST_SUITE}\n  1 test created" in (tmp_path / "report.txt").read_text()
    assert f"Imported into test suite {DEST_SUITE}: 1 test created." in capsys.readouterr().out


def test_api_delete_absent_deletes_destination_tests_missing_from_the_document(tmp_path, api, capsys):
    fake = api(
        _document(_test("Match_Null_Ct", "a", "x")), _import_result(updated=1, deleted=2),
        _document(_test("Match_Null_Ct", "a", "x")), _import_result(updated=1, deleted=2),
    )

    assert script.main(_api_args(tmp_path, "--delete-absent")) == 0
    assert "1 test would be updated, 2 tests would be deleted" in (tmp_path / "report.txt").read_text()
    assert script.main(_api_args(tmp_path, "--delete-absent", "--apply")) == 0

    preview, applied = fake.requests[1]["body"]["config"], fake.requests[3]["body"]["config"]
    assert (preview["mode"], preview["on_absence"]) == ("preview", "delete_all")
    assert (applied["mode"], applied["on_absence"]) == ("apply_strict", "delete_all")
    assert "1 test updated, 2 tests deleted." in capsys.readouterr().out


def test_api_apply_refused_when_tests_would_be_skipped(tmp_path, api, capsys):
    result = _import_result(created=1, skipped=[("missing_required_field", [0])])
    api(
        _document(_test("Match_Null_Ct", "a", "x"), _test("Match_Row_Ct", "a")),
        _http_error(400, {"detail": {"errors": [{"code": "strict_validation_failed", "detail": "1 skipped"}],
                                     "import_result": result}}),
    )

    assert script.main(_api_args(tmp_path, "--apply")) == 1

    report = (tmp_path / "report.txt").read_text()
    assert "refused: tests would be skipped, so nothing was imported" in report
    assert "required field left blank:\n    Match_Null_Ct on b.y: 1 test" in report
    assert (tmp_path / "out.json").exists()
    assert "would skip tests, so nothing was imported" in capsys.readouterr().err


def test_api_imports_a_file_input(tmp_path, api):
    args = _cli_args(tmp_path)
    fake = api(_import_result(created=1))

    assert script.main([*args, "--api-url", API_URL, "--import-to", DEST_SUITE]) == 0

    assert [request["method"] for request in fake.requests] == ["POST"]
    assert f"Input:   {tmp_path / 'in.json'}" in (tmp_path / "report.txt").read_text()


def test_api_export_not_found_writes_nothing(tmp_path, api, capsys):
    api(_http_error(404, {"detail": {"errors": [{"code": "not_found", "detail": "Not found"}]}}))

    assert script.main(_api_args(tmp_path)) == 1

    assert not (tmp_path / "out.json").exists()
    assert not (tmp_path / "report.txt").exists()
    assert f"Test suite {SOURCE_SUITE} was not found, or the token's user cannot view it" in capsys.readouterr().err


def test_api_preview_failure_writes_nothing(tmp_path, api, capsys):
    api(_document(_test("Match_Null_Ct", "a", "x")), _http_error(401, {"detail": "Invalid or expired token"}))

    assert script.main(_api_args(tmp_path)) == 1

    assert not (tmp_path / "out.json").exists()
    assert "returned HTTP 401: Invalid or expired token" in capsys.readouterr().err


def test_api_apply_connection_failure_says_the_import_may_have_run(tmp_path, api, capsys):
    api(_document(_test("Match_Null_Ct", "a", "x")), URLError("timed out"))

    assert script.main(_api_args(tmp_path, "--apply")) == 1

    error = capsys.readouterr().err
    assert "Could not reach" in error
    assert "The import may have run" in error
    assert (tmp_path / "report.txt").exists()


def test_api_apply_gateway_error_says_the_import_may_have_run(tmp_path, api, capsys):
    api(_document(_test("Match_Null_Ct", "a", "x")), _http_error(504, {"detail": "Gateway Timeout"}))

    assert script.main(_api_args(tmp_path, "--apply")) == 1

    assert "The import may have run" in capsys.readouterr().err


def test_api_apply_client_error_says_nothing_was_imported(tmp_path, api, capsys):
    api(_document(_test("Match_Null_Ct", "a", "x")), _http_error(401, {"detail": "Invalid or expired token"}))

    assert script.main(_api_args(tmp_path, "--apply")) == 1

    assert "Nothing was imported" in capsys.readouterr().err


def test_api_refuses_a_redirect_instead_of_following_it():
    request = script.Request(f"{API_URL}/api/v1/test-suites/x/test-definition-import", data=b"{}", method="POST")

    with pytest.raises(script.ApiFailed, match="redirected to https://other.example.com/"):
        script._RefuseRedirects().redirect_request(request, None, 301, "Moved", {}, "https://other.example.com/")
    assert any(isinstance(handler, script._RefuseRedirects) for handler in script._opener.handlers)


def test_api_404_from_an_unknown_path_is_not_blamed_on_the_suite(tmp_path, api, capsys):
    api(HTTPError(API_URL, 404, "Not Found", {}, io.BytesIO(b"Not Found")))  # type: ignore[arg-type]

    assert script.main(_api_args(tmp_path)) == 1

    error = capsys.readouterr().err
    assert "returned HTTP 404. Check that --api-url is the TestGen API URL" in error
    assert "was not found, or the token's user" not in error


def test_api_response_that_is_not_json_points_at_the_api_url(tmp_path, api, capsys):
    api(b"<html>TestGen</html>")

    assert script.main(_api_args(tmp_path)) == 1
    assert "not the UI URL" in capsys.readouterr().err


def test_api_url_with_the_api_prefix_is_accepted(tmp_path, api):
    args = _api_args(tmp_path)
    args[args.index(API_URL)] = f"{API_URL}/api/v1/"
    fake = api(_document(_test("Match_Null_Ct", "a", "x")), _import_result(created=1))

    assert script.main(args) == 0
    assert fake.requests[0]["url"].startswith(f"{API_URL}/api/v1/test-suites/")


@pytest.mark.parametrize(("change", "message"), [
    (lambda args: [*(a for a in args if a not in ("--import-to", DEST_SUITE)), "--apply"],
     "--apply requires --import-to"),
    (lambda args: [*(a for a in args if a not in ("--import-to", DEST_SUITE)), "--delete-absent"],
     "--delete-absent requires --import-to"),
    (lambda args: [a for a in args if a not in ("--api-url", API_URL)], "require --api-url"),
    (lambda args: [*args[:args.index(SOURCE_SUITE)], "suite-name", *args[args.index(SOURCE_SUITE) + 1:]],
     "--export-from takes a test suite ID"),
    (lambda args: [SOURCE_SUITE if a == DEST_SUITE else a for a in args], "must be different test suites"),
    (lambda args: ["ftp://host" if a == API_URL else a for a in args], "must start with http:// or https://"),
])
def test_api_argument_errors(tmp_path, api, capsys, change, message):
    fake = api()

    with pytest.raises(SystemExit):
        script.main(change(_api_args(tmp_path)))

    assert message in capsys.readouterr().err
    assert not fake.requests


def test_api_url_without_an_api_option_is_an_error(tmp_path, capsys):
    with pytest.raises(SystemExit):
        script.main([*_cli_args(tmp_path), "--api-url", API_URL])
    assert "--api-url is used only with" in capsys.readouterr().err


def test_api_requires_the_token_variable(tmp_path, api, monkeypatch, capsys):
    fake = api()
    monkeypatch.delenv(script.API_TOKEN_VARIABLE)

    with pytest.raises(SystemExit):
        script.main(_api_args(tmp_path))

    assert script.API_TOKEN_VARIABLE in capsys.readouterr().err
    assert not fake.requests
