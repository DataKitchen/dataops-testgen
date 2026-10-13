#!/usr/bin/env python
"""
Test Transfer Script

Transfers test definitions from one test suite to another whose table group names its tables or columns
differently, renaming the tables and columns from a mapping table. Through the TestGen API, it exports the source
test suite, maps it, and previews or applies the import into the destination test suite. It also maps an exported
test definition document given as a file. Either way it writes the mapped document and a change report.

Runs on Python 3.11+ with the standard library only; TestGen does not need to be installed.

Usage:
    export TESTGEN_API_TOKEN=<access token>
    python scripts/transfer_tests.py \
        --api-url <TestGen API URL> \
        --export-from <source test suite ID> \
        --import-to <destination test suite ID> \
        --mapping mapping.csv \
        --output mapped_suite.json \
        --report transfer_report.txt \
        [--apply] \
        [--delete-absent] \
        [--skip-unrewritable]

    --import-to previews the import of the mapped document and adds the preview to the report; nothing is imported.
    Run the same command again with --apply to import. The import creates tests the destination does not have and
    locks the generated ones, overwrites matching tests even when locked, and leaves the destination's other tests
    alone. It imports every test or none: when any test would be skipped, nothing is imported and the report lists the
    skipped tests.

    With --delete-absent, the import also deletes every destination test that is not in the mapped document,
    including tests added to the destination test suite by hand and the destination copies of tests that
    --skip-unrewritable leaves out. Pass it to the preview as well, so the preview counts the tests that would be
    deleted.

    To map an exported document file instead, pass --input in place of --export-from. Without --import-to, the script
    only writes the mapped document and the report:

    python scripts/transfer_tests.py \
        --mapping mapping.csv \
        --input source_suite.json \
        --output mapped_suite.json \
        --report transfer_report.txt

Mapping CSV:
    Four columns: source_table, source_column, target_table, target_column. Names are exact and case-sensitive,
    unquoted, as profiling stores them. Column rows are keyed by the source table name.

    source_table,source_column,target_table,target_column
    orders,,sales_orders,
    orders,cust_id,sales_orders,customer_id
    orders,legacy_flag,,DROP
    audit_log,,DROP,
    staging_tmp,,DROP_ALL,

    - A table row (source_column blank) renames the table.
    - A column row renames the column and places it in its target table.
    - DROP in target_column drops every test on the column, the keyed-hash tests keyed on it, and the table's
      column count test.
    - A column row that places a column in a different table than its own table lands in drops the column count
      test of both tables.
    - Two source tables that land in the same table, through table rows or by keeping their names, drop the column
      count test of both tables.
    - DROP in target_table drops the table's table-level tests only; DROP_ALL drops every test on the table.
    - A column with no column row keeps its name and follows its table's table row, unless that row is DROP.

What the script rewrites:
    table_name and column_name, and groupby_names on the keyed-hash comparison types, where it holds the key
    column. Every other field is copied through unchanged, including fields absent from the input, which stay
    absent. A test with a non-empty field that can embed a name in SQL (subset and having conditions, custom
    queries, the window date column, the referential match fields, other grouping columns) is refused, or, with
    --skip-unrewritable, left out of the mapped document and listed in the report. The mapped document also carries
    a test_transfer entry that marks it as this script's output.

Refusals:
    The script writes nothing and exits with status 1 when the mapping is malformed; when the input is not valid
    JSON, not an export document of a supported format version, or this script's own output; when a test carries a
    field it cannot rewrite (unless --skip-unrewritable); when two source names would land on the same target name;
    when a keyed-hash test's key column would land on a different table than the test; or when the mapping, input,
    output, and report paths are not all different files. With the API, it also exits with status 1: having written
    nothing, when the export or the preview fails; and after writing both files, when the --apply import fails or
    would skip any test, or when it ran but the report could not be updated.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import stat
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

SUPPORTED_FORMAT_VERSIONS = {1}
MARKER_KEY = "test_transfer"

API_TOKEN_VARIABLE = "TESTGEN_API_TOKEN"  # noqa: S105
API_TIMEOUT_SECONDS = 600
IMPORT_POLICY = {"on_match": "overwrite_all", "on_new": "create_and_lock", "on_absence": "do_nothing"}
SKIP_REASONS = {
    "invalid_table": "table not found in the destination table group",
    "invalid_column": "column not found in the destination table group",
    "invalid_test_type": "test type does not exist",
    "managed_test_type": "managed test type",
    "missing_external_id": "manual test without an external_id",
    "missing_required_field": "required field left blank",
}

MAPPING_COLUMNS = ("source_table", "source_column", "target_table", "target_column")
DROP = "DROP"
DROP_ALL = "DROP_ALL"

COLUMN_COUNT_TEST_TYPE = "Match_Column_Ct"
KEYED_HASH_TEST_TYPES = frozenset({"Match_Keyed_Hash_Text", "Match_Keyed_Hash_Num", "Match_Keyed_Hash_Date"})

UNREWRITABLE_FIELDS = (
    "subset_condition",
    "having_condition",
    "custom_query",
    "window_date_column",
    "match_schema_name",
    "match_table_name",
    "match_column_names",
    "match_subset_condition",
    "match_groupby_names",
    "match_having_condition",
)
NON_PLAIN_NAME_CHARS = frozenset(",()\"'`[]")


class MappingRefused(Exception):
    """Raised when the input cannot be mapped safely."""


class ApiFailed(Exception):
    """Raised when a TestGen API request fails."""

    def __init__(self, message: str, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class MappingRow:
    line: int
    source_table: str
    source_column: str
    target_table: str
    target_column: str

    def describe(self) -> str:
        if not self.source_column:
            return f"line {self.line}: {self.source_table} -> {self.target_table}"
        target = DROP if self.target_column == DROP else f"{self.target_table}.{self.target_column}"
        return f"line {self.line}: {self.source_table}.{self.source_column} -> {target}"


@dataclass
class Mapping:
    table_rows: dict[str, MappingRow] = field(default_factory=dict)
    column_rows: dict[tuple[str, str], MappingRow] = field(default_factory=dict)

    @property
    def dropped_column_tables(self) -> set[str]:
        return {table for (table, _), row in self.column_rows.items() if row.target_column == DROP}

    def landing_table(self, table: str) -> str:
        """The table a source table's columns land in when they have no column row."""
        row = self.table_rows.get(table)
        return row.target_table if row and row.target_table not in (DROP, DROP_ALL) else table

    @property
    def moved_columns(self) -> list[tuple[str, str]]:
        """(source table, target table) for each column row that places a column outside its table's landing table."""
        return [
            (table, row.target_table) for (table, _), row in self.column_rows.items()
            if row.target_column != DROP and row.target_table != self.landing_table(table)
        ]

    def all_rows(self) -> list[MappingRow]:
        return sorted([*self.table_rows.values(), *self.column_rows.values()], key=lambda row: row.line)


@dataclass
class DroppedTest:
    index: int
    test_type: str
    location: str
    reason: str
    listed_individually: bool = False


@dataclass
class Report:
    table_renames: Counter[tuple[str, str]] = field(default_factory=Counter)
    column_renames: Counter[tuple[str, str]] = field(default_factory=Counter)
    dropped: list[DroppedTest] = field(default_factory=list)
    unmatched_rows: list[MappingRow] = field(default_factory=list)
    # Tests whose table keeps its name: no table row, or a DROP table row for column tests
    kept: Counter[str] = field(default_factory=Counter)
    kept_columns: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    kept_table_level: set[str] = field(default_factory=set)
    # Tests on a column with no column row that follows its table's table row
    followed: Counter[tuple[str, str]] = field(default_factory=Counter)
    followed_columns: defaultdict[tuple[str, str], set[str]] = field(default_factory=lambda: defaultdict(set))
    unmapped_keys: Counter[str] = field(default_factory=Counter)
    no_table: Counter[str] = field(default_factory=Counter)
    tests_in: int = 0
    tests_out: int = 0


def read_mapping(path: Path) -> Mapping:
    try:
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            missing = [name for name in MAPPING_COLUMNS if name not in (reader.fieldnames or [])]
            if missing:
                raise MappingRefused(f"Mapping file is missing columns: {', '.join(missing)}")
            return parse_mapping_rows(reader)
    except UnicodeDecodeError as error:
        raise MappingRefused(
            f"Mapping file is not UTF-8 text ({error}). Save it with UTF-8 encoding, in Excel as CSV UTF-8."
        ) from error
    except csv.Error as error:
        raise MappingRefused(f"Mapping file is not valid CSV: {error}") from error


def parse_mapping_rows(reader: csv.DictReader[str]) -> Mapping:
    mapping = Mapping()
    errors: list[str] = []
    for record in reader:
        line = reader.line_num
        values = {name: record.get(name) or "" for name in MAPPING_COLUMNS}
        if not any(values.values()):
            continue
        padded = [name for name, value in values.items() if value != value.strip()]
        if padded:
            errors.append(f"line {line}: leading or trailing spaces in {', '.join(padded)}")
            continue

        row = MappingRow(line, **values)
        error = _validate_row(row)
        if error:
            errors.append(f"line {line}: {error}")
        elif row.source_column:
            key = (row.source_table, row.source_column)
            if key in mapping.column_rows:
                errors.append(f"line {line}: {row.source_table}.{row.source_column} is already mapped on line "
                              f"{mapping.column_rows[key].line}")
            else:
                mapping.column_rows[key] = row
        elif row.source_table in mapping.table_rows:
            errors.append(f"line {line}: table {row.source_table} is already mapped on line "
                          f"{mapping.table_rows[row.source_table].line}")
        else:
            mapping.table_rows[row.source_table] = row

    for (table, column), row in mapping.column_rows.items():
        table_row = mapping.table_rows.get(table)
        if table_row and table_row.target_table == DROP_ALL:
            errors.append(f"line {row.line}: {table}.{column} is mapped, but line {table_row.line} drops every test "
                          f"on {table}")

    if errors:
        raise MappingRefused("Mapping file has errors:\n  " + "\n  ".join(errors))
    return mapping


def _validate_row(row: MappingRow) -> str | None:
    if not row.source_table:
        return "source_table is blank"
    if not row.source_column:
        if not row.target_table:
            return "a table row needs a target_table, DROP, or DROP_ALL"
        if row.target_column:
            return "a table row must leave target_column blank"
        return None
    if row.target_column == DROP:
        return None
    if not row.target_table or not row.target_column:
        return "a column row needs both target_table and target_column, or DROP in target_column"
    if row.target_table in (DROP, DROP_ALL) or row.target_column == DROP_ALL:
        return "a column row is dropped with DROP in target_column"
    return None


def map_document(
    document: Any, mapping: Mapping, marker: dict[str, str], skip_unrewritable: bool = False
) -> tuple[dict[str, Any], Report]:
    """Maps the names in an export document.

    :param document: The parsed export document.
    :param mapping: The parsed mapping table.
    :param marker: The value stored under the marker key of the mapped document.
    :param skip_unrewritable: Leave out tests with fields the script cannot rewrite, instead of refusing.
    :return: The mapped document and the change report.
    :raises MappingRefused: When the document cannot be mapped safely.
    """
    definitions = _check_document(document)
    present_tables = {definition.get("table_name") or "" for definition in definitions}
    unrewritable = {
        index: problem for index, problem in _unrewritable(definitions).items()
        if not _drop_reason(definitions[index], mapping, present_tables)
    }
    if unrewritable and not skip_unrewritable:
        raise MappingRefused(
            "These tests have fields that can contain table or column names the script cannot rewrite. Remove the "
            "tests from the document, rename them by hand, or pass --skip-unrewritable to leave them out:\n  "
            + "\n  ".join(f"test {index} ({where}): {fields}" for index, (where, fields) in unrewritable.items())
        )

    report = Report(tests_in=len(definitions))
    mapped_definitions: list[dict[str, Any]] = []
    column_sources: defaultdict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    table_sources: defaultdict[str, set[str]] = defaultdict(set)

    for index, definition in enumerate(definitions):
        test_type = definition.get("test_type", "")
        table = definition.get("table_name") or ""
        column = definition.get("column_name") or ""
        location = f"{table}.{column}" if column else table
        table_row = mapping.table_rows.get(table)
        column_row = mapping.column_rows.get((table, column))
        key_column = _key_column(definition)
        key_row = mapping.column_rows.get((table, key_column))

        drop_reason = _drop_reason(definition, mapping, present_tables)
        if drop_reason:
            report.dropped.append(DroppedTest(index, test_type, location, drop_reason))
            continue

        if index in unrewritable:
            where, fields = unrewritable[index]
            report.dropped.append(DroppedTest(
                index, test_type, location, f"test {index} ({where}): {fields} can contain names the script cannot "
                "rewrite", listed_individually=True,
            ))
            continue

        mapped = dict(definition)
        if not table:
            report.no_table[test_type] += 1
        elif not column:
            if table_row:
                _rename(mapped, "table_name", table_row.target_table, (table, table_row.target_table), report)
            else:
                report.kept[table] += 1
                report.kept_table_level.add(table)
            table_sources[mapped["table_name"]].add(table)
        else:
            if column_row:
                _rename(mapped, "table_name", column_row.target_table, (table, column_row.target_table), report)
                _rename(mapped, "column_name", column_row.target_column, (location, _qualified(column_row)), report)
            elif table_row and table_row.target_table != DROP:
                _rename(mapped, "table_name", table_row.target_table, (table, table_row.target_table), report)
                report.followed[(table, table_row.target_table)] += 1
                report.followed_columns[(table, table_row.target_table)].add(column)
            else:
                report.kept[table] += 1
                report.kept_columns[table].add(column)
            column_sources[(mapped["table_name"], mapped["column_name"])].add((table, column))

        if key_column:
            if key_row:
                key_table, key_source = key_row.target_table, f"line {key_row.line} maps to"
            else:
                follows = table_row and table_row.target_table not in (DROP, DROP_ALL)
                key_table = table_row.target_table if table_row and follows else table
                key_source = "has no column row and so stays with"
                if not table_row:
                    report.unmapped_keys[f"{table}.{key_column}"] += 1
            if key_table != mapped["table_name"]:
                raise MappingRefused(
                    f"Test {index} ({test_type} on {location}) has key column {table}.{key_column}, which "
                    f"{key_source} table {key_table}, but the test maps to table {mapped['table_name']}"
                )
            if key_row:
                _rename(mapped, "groupby_names", key_row.target_column,
                        (f"{table}.{key_column}", _qualified(key_row)), report)

        mapped_definitions.append(mapped)

    _check_collisions(column_sources, table_sources)

    present_columns = {
        (definition.get("table_name") or "", name) for definition in definitions
        for name in (definition.get("column_name") or "", _key_column(definition)) if name
    }
    report.unmatched_rows = [
        row for row in mapping.all_rows()
        if (row.source_table, row.source_column) not in present_columns
        and not (not row.source_column and row.source_table in present_tables)
    ]
    report.tests_out = len(mapped_definitions)
    mapped_document = {**document, "definitions": mapped_definitions, MARKER_KEY: marker}
    return mapped_document, report


def _check_document(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("definitions"), list):
        raise MappingRefused("Input is not a test definition export document")
    if MARKER_KEY in document:
        raise MappingRefused(
            "Input was written by this script and has already been mapped. Map the original export document."
        )
    version = document.get("version")
    if isinstance(version, bool) or version not in SUPPORTED_FORMAT_VERSIONS:
        supported = ", ".join(str(supported) for supported in sorted(SUPPORTED_FORMAT_VERSIONS))
        raise MappingRefused(f"Unsupported export document version {version!r}; supported version: {supported}")
    definitions: list[dict[str, Any]] = document["definitions"]
    if not all(isinstance(definition, dict) for definition in definitions):
        raise MappingRefused("Input is not a test definition export document: a definition is not an object")
    return definitions


def _unrewritable(definitions: list[dict[str, Any]]) -> dict[int, tuple[str, str]]:
    """Tests with fields that can embed names the script cannot rewrite: index -> (type and location, fields)."""
    problems: dict[int, tuple[str, str]] = {}
    for index, definition in enumerate(definitions):
        test_type = definition.get("test_type", "")
        fields = [name for name in UNREWRITABLE_FIELDS if _is_set(definition.get(name))]
        groupby_names = definition.get("groupby_names")
        if _is_set(groupby_names) and (
            test_type not in KEYED_HASH_TEST_TYPES or not _is_plain_name(groupby_names)
        ):
            fields.append("groupby_names")
        if fields:
            location = ".".join(filter(None, [definition.get("table_name"), definition.get("column_name")]))
            problems[index] = (f"{test_type} on {location or 'no table'}", ", ".join(fields))
    return problems


def _key_column(definition: dict[str, Any]) -> str:
    if definition.get("test_type") not in KEYED_HASH_TEST_TYPES:
        return ""
    return definition.get("groupby_names") or ""


def _drop_reason(definition: dict[str, Any], mapping: Mapping, source_tables: set[str]) -> str | None:
    """The reason the mapping drops a test, if it does.

    :param source_tables: The table names of the document's tests.
    """
    test_type = definition.get("test_type", "")
    table = definition.get("table_name") or ""
    column = definition.get("column_name") or ""
    key_column = _key_column(definition)
    table_row = mapping.table_rows.get(table)
    column_row = mapping.column_rows.get((table, column))
    key_row = mapping.column_rows.get((table, key_column))

    if table_row and table_row.target_table == DROP_ALL:
        return f"{table} mapped to DROP_ALL"
    if not column and table_row and table_row.target_table == DROP:
        return f"{table} mapped to DROP"
    if column and column_row and column_row.target_column == DROP:
        return f"{table}.{column} mapped to DROP"
    if key_column and key_row and key_row.target_column == DROP:
        return f"key column {table}.{key_column} mapped to DROP"
    if test_type == COLUMN_COUNT_TEST_TYPE:
        if table in mapping.dropped_column_tables:
            return f"a column of {table} is dropped, so the column count no longer matches"
        moved = mapping.moved_columns
        if any(source == table for source, _ in moved):
            return f"a column of {table} moves to another table, so the column count no longer matches"
        landing = mapping.landing_table(table)
        if any(target == landing and source != table for source, target in moved):
            return f"a column from another table moves into {landing}, so the column count no longer matches"
        if any(other and other != table and mapping.landing_table(other) == landing for other in source_tables):
            return f"another table also lands in {landing}, so the column count no longer matches"
    return None


def _check_collisions(
    column_sources: dict[tuple[str, str], set[tuple[str, str]]],
    table_sources: dict[str, set[str]],
) -> None:
    colliding_tables = {target: sources for target, sources in table_sources.items() if len(sources) > 1}
    errors = [f"{', '.join(sorted(sources))} -> {target}" for target, sources in sorted(colliding_tables.items())]
    implied = 0
    for (table, column), sources in sorted(column_sources.items()):
        if len(sources) < 2:
            continue
        source_tables = {source_table for source_table, _ in sources}
        if len(source_tables) > 1 and source_tables <= colliding_tables.get(table, set()):
            implied += 1
            continue
        errors.append(f"{', '.join(sorted(f'{t}.{c}' for t, c in sources))} -> {table}.{column}")
    if implied:
        errors.append(f"and {implied} column collisions between the colliding tables above")
    if errors:
        raise MappingRefused(
            "More than one source name maps to the same target name. A name with no mapping row keeps its own "
            "name, so it counts as mapped to itself:\n  " + "\n  ".join(errors)
        )


def _rename(mapped: dict[str, Any], key: str, target: str, change: tuple[str, str], report: Report) -> None:
    if mapped[key] == target:
        return
    mapped[key] = target
    renames = report.table_renames if key == "table_name" else report.column_renames
    renames[change] += 1


def _qualified(row: MappingRow) -> str:
    return f"{row.target_table}.{row.target_column}"


def _is_set(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _is_plain_name(value: Any) -> bool:
    return isinstance(value, str) and value == value.strip() and not NON_PLAIN_NAME_CHARS & set(value)


def format_report(report: Report, input_source: Path | str, mapping_path: Path) -> str:
    lines = [
        "Test transfer report",
        f"Input:   {input_source}",
        f"Mapping: {mapping_path}",
        f"Tests:   {report.tests_in} read, {report.tests_out} written, {len(report.dropped)} dropped",
    ]

    def section(title: str, entries: list[str]) -> None:
        if entries:
            lines.extend(["", f"{title} ({len(entries)})", *(f"  {entry}" for entry in entries)])

    def tests(count: int) -> str:
        return f"{count} test" if count == 1 else f"{count} tests"

    section("Tables renamed", [f"{source} -> {target}: {tests(count)}"
                               for (source, target), count in sorted(report.table_renames.items())])
    section("Columns renamed", [f"{source} -> {target}: {tests(count)}"
                                for (source, target), count in sorted(report.column_renames.items())])
    grouped = Counter(test.reason for test in report.dropped if not test.listed_individually)
    section("Tests dropped", [f"{reason}: {tests(count)}" for reason, count in grouped.items()]
            + [test.reason for test in report.dropped if test.listed_individually])
    section("Mapping rows that matched no test", [row.describe() for row in report.unmatched_rows])

    kept = []
    for table, count in sorted(report.kept.items()):
        parts = (["table-level"] if table in report.kept_table_level else []) + (
            [_plural(len(report.kept_columns[table]), "column")] if report.kept_columns[table] else [])
        kept.append(f"{table}: {tests(count)} ({' and '.join(parts)})")
    section("Tables kept as named", kept)
    section("Key columns kept as named", [f"{key}: {tests(count)}" for key, count in sorted(report.unmapped_keys.items())])
    section("Tests with no table", [f"{test_type}: {tests(count)}" for test_type, count in sorted(report.no_table.items())])
    section("Columns with no column row that follow their table's rename", [
        f"{source} -> {target}: {_plural(len(report.followed_columns[(source, target)]), 'column')}, {tests(count)}"
        for (source, target), count in sorted(report.followed.items())
    ])
    return "\n".join(lines) + "\n"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class _RefuseRedirects(HTTPRedirectHandler):
    """Refuses redirects: urllib would send the token to the redirect target and turn a POST into a GET."""

    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str  # noqa: ARG002
    ) -> None:
        raise ApiFailed(f"{req.full_url} redirected to {newurl}. Check the scheme, host, and port in --api-url.")


_opener = build_opener(_RefuseRedirects)


def _open(request: Request, timeout: float) -> Any:
    return _opener.open(request, timeout=timeout)


class ApiClient:
    """Sends requests to the TestGen REST API with a bearer token."""

    def __init__(self, api_url: str, token: str) -> None:
        self.base_url = api_url.rstrip("/").removesuffix("/api/v1")
        self._token = token

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """Sends a request and returns the parsed JSON response.

        :param path: The path below /api/v1.
        :param body: The JSON request body, if any.
        :raises ApiFailed: When the request cannot be sent, or the response is an error status or not JSON.
        """
        url = f"{self.base_url}/api/v1{path}"
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with _open(request, timeout=API_TIMEOUT_SECONDS) as response:
                text = response.read().decode("utf-8")
        except HTTPError as error:
            error_body = _parse_json(error.read())
            hint = ""
            if error.code == 404 and not _has_error_code(error_body, "not_found"):
                hint = ". Check that --api-url is the TestGen API URL, with no path"
            raise ApiFailed(
                f"{method} {url} returned HTTP {error.code}{_error_details(error_body)}{hint}", error.code, error_body
            ) from error
        except URLError as error:
            raise ApiFailed(f"Could not reach {url}: {error.reason}") from error
        except OSError as error:
            raise ApiFailed(f"Could not reach {url}: {error}") from error

        parsed = _parse_json(text.encode("utf-8"))
        if parsed is None:
            raise ApiFailed(f"{url} did not return JSON. Check that --api-url is the TestGen API URL, not the UI URL.")
        return parsed


def _parse_json(content: bytes) -> Any:
    try:
        return json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _error_details(body: Any) -> str:
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        detail = detail.get("errors")
    if isinstance(detail, list):
        detail = "; ".join(
            str(item.get("detail") or item.get("msg")) for item in detail
            if isinstance(item, dict) and (item.get("detail") or item.get("msg"))
        )
    return f": {detail}" if isinstance(detail, str) and detail else ""


def _has_error_code(body: Any, code: str) -> bool:
    """Whether an API error body carries an error with the given code."""
    detail = body.get("detail") if isinstance(body, dict) else None
    errors = detail.get("errors") if isinstance(detail, dict) else None
    return isinstance(errors, list) and any(isinstance(item, dict) and item.get("code") == code for item in errors)


def _is_not_found(error: ApiFailed) -> bool:
    """Whether the API reported a missing resource, as opposed to a URL that matches no endpoint."""
    return error.status == 404 and _has_error_code(error.body, "not_found")


def export_from_api(client: ApiClient, test_suite_id: str) -> Any:
    """Exports every test definition in a test suite."""
    try:
        return client.request("GET", f"/test-suites/{test_suite_id}/test-definition-export")
    except ApiFailed as error:
        if _is_not_found(error):
            raise ApiFailed(
                f"Test suite {test_suite_id} was not found, or the token's user cannot view it", error.status
            ) from error
        raise


def import_to_api(
    client: ApiClient, test_suite_id: str, document: dict[str, Any], apply: bool, delete_absent: bool = False
) -> tuple[dict[str, Any], bool]:
    """Previews or applies the import of a mapped document into a test suite.

    :param apply: Import with all-or-nothing semantics instead of previewing.
    :param delete_absent: Delete the destination tests that are not in the document.
    :return: The import result, and whether the import was refused because tests would be skipped.
    """
    config = {"mode": "apply_strict" if apply else "preview", **IMPORT_POLICY}
    if delete_absent:
        config["on_absence"] = "delete_all"
    body = {"config": config, "payload": document}
    try:
        return client.request("POST", f"/test-suites/{test_suite_id}/test-definition-import", body), False
    except ApiFailed as error:
        detail = error.body.get("detail") if isinstance(error.body, dict) else None
        if error.status == 400 and isinstance(detail, dict) and isinstance(detail.get("import_result"), dict):
            return detail["import_result"], True
        if _is_not_found(error):
            raise ApiFailed(
                f"Test suite {test_suite_id} was not found, or the token's user cannot edit it", error.status
            ) from error
        raise


def format_import(
    result: dict[str, Any], document: dict[str, Any], test_suite_id: str, applied: bool, refused: bool
) -> str:
    """The report section for an import preview or an applied import.

    :param document: The mapped document that was sent, to name the tests the result refers to by index.
    """
    if refused:
        title = f"Import into test suite {test_suite_id} refused: tests would be skipped, so nothing was imported"
    elif applied:
        title = f"Import into test suite {test_suite_id}"
    else:
        title = f"Import preview into test suite {test_suite_id} (nothing imported)"
    lines = ["", title, f"  {_import_counts(result, applied and not refused)}"]

    definitions = document.get("definitions") or []
    skipped: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for item in result.get("items") or []:
        if item.get("action") != "skip":
            continue
        reason = str(item.get("reason"))
        for test in item.get("tds") or []:
            index = test.get("idx")
            definition = definitions[index] if isinstance(index, int) and 0 <= index < len(definitions) else {}
            table = definition.get("table_name") or "no table"
            column = definition.get("column_name")
            location = f"{table}.{column}" if column else table
            if reason == "invalid_table":
                skipped[reason][table] += 1
            elif reason == "invalid_column":
                skipped[reason][location] += 1
            else:
                skipped[reason][f"{definition.get('test_type', 'test')} on {location}"] += 1
    if skipped:
        lines.extend(["", f"Tests skipped by the import ({sum(sum(tests.values()) for tests in skipped.values())})"])
        for reason, locations in skipped.items():
            lines.append(f"  {SKIP_REASONS.get(reason, reason)}:")
            lines.extend(f"    {location}: {_plural(count, 'test')}" for location, count in sorted(locations.items()))
    return "\n".join(lines) + "\n"


def _import_counts(result: dict[str, Any], applied: bool) -> str:
    summary = result.get("summary") or {}
    verb = "" if applied else "would be "
    counts = [
        f"{_plural(count, 'test')} {verb}{action}" for action in ("created", "updated", "skipped", "deleted")
        if (count := int(summary.get(action) or 0))
    ]
    return ", ".join(counts) if counts else "no tests to import"


def _check_paths(*paths: Path) -> None:
    for position, path in enumerate(paths):
        for other in paths[position + 1:]:
            same = path.resolve() == other.resolve() or (path.exists() and other.exists() and path.samefile(other))
            if same:
                raise MappingRefused("The mapping, input, output, and report paths must all be different files")


def _write_together(contents: dict[Path, str]) -> None:
    """Writes each file to a temporary file beside it, then moves them all into place.

    Each file gets the mode a plain open() would give it: an existing file's mode, else the default mode less the umask.
    """
    umask = os.umask(0)
    os.umask(umask)
    staged: dict[Path, Path] = {}
    try:
        for path, text in contents.items():
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as handle:
                staged[path] = Path(handle.name)
                handle.write(text)
            try:
                mode = stat.S_IMODE(path.stat().st_mode)
            except FileNotFoundError:
                mode = 0o666 & ~umask
            os.chmod(staged[path], mode)
        for path, temporary in staged.items():
            os.replace(temporary, path)
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def _read_document(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        try:
            return json.load(file)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MappingRefused(f"Input is not valid JSON: {error}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Transfer test definitions between test suites, renaming tables and columns from a mapping table."
    )
    parser.add_argument("--mapping", type=Path, required=True, help="Mapping table (CSV)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Export document to map (JSON)")
    source.add_argument("--export-from", metavar="TEST_SUITE_ID", help="Test suite to export through the API")
    parser.add_argument("--output", type=Path, required=True, help="Mapped document to write (JSON)")
    parser.add_argument("--report", type=Path, required=True, help="Change report to write (text)")
    parser.add_argument(
        "--skip-unrewritable", action="store_true",
        help="Leave out tests with fields that can contain names the script cannot rewrite, instead of refusing",
    )
    parser.add_argument(
        "--api-url",
        help=f"TestGen API URL, for --export-from and --import-to. The token is read from {API_TOKEN_VARIABLE}",
    )
    parser.add_argument(
        "--import-to", metavar="TEST_SUITE_ID",
        help="Test suite to import the mapped document into through the API. Previews the import unless --apply is set",
    )
    parser.add_argument("--apply", action="store_true", help="Import the mapped document instead of previewing")
    parser.add_argument(
        "--delete-absent", action="store_true",
        help="Also delete the destination tests that are not in the mapped document, including tests added by hand",
    )
    args = parser.parse_args(argv)
    _check_arguments(parser, args)

    client = None
    if args.export_from or args.import_to:
        token = os.environ.get(API_TOKEN_VARIABLE, "").strip()
        if not token:
            parser.error(f"--export-from and --import-to read the API token from {API_TOKEN_VARIABLE}, which is unset")
        client = ApiClient(args.api_url, token)

    try:
        _check_paths(*filter(None, [args.mapping, args.input, args.output, args.report]))
        mapping = read_mapping(args.mapping)
        if client and args.export_from:
            document = export_from_api(client, args.export_from)
            input_source = f"test suite {args.export_from} at {client.base_url}"
        else:
            document = _read_document(args.input)
            input_source = str(args.input)
        marker = {"mapping_file": args.mapping.name, "mapped_at": datetime.now(UTC).isoformat(timespec="seconds")}
        mapped_document, report = map_document(document, mapping, marker, args.skip_unrewritable)
        report_text = format_report(report, input_source, args.mapping)

        import_result: dict[str, Any] | None = None
        if client and args.import_to and not args.apply:
            import_result, _ = import_to_api(
                client, args.import_to, mapped_document, apply=False, delete_absent=args.delete_absent
            )
            report_text += format_import(import_result, mapped_document, args.import_to, applied=False, refused=False)
        _write_together({
            args.output: json.dumps(mapped_document, indent=2, ensure_ascii=False) + "\n",
            args.report: report_text,
        })
    except MappingRefused as error:
        sys.stderr.write(f"Refused: {error}\n")
        return 1
    except ApiFailed as error:
        sys.stderr.write(f"Error: {error}\n")
        return 1
    except OSError as error:
        sys.stderr.write(f"Error: {error}\n")
        return 1

    wrote = f"Wrote {args.output} ({report.tests_out} of {report.tests_in} tests) and {args.report}."
    if client is None or not args.import_to:
        sys.stdout.write(f"{wrote} Review both before importing.\n")
        return 0
    if import_result is not None:
        sys.stdout.write(
            f"{wrote} Previewed the import into test suite {args.import_to}; nothing was imported. "
            "Review both, then run the same command with --apply to import.\n"
        )
        return 0
    return _apply_import(client, args, mapped_document, report_text, wrote)


def _check_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.apply and not args.import_to:
        parser.error("--apply requires --import-to")
    if args.delete_absent and not args.import_to:
        parser.error("--delete-absent requires --import-to")
    if (args.export_from or args.import_to) and not args.api_url:
        parser.error("--export-from and --import-to require --api-url")
    if args.api_url and not (args.export_from or args.import_to):
        parser.error("--api-url is used only with --export-from or --import-to")
    if args.api_url and not args.api_url.startswith(("http://", "https://")):
        parser.error("--api-url must start with http:// or https://")
    for option, value in (("--export-from", args.export_from), ("--import-to", args.import_to)):
        if value is not None:
            try:
                UUID(value)
            except ValueError:
                parser.error(f"{option} takes a test suite ID, not {value!r}")
    if args.export_from and args.import_to and UUID(args.export_from) == UUID(args.import_to):
        parser.error("--export-from and --import-to must be different test suites")


def _apply_import(
    client: ApiClient, args: argparse.Namespace, document: dict[str, Any], report_text: str, wrote: str
) -> int:
    """Imports the mapped document after both files are written, and adds the result to the report."""
    try:
        result, refused = import_to_api(client, args.import_to, document, apply=True, delete_absent=args.delete_absent)
    except ApiFailed as error:
        # A 5xx can come from a proxy that gave up while the API went on to finish the import
        outcome = (
            "Nothing was imported." if error.status and error.status < 500
            else "The import may have run. Running the command again is safe, because it updates the same tests."
        )
        sys.stderr.write(f"{wrote}\nError: {error}. {outcome}\n")
        return 1

    section = format_import(result, document, args.import_to, applied=True, refused=refused)
    try:
        _write_together({args.report: report_text + section})
    except OSError as error:
        sys.stderr.write(f"Error: the import ran, but the report could not be updated: {error}\n{section}")
        return 1
    if refused:
        sys.stderr.write(
            f"{wrote}\nRefused: the import into test suite {args.import_to} would skip tests, so nothing was "
            f"imported. The report lists them.\n"
        )
        return 1
    sys.stdout.write(f"{wrote} Imported into test suite {args.import_to}: {_import_counts(result, True)}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
