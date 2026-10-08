"""The catalog holds one row per table, and both install paths enforce it.

``data_table_chars`` / ``data_column_chars`` are read by joining on
``(table_groups_id, table_name[, column_name])``. A second row under that identity multiplies every
such read -- score rollups, test generation, score cards -- and nothing about the write path
prevents one, so the identity carries a unique index.

A fresh install declares it in the schema; an existing one receives it from an upgrade. A database
built one way would otherwise accept rows the other rejects.
"""

import re
from pathlib import Path

import pytest

import testgen

pytestmark = pytest.mark.unit

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"
CATALOG_TABLES = {
    "data_table_chars": ("table_groups_id", "table_name"),
    "data_column_chars": ("table_groups_id", "table_name", "column_name"),
}

INDEX = re.compile(
    r"CREATE\s+(?P<unique>UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+(?P<name>\w+)\s+"
    r"ON\s+(?P<table>\w+)\s*\((?P<columns>[^)]*)\)",
    re.IGNORECASE,
)


def _indexes(sql_path: Path) -> list[tuple[bool, str, str, tuple[str, ...]]]:
    return [
        (
            bool(found.group("unique")),
            found.group("name"),
            found.group("table").lower(),
            tuple(column.strip().lower() for column in found.group("columns").split(",")),
        )
        for found in INDEX.finditer(sql_path.read_text(encoding="utf-8"))
    ]


@pytest.mark.parametrize(("table", "identity"), CATALOG_TABLES.items())
def test_a_fresh_install_makes_the_identity_unique(table, identity):
    schema = TEMPLATE_ROOT / "dbsetup" / "030_initialize_new_schema_structure.sql"
    matching = [unique for unique, _, on_table, columns in _indexes(schema)
                if on_table == table and columns == identity]

    assert matching, f"{table} has no index on {identity}"
    assert all(matching), f"{table}'s index on {identity} is not unique"


@pytest.mark.parametrize(("table", "identity"), CATALOG_TABLES.items())
def test_an_upgrade_makes_the_identity_unique(table, identity):
    declared = [
        unique
        for path in sorted((TEMPLATE_ROOT / "dbupgrade").glob("*.sql"))
        for unique, _, on_table, columns in _indexes(path)
        if on_table == table and columns == identity
    ]

    assert declared, f"no upgrade adds an index on {table} {identity}"
    assert declared[-1], f"the upgrade adding {table} {identity} does not make it unique"


@pytest.mark.parametrize("table", CATALOG_TABLES)
def test_a_fresh_install_does_not_key_the_catalog_on_its_schema(table):
    """An index led by schema_name answers a lookup nothing performs, and reads that join on the
    identity alone cannot use it."""
    schema = TEMPLATE_ROOT / "dbsetup" / "030_initialize_new_schema_structure.sql"
    keyed_on_schema = [
        name for _, name, on_table, columns in _indexes(schema)
        if on_table == table and "schema_name" in columns
    ]

    assert not keyed_on_schema, f"{table} is still indexed on schema_name by {keyed_on_schema}"
