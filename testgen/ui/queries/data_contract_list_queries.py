# testgen/ui/queries/data_contract_list_queries.py
"""
Queries for the DataContractsListPage and Create Contract wizard.
"""
from __future__ import annotations

from typing import Any

from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import fetch_dict_from_db
from testgen.common.models import with_database_session


@with_database_session
def fetch_contracts_for_project(project_code: str) -> list[dict[str, Any]]:
    """
    Return all contracts for a project with current version info and run status.

    Status derivation per card:
    - Any Failed/Error result in latest run → 'Failing'
    - Any Warning (no Failed/Error) → 'Warning'
    - All Passed → 'Passing'
    - No results found → 'No Run'
    """
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"""
        SELECT
            c.id::text                   AS contract_id,
            c.name,
            c.is_active,
            c.created_at,
            c.table_group_id::text,
            tg.table_groups_name         AS table_group_name,
            COALESCE(cv.version, -1)     AS version,
            COALESCE(cv.term_count, 0)   AS term_count,
            cv.saved_at,
            COALESCE(vc.version_count, 0) AS version_count,
            COALESCE(tc.test_count, 0)   AS test_count,
            CASE
                WHEN COALESCE(rs.has_failed, FALSE)  THEN 'Failing'
                WHEN COALESCE(rs.has_warning, FALSE) THEN 'Warning'
                WHEN COALESCE(rs.has_passed, FALSE)  THEN 'Passing'
                ELSE 'No Run'
            END                          AS status
          FROM {schema}.contracts c
          JOIN {schema}.table_groups tg
            ON tg.id = c.table_group_id
          LEFT JOIN {schema}.contract_versions cv
            ON cv.contract_id = c.id AND cv.is_current = TRUE
          LEFT JOIN (
              SELECT contract_id, COUNT(*) AS version_count
                FROM {schema}.contract_versions
               GROUP BY contract_id
          ) vc ON vc.contract_id = c.id
          LEFT JOIN (
              SELECT ts.id AS suite_id, COUNT(td.id) AS test_count
                FROM {schema}.test_suites ts
                JOIN {schema}.test_definitions td
                  ON td.test_suite_id = ts.id AND td.test_active = 'Y'
               GROUP BY ts.id
          ) tc ON tc.suite_id = c.test_suite_id
          LEFT JOIN LATERAL (
              SELECT
                  BOOL_OR(tr.result_status IN ('Failed','Error'))  AS has_failed,
                  BOOL_OR(tr.result_status = 'Warning')            AS has_warning,
                  BOOL_AND(tr.result_status = 'Passed')            AS has_passed
                FROM {schema}.test_runs run
                JOIN {schema}.test_results tr ON tr.test_run_id = run.id
               WHERE run.test_suite_id = c.test_suite_id
                 AND run.test_starttime = (
                     SELECT MAX(test_starttime)
                       FROM {schema}.test_runs
                      WHERE test_suite_id = c.test_suite_id
                 )
          ) rs ON TRUE
         WHERE c.project_code = :project_code
         ORDER BY tg.table_groups_name, c.name
        """,
        params={"project_code": project_code},
    )
    return [dict(r) for r in rows]


@with_database_session
def fetch_table_groups_for_project(project_code: str) -> list[dict[str, Any]]:
    """Return table groups with contract count for wizard Step 1."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"""
        SELECT tg.id::text,
               tg.table_groups_name,
               tg.project_code,
               COALESCE(tc.table_count, 0) AS table_count,
               COALESCE(pc.profile_date, NULL) AS last_profiling_date,
               COALESCE(cc.contract_count, 0) AS contract_count
          FROM {schema}.table_groups tg
          LEFT JOIN (
              SELECT table_groups_id, COUNT(DISTINCT table_name) AS table_count
                FROM {schema}.data_column_chars GROUP BY table_groups_id
          ) tc ON tc.table_groups_id = tg.id
          LEFT JOIN (
              SELECT table_groups_id, MAX(profiling_starttime) AS profile_date
                FROM {schema}.profiling_runs WHERE status = 'Complete' GROUP BY table_groups_id
          ) pc ON pc.table_groups_id = tg.id
          LEFT JOIN (
              SELECT table_group_id, COUNT(*) AS contract_count
                FROM {schema}.contracts GROUP BY table_group_id
          ) cc ON cc.table_group_id = tg.id
         WHERE tg.project_code = :project_code
         ORDER BY tg.table_groups_name
        """,
        params={"project_code": project_code},
    )
    return [dict(r) for r in rows]


@with_database_session
def fetch_eligible_suites_for_wizard(table_group_id: str) -> list[dict[str, Any]]:
    """Return non-monitor, non-snapshot, non-contract-primary suites for wizard Step 2."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"""
        SELECT ts.id::text, ts.test_suite AS name,
               COUNT(td.id) AS active_test_count
          FROM {schema}.test_suites ts
          LEFT JOIN {schema}.test_definitions td
            ON td.test_suite_id = ts.id AND td.test_active = 'Y'
         WHERE ts.table_groups_id = CAST(:tg_id AS uuid)
           AND COALESCE(ts.is_monitor, FALSE) = FALSE
           AND COALESCE(ts.is_contract_snapshot, FALSE) = FALSE
           AND COALESCE(ts.is_contract_suite, FALSE) = FALSE
         GROUP BY ts.id, ts.test_suite
         ORDER BY ts.test_suite
        """,
        params={"tg_id": table_group_id},
    )
    return [dict(r) for r in rows]


@with_database_session
def fetch_tables_for_wizard(table_group_id: str) -> list[dict[str, Any]]:
    """Return distinct profiled tables for wizard Step 3."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"""
        SELECT DISTINCT dcc.table_name,
               COUNT(td.id) AS active_test_count
          FROM {schema}.data_column_chars dcc
          LEFT JOIN {schema}.test_definitions td
            ON td.table_name = dcc.table_name
           AND td.test_active = 'Y'
          LEFT JOIN {schema}.test_suites ts
            ON ts.id = td.test_suite_id
           AND ts.table_groups_id = CAST(:tg_id AS uuid)
         WHERE dcc.table_groups_id = CAST(:tg_id AS uuid)
         GROUP BY dcc.table_name
         ORDER BY dcc.table_name
        """,
        params={"tg_id": table_group_id},
    )
    return [dict(r) for r in rows]


@with_database_session
def count_in_scope_tests(
    suite_ids: list[str],
    table_names: list[str],
    table_group_id: str,
    include_monitors: bool,
) -> int:
    """Count active tests in scope for wizard Step 5 preview."""
    schema = get_tg_schema()
    if not suite_ids and not include_monitors:
        return 0

    parts: list[str] = []
    params: dict[str, Any] = {}

    if suite_ids:
        id_placeholders = ", ".join(f"CAST(:sid_{i} AS uuid)" for i, _ in enumerate(suite_ids))
        for i, sid in enumerate(suite_ids):
            params[f"sid_{i}"] = sid
        tbl_filter = ""
        if table_names:
            tbl_placeholders = ", ".join(f":tbl_{i}" for i, _ in enumerate(table_names))
            for i, t in enumerate(table_names):
                params[f"tbl_{i}"] = t
            tbl_filter = f"AND td.table_name IN ({tbl_placeholders})"
        parts.append(f"""
            SELECT COUNT(td.id)
              FROM {schema}.test_definitions td
             WHERE td.test_suite_id IN ({id_placeholders})
               AND td.test_active = 'Y'
               {tbl_filter}
        """)

    if include_monitors:
        params["tg_id"] = table_group_id
        parts.append(f"""
            SELECT COUNT(td.id)
              FROM {schema}.test_definitions td
              JOIN {schema}.test_suites ts ON ts.id = td.test_suite_id
             WHERE ts.table_groups_id = CAST(:tg_id AS uuid)
               AND COALESCE(ts.is_monitor, FALSE) = TRUE
               AND td.test_active = 'Y'
        """)

    if not parts:
        return 0

    union_sql = " UNION ALL ".join(f"SELECT ct FROM ({p}) AS sub{i}(ct)" for i, p in enumerate(parts))
    rows = fetch_dict_from_db(f"SELECT SUM(ct) AS total FROM ({union_sql}) AS combined", params=params)
    if not rows:
        return 0
    return int(rows[0].get("total") or 0)


@with_database_session
def is_contract_name_taken(name: str, project_code: str) -> bool:
    """Return True if a contract with this name already exists in the project."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"SELECT 1 FROM {schema}.contracts WHERE name = :name AND project_code = :project_code LIMIT 1",
        params={"name": name, "project_code": project_code},
    )
    return bool(rows)
