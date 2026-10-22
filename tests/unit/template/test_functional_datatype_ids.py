"""ID functional types assigned by functional_datatype.sql, run against a minimal profile_results."""

import re
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import duckdb
import pytest

from testgen.commands.queries.profiling_query import ProfilingSQL

pytestmark = pytest.mark.unit

# The statements that assign ID types, in template order. Each is matched by its SET line.
ID_STATEMENTS = (
    "SET functional_data_type = 'ID-SK'\n",
    "SET functional_data_type = 'ID'\n",
    "SET functional_data_type = CASE\n",
    "SET functional_data_type = 'ID-Unique'\n",
    "SET functional_data_type = 'ID-Unique-SK'\n",
    "SET functional_data_type = 'ID-FK'\n",
)


def _id_statements(id_mask: str | None) -> tuple[list[str], dict]:
    table_group = MagicMock(
        project_code="P",
        id=uuid4(),
        table_group_schema="s",
        profile_id_column_mask=id_mask,
        profile_sk_column_mask="%_sk",
    )
    profiling_run = MagicMock(id=uuid4(), profiling_starttime=datetime(2026, 1, 1, tzinfo=UTC))
    connection = MagicMock(sql_flavor="postgresql", sql_flavor_code="postgresql", connection_id=1)
    query, params = ProfilingSQL(connection, table_group, profiling_run)._get_query("functional_datatype.sql")

    statements = query.split(";")
    selected = []
    for marker in ID_STATEMENTS:
        matching = [statement for statement in statements if marker in statement and "UPDATE profile_results" in statement]
        assert len(matching) == 1, f"expected one statement setting {marker.strip()}"
        # DuckDB names its parameters with $ where the app database takes :, and its ILIKE has no
        # default escape character where the app database's escapes with a backslash
        statement = re.sub(r"(?<!:):([A-Z_]+)\b", r"$\1", matching[0])
        selected.append(re.sub(r"(ILIKE \$[A-Z_]+)", r"\1 ESCAPE '\\'", statement))
    return selected, params


def _profile(columns: list[tuple[str, str, int, int]], id_mask: str | None) -> dict[tuple[str, str], str | None]:
    """Run the ID statements over (table, column, record count, distinct count) rows."""
    statements, params = _id_statements(id_mask)
    run_id, table_groups_id = params["PROFILE_RUN_ID"], params["TABLE_GROUPS_ID"]
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE profile_results (profile_run_id UUID, table_groups_id UUID, table_name VARCHAR, "
        "column_name VARCHAR, functional_data_type VARCHAR, record_ct BIGINT, value_ct BIGINT, "
        "distinct_value_ct BIGINT)"
    )
    con.executemany(
        "INSERT INTO profile_results VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
        [(run_id, table_groups_id, table, column, record_ct, record_ct, distinct_ct)
         for table, column, record_ct, distinct_ct in columns],
    )
    for statement in statements:
        used = {name: params[name] for name in re.findall(r"\$([A-Z_]+)", statement)}
        con.execute(statement, used)
    return {
        (table, column): functional_type
        for table, column, functional_type in con.execute(
            "SELECT table_name, column_name, functional_data_type FROM profile_results"
        ).fetchall()
    }


def test_a_small_tables_id_column_is_not_a_reference_to_another_tables_id():
    types = _profile(
        [
            ("customers", "id", 100, 100),
            ("status_codes", "id", 10, 10),
            ("orders", "customer_id", 100, 100),
            ("payments", "customer_id", 40, 30),
        ],
        id_mask="%_id",
    )

    assert types[("customers", "id")] == "ID-Unique"
    assert types[("status_codes", "id")] == "ID-Secondary"
    # Any other column that shares a unique ID's name still reads as a reference to it
    assert types[("orders", "customer_id")] == "ID-Unique"
    assert types[("payments", "customer_id")] == "ID-FK"


@pytest.mark.parametrize("column_name", ["id", "ID", "Id"])
def test_a_column_named_id_is_an_id_while_the_id_mask_is_set(column_name):
    types = _profile([("customers", column_name, 100, 100)], id_mask="%_id")

    assert types[("customers", column_name)] == "ID-Unique"


@pytest.mark.parametrize("id_mask", [None, ""])
def test_a_column_named_id_is_not_an_id_without_an_id_mask(id_mask):
    types = _profile([("customers", "id", 100, 100)], id_mask=id_mask)

    assert types[("customers", "id")] is None
