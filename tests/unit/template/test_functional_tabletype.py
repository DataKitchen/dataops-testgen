"""The functional table type profiling stages for each table, run in DuckDB.

DuckDB stands in for the application database's PostgreSQL: the staging query and the
profile_results update use only window functions, CASE, and CONCAT_WS, which both read alike.
"""

import duckdb
import pytest

from testgen.common.read_file import read_template_sql_file

pytestmark = pytest.mark.unit

RUN_ID = "00000000-0000-0000-0000-000000000003"
EARLIER_RUN_ID = "00000000-0000-0000-0000-000000000001"
TABLE_GROUP_ID = "00000000-0000-0000-0000-0000000000aa"
FUNCTIONAL_DATA_TYPES = ("ID-Unique", "Measure", "Transactional Date")


def _render(sql: str) -> str:
    return (
        sql.replace(":PROFILE_RUN_ID", f"'{RUN_ID}'")
        .replace(":TABLE_GROUPS_ID", f"'{TABLE_GROUP_ID}'")
        .replace(":RUN_DATE", "TIMESTAMP '2026-01-03'")
    )


def _profile_results_update() -> str:
    statements = read_template_sql_file("functional_tabletype_update.sql", "profiling").split(";")
    return next(statement for statement in statements if "UPDATE profile_results" in statement)


def _table_types(history: dict[str, list[tuple[str, int]]]) -> dict[str, str | None]:
    """Profile each table at the given (run id, record count) pairs, earliest first, and return the
    functional table type the latest run's rows carry."""
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE stg_functional_table_updates (project_code VARCHAR, schema_name VARCHAR,"
        " run_date TIMESTAMP, table_name VARCHAR, table_period VARCHAR, table_type VARCHAR, profile_run_id UUID)"
    )
    con.execute(
        "CREATE TABLE profile_results (project_code VARCHAR, schema_name VARCHAR, table_name VARCHAR,"
        " run_date TIMESTAMP, record_ct INTEGER, functional_data_type VARCHAR, functional_table_type VARCHAR,"
        " table_groups_id UUID, profile_run_id UUID)"
    )
    for table_name, runs in history.items():
        for day, (run_id, record_ct) in enumerate(runs, start=1):
            for functional_data_type in FUNCTIONAL_DATA_TYPES:
                con.execute(
                    "INSERT INTO profile_results VALUES ('P', 's', ?, ?, ?, ?, NULL, ?, ?)",
                    [table_name, f"2026-01-0{day}", record_ct, functional_data_type, TABLE_GROUP_ID, run_id],
                )

    con.execute(_render(read_template_sql_file("functional_tabletype_stage.sql", "profiling")))
    con.execute(_render(_profile_results_update()))

    return dict(con.execute(
        "SELECT DISTINCT table_name, functional_table_type FROM profile_results WHERE profile_run_id = ?",
        [RUN_ID],
    ).fetchall())


def test_a_table_profiled_once_gets_its_table_type_without_a_period():
    assert _table_types({"orders": [(RUN_ID, 100)]}) == {"orders": "transaction"}


@pytest.mark.parametrize(("counts", "expected"), [
    ((10, 20), "cumulative-transaction"),
    ((5, 5), "cumulative-transaction"),
    ((30, 20), "window-transaction"),
], ids=["growing", "constant", "shrinking"])
def test_a_table_with_an_earlier_run_gets_a_period_from_its_record_counts(counts, expected):
    earlier, latest = counts

    types = _table_types({"orders": [(EARLIER_RUN_ID, earlier), (RUN_ID, latest)]})

    assert types == {"orders": expected}
