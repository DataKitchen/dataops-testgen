#!/usr/bin/env python
"""
Test Definition Name Mapping Script

Renames tables and columns in an exported test definition document, using a mapping table, so that tests
generated on one table group can be imported into a table group whose tables or columns are named differently.
Writes the mapped document and a change report. Review both before importing the mapped document.

Runs on Python 3.11+ with the standard library only; TestGen does not need to be installed.

Usage:
    python scripts/map_test_definitions.py \
        --mapping mapping.csv \
        --input source_suite.json \
        --output mapped_suite.json \
        --report mapping_report.txt \
        [--skip-unrewritable]

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
    a name_mapping entry that marks it as this script's output.

Refusals:
    The script writes nothing and exits with status 1 when the mapping is malformed; when the input is not valid
    JSON, not an export document of a supported format version, or this script's own output; when a test carries a
    field it cannot rewrite (unless --skip-unrewritable); when two source names would land on the same target name;
    when a keyed-hash test's key column would land on a different table than the test; or when the mapping, input,
    output, and report paths are not all different files.
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

SUPPORTED_FORMAT_VERSIONS = {1}
MARKER_KEY = "name_mapping"

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


def format_report(report: Report, input_path: Path, mapping_path: Path) -> str:
    lines = [
        "Test definition name mapping report",
        f"Input:   {input_path}",
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
    kept += [f"key column {key}: {tests(count)}" for key, count in sorted(report.unmapped_keys.items())]
    kept += [f"{test_type} with no table: {tests(count)}" for test_type, count in sorted(report.no_table.items())]
    section("Tables kept as named", kept)
    section("Columns with no column row that follow their table's rename", [
        f"{source} -> {target}: {_plural(len(report.followed_columns[(source, target)]), 'column')}, {tests(count)}"
        for (source, target), count in sorted(report.followed.items())
    ])
    return "\n".join(lines) + "\n"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


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
        description="Rename tables and columns in a test definition export document from a mapping table."
    )
    parser.add_argument("--mapping", type=Path, required=True, help="Mapping table (CSV)")
    parser.add_argument("--input", type=Path, required=True, help="Export document to map (JSON)")
    parser.add_argument("--output", type=Path, required=True, help="Mapped document to write (JSON)")
    parser.add_argument("--report", type=Path, required=True, help="Change report to write (text)")
    parser.add_argument(
        "--skip-unrewritable", action="store_true",
        help="Leave out tests with fields that can contain names the script cannot rewrite, instead of refusing",
    )
    args = parser.parse_args(argv)

    try:
        _check_paths(args.mapping, args.input, args.output, args.report)
        mapping = read_mapping(args.mapping)
        document = _read_document(args.input)
        marker = {"mapping_file": args.mapping.name, "mapped_at": datetime.now(UTC).isoformat(timespec="seconds")}
        mapped_document, report = map_document(document, mapping, marker, args.skip_unrewritable)
        _write_together({
            args.output: json.dumps(mapped_document, indent=2, ensure_ascii=False) + "\n",
            args.report: format_report(report, args.input, args.mapping),
        })
    except MappingRefused as error:
        sys.stderr.write(f"Refused: {error}\n")
        return 1
    except OSError as error:
        sys.stderr.write(f"Error: {error}\n")
        return 1

    sys.stdout.write(
        f"Wrote {args.output} ({report.tests_out} of {report.tests_in} tests) and {args.report}. "
        "Review both before importing.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
