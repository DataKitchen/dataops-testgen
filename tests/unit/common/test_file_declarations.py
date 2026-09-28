"""Tests for file declarations — the table list a file-based connection's table group carries."""

from types import SimpleNamespace

import pytest

from testgen.common.database import database_service
from testgen.common.database.database_service import set_target_db_params
from testgen.common.database.file_declarations import (
    NAME_DUPLICATE,
    NAME_INVALID,
    NAME_REQUIRED,
    NO_DECLARATIONS,
    PATH_OUTSIDE_BASE_PATH,
    URI_HAS_CREDENTIALS,
    URI_IS_FOLDER,
    URI_OUTSIDE_BASE_PATH,
    URI_REQUIRED,
    FileDeclaration,
    create_view_statement,
    has_embedded_credentials,
    is_inside_base_path,
    is_multi_file,
    parse_file_declarations,
    read_pattern,
    resolve_uri,
    skip_reason,
    validate_file_declarations,
)
from testgen.common.enums import FileFormat

pytestmark = pytest.mark.unit


@pytest.fixture
def base_path(tmp_path):
    root = tmp_path / "data"
    (root / "nested").mkdir(parents=True)
    (root / "claims_2024.csv").write_text("id,amount\n1,10\n")
    (root / "claims_2025.csv").write_text("id,amount\n2,20\n")
    (root / "nested" / "extra.csv").write_text("id,amount\n3,30\n")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.csv").write_text("a\n1\n")
    return root


def declaration(**overrides) -> FileDeclaration:
    return FileDeclaration(
        **{"name": "claims", "uri": "claims_*.csv", "format": FileFormat.CSV, "options": {}, **overrides}
    )


def validate(entries, base_path) -> list[str]:
    """Validate declarations that are complete apart from what the test is exercising."""
    return validate_file_declarations([{"format": "csv", **entry} for entry in entries], str(base_path))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_stored_entries_become_declarations():
    parsed = parse_file_declarations([
        {"name": " claims ", "uri": " claims_*.csv ", "format": "CSV"},
        {"name": "dim", "uri": "dim.parquet", "format": "parquet", "options": {"ignored": 1}},
    ])

    assert [(d.name, d.uri, d.format) for d in parsed] == [
        ("claims", "claims_*.csv", FileFormat.CSV),
        ("dim", "dim.parquet", FileFormat.PARQUET),
    ]


def test_an_entry_naming_a_format_testgen_cannot_read_is_skipped():
    assert parse_file_declarations([{"name": "x", "uri": "x.avro", "format": "avro"}]) == []


def test_nothing_stored_parses_to_nothing():
    assert parse_file_declarations(None) == []


# ---------------------------------------------------------------------------
# Validation — the messages the form shows, word for word
# ---------------------------------------------------------------------------


def test_a_table_group_with_no_declarations_is_rejected(base_path):
    assert validate([], base_path) == [NO_DECLARATIONS]


def test_a_nameless_declaration_is_rejected(base_path):
    assert any(NAME_REQUIRED in error for error in validate([{"uri": "claims_*.csv"}], base_path))


@pytest.mark.parametrize("name", ["9claims", "my claims", "claims-2024", "claims!", "$claims"])
def test_a_name_that_is_not_an_identifier_is_rejected(base_path, name):
    errors = validate([{"name": name, "uri": "claims_*.csv"}], base_path)
    assert any(NAME_INVALID in error for error in errors)


@pytest.mark.parametrize("name", ["claims", "_claims", "Claims2024", "a"])
def test_an_identifier_name_is_accepted(base_path, name):
    assert validate([{"name": name, "uri": "claims_*.csv"}], base_path) == []


@pytest.mark.parametrize("second_name", ["claims", "Claims"])
def test_two_declarations_cannot_share_a_name(base_path, second_name):
    errors = validate([
        {"name": "claims", "uri": "claims_2024.csv"},
        {"name": second_name, "uri": "claims_2025.csv"},
    ], base_path)
    assert any(NAME_DUPLICATE in error for error in errors)


def test_a_declaration_with_no_path_is_rejected(base_path):
    assert any(URI_REQUIRED in error for error in validate([{"name": "claims"}], base_path))


def test_an_error_names_the_table_it_belongs_to(base_path):
    errors = validate([{"name": "claims", "uri": ""}], base_path)
    assert errors == [f"claims: {URI_REQUIRED}"]


def test_an_unnamed_table_is_identified_by_position(base_path):
    errors = validate([{"name": "", "uri": ""}], base_path)
    assert all(error.startswith("Table 1: ") for error in errors)


# ---------------------------------------------------------------------------
# Credentials and containment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("uri", [
    "claims.csv?sig=abc123",
    "claims.csv?sv=2021&sig=abc123",
    "claims.csv?X-Amz-Signature=deadbeef",
    "claims.csv?x-amz-credential=AKIA",
    "claims.csv?X-Goog-Signature=abc",
])
def test_a_path_carrying_a_signed_url_is_rejected(base_path, uri):
    assert has_embedded_credentials(uri)
    assert any(URI_HAS_CREDENTIALS in error for error in validate([{"name": "claims", "uri": uri}], base_path))


@pytest.mark.parametrize("uri", ["claims.csv", "claims.csv?version=2", "a?b", "claims_*.csv"])
def test_an_ordinary_path_carries_no_credentials(uri):
    assert not has_embedded_credentials(uri)


@pytest.mark.parametrize("uri", ["../outside/secret.csv", "nested/../../outside/secret.csv"])
def test_a_path_climbing_out_of_the_base_path_is_rejected(base_path, uri):
    assert not is_inside_base_path(str(base_path), uri)
    errors = validate([{"name": "escape", "uri": uri}], base_path)
    assert any(URI_OUTSIDE_BASE_PATH in error for error in errors)


def test_an_absolute_path_elsewhere_is_rejected(base_path):
    outside = base_path.parent / "outside" / "secret.csv"
    assert not is_inside_base_path(str(base_path), str(outside))


def test_an_absolute_path_inside_the_base_path_is_kept(base_path):
    inside = base_path / "claims_2024.csv"
    assert is_inside_base_path(str(base_path), str(inside))
    assert resolve_uri(str(base_path), str(inside)) == inside.resolve()


def test_a_symlink_pointing_out_of_the_base_path_is_rejected(base_path):
    link = base_path / "linked.csv"
    link.symlink_to(base_path.parent / "outside" / "secret.csv")
    assert not is_inside_base_path(str(base_path), "linked.csv")


def test_nothing_is_inside_a_connection_with_no_base_path():
    assert not is_inside_base_path("", "claims.csv")


# ---------------------------------------------------------------------------
# Building the read
# ---------------------------------------------------------------------------


def test_a_pattern_is_read_as_written(base_path):
    pattern = read_pattern(str(base_path), declaration(uri="**/*.csv"))
    assert pattern == f"{base_path.resolve()}/**/*.csv"


@pytest.mark.parametrize("uri", [".", "nested", "nested/"])
def test_a_folder_is_rejected_in_favor_of_a_pattern(base_path, uri):
    errors = validate([{"name": "claims", "uri": uri, "format": "csv"}], base_path)
    assert errors == [f"claims: {URI_IS_FOLDER}"]


def test_a_pattern_over_a_folder_is_accepted(base_path):
    assert validate([{"name": "claims", "uri": "nested/*.csv", "format": "csv"}], base_path) == []


def test_a_single_file_is_read_as_itself(base_path):
    pattern = read_pattern(str(base_path), declaration(uri="claims_2024.csv"))
    assert pattern == str((base_path / "claims_2024.csv").resolve())


@pytest.mark.parametrize(("uri", "expected"), [
    ("claims_*.csv", True),
    ("claims_202?.csv", True),
    ("**/*.csv", True),
    ("claims_2024.csv", False),
])
def test_a_declaration_matching_more_than_one_file_is_recognized(uri, expected):
    assert is_multi_file(declaration(uri=uri)) is expected


def test_a_multi_file_declaration_unions_the_columns_of_every_file(base_path):
    statement = create_view_statement(str(base_path), declaration(uri="claims_*.csv"), "main")
    assert "union_by_name = true" in statement


def test_a_single_file_declaration_does_not_ask_for_a_union(base_path):
    statement = create_view_statement(str(base_path), declaration(uri="claims_2024.csv"), "main")
    assert "union_by_name" not in statement


def test_json_unions_across_files_without_being_asked(base_path):
    statement = create_view_statement(
        str(base_path), declaration(uri="*.json", format=FileFormat.JSON), "main",
    )
    assert "union_by_name" not in statement


@pytest.mark.parametrize(("file_format", "reader"), [
    (FileFormat.CSV, "read_csv"),
    (FileFormat.PARQUET, "read_parquet"),
    (FileFormat.JSON, "read_json"),
])
def test_each_format_selects_its_own_reader(base_path, file_format, reader):
    statement = create_view_statement(
        str(base_path), declaration(uri="claims_2024.csv", format=file_format), "main",
    )
    assert f"FROM {reader}(" in statement


def test_declared_csv_settings_reach_the_reader(base_path):
    statement = create_view_statement(
        str(base_path),
        declaration(uri="claims_2024.csv", options={"delimiter": "|", "header": True, "quote": "'"}),
        "main",
    )
    assert "delim = '|'" in statement
    assert "header = true" in statement
    assert "quote = ''''" in statement


def test_a_blank_setting_is_left_out(base_path):
    statement = create_view_statement(
        str(base_path), declaration(uri="claims_2024.csv", options={"delimiter": "", "quote": None}), "main",
    )
    assert "delim" not in statement
    assert "quote = " not in statement


def test_a_quoted_empty_field_stays_an_empty_string(base_path):
    """Read as NULL it would be indistinguishable from a missing value, and no non-standard blank
    would be left for TestGen to report."""
    statement = create_view_statement(str(base_path), declaration(uri="claims_2024.csv"), "main")
    assert "allow_quoted_nulls = false" in statement


def test_settings_that_would_make_a_read_tolerant_never_reach_the_reader(base_path):
    """A tolerant read drops rows silently, so a column-scoped test and a row count disagree."""
    statement = create_view_statement(
        str(base_path),
        declaration(uri="claims_2024.csv", options={"ignore_errors": True, "store_rejects": True}),
        "main",
    )
    assert "ignore_errors" not in statement
    assert "store_rejects" not in statement


def test_a_setting_a_format_does_not_declare_is_left_out(base_path):
    statement = create_view_statement(
        str(base_path),
        declaration(uri="dim.parquet", format=FileFormat.PARQUET, options={"delimiter": "|"}),
        "main",
    )
    assert "delim" not in statement


def test_a_quote_in_a_path_cannot_end_the_literal(tmp_path):
    root = tmp_path / "da'ta"
    root.mkdir()
    (root / "claims.csv").write_text("id\n1\n")
    statement = create_view_statement(str(root), declaration(uri="claims.csv"), "main")
    assert "da''ta" in statement


@pytest.mark.parametrize(
    "name",
    [
        'claims" AS SELECT 1; DROP TABLE x; CREATE VIEW "junk',
        'claims"',
        "claims table",
        "2claims",
        "",
    ],
)
def test_a_name_that_is_not_an_identifier_is_refused(base_path, name):
    """The name becomes an identifier in DDL. A driver that runs several statements per call
    would turn a quote here into arbitrary SQL against the target."""
    with pytest.raises(ValueError, match="Name must start with a letter"):
        create_view_statement(base_path, declaration(name=name), "main")


# ---------------------------------------------------------------------------
# Reaching the connection
# ---------------------------------------------------------------------------


def test_a_table_group_declarations_reach_the_target_connection(monkeypatch):
    """A file flavor builds its views as the connection opens, so they have to arrive with it."""
    monkeypatch.setattr(database_service, "target_db_params", None)
    monkeypatch.setattr(database_service.engine_cache, "target_db", None, raising=False)
    set_target_db_params(
        {"sql_flavor": "duckdb", "sql_flavor_code": "files"},
        SimpleNamespace(file_declarations=[{"name": "claims", "uri": "claims_*.csv", "format": "csv"}]),
    )

    assert database_service.target_db_params.declarations == [
        FileDeclaration(name="claims", uri="claims_*.csv", format=FileFormat.CSV)
    ]
    assert "file_declarations" not in database_service.target_db_params.connection


def test_no_table_group_carries_no_declarations(monkeypatch):
    monkeypatch.setattr(database_service, "target_db_params", None)
    monkeypatch.setattr(database_service.engine_cache, "target_db", None, raising=False)
    set_target_db_params({"sql_flavor": "postgresql"}, None)

    assert database_service.target_db_params.declarations == []


@pytest.mark.parametrize(
    "name,uri,expected",
    [
        ("claims", "claims_2024.csv", None),
        ("claims", "claims_*.csv", None),
        ("bad name", "claims_2024.csv", NAME_INVALID),
        ("escape", "../outside/secret.csv", PATH_OUTSIDE_BASE_PATH),
    ],
)
def test_skip_reason_names_why_a_declaration_cannot_be_read(base_path, name, uri, expected):
    assert skip_reason(str(base_path), FileDeclaration(name=name, uri=uri, format=FileFormat.CSV)) == expected
