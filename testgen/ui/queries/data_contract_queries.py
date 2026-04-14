"""
Data Contract — database query and write helpers.

All functions in this module own the SQL side of the data contract feature.
They use @with_database_session and the common DB utilities so they can be
imported by the view, the CLI, and tests without pulling in Streamlit.
"""
from __future__ import annotations

import io
import logging

from testgen.commands.export_data_contract import run_export_data_contract
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import execute_db_queries, fetch_dict_from_db
from testgen.common.models import with_database_session
from testgen.ui.queries.profiling_queries import COLUMN_GOVERNANCE_FIELDS, TAG_FIELDS

_log = logging.getLogger(__name__)

# Complete label → (db_column, null/reset value) for all deletable governance terms.
# Bool fields reset to False; string/enum fields reset to None.
_BOOL_GOV_DB_FIELDS: frozenset[str] = frozenset({"critical_data_element", "excluded_data_element"})
_GOVERNANCE_LABEL_TO_FIELD: dict[str, tuple[str, object]] = {
    "Critical Data Element": ("critical_data_element", False),
    "Excluded Data Element": ("excluded_data_element", False),
    "PII":                   ("pii_flag",              None),
    "Description":           ("description",           None),
    # aliases used by single-term delete dialog
    "CDE":                   ("critical_data_element", False),
    "Classification":        ("pii_flag",              None),
    **{label: (col_key, None) for label, col_key in [
        ("Data Source",       "data_source"),
        ("Source System",     "source_system"),
        ("Source Process",    "source_process"),
        ("Business Domain",   "business_domain"),
        ("Stakeholder Group", "stakeholder_group"),
        ("Transform Level",   "transform_level"),
        ("Aggregation Level", "aggregation_level"),
        ("Data Product",      "data_product"),
    ]},
}


# ---------------------------------------------------------------------------
# YAML export wrapper
# ---------------------------------------------------------------------------

@with_database_session
def _capture_yaml(table_group_id: str, buf: io.StringIO) -> None:
    """Export the current contract YAML for a table group into *buf*."""
    run_export_data_contract(table_group_id, output_path=None, output_stream=buf)


# ---------------------------------------------------------------------------
# Read queries
# ---------------------------------------------------------------------------

@with_database_session
def _fetch_anomalies(table_group_id: str) -> list[dict]:
    schema = get_tg_schema()
    sql = f"""
        SELECT
            r.table_name,
            r.column_name,
            t.anomaly_type,
            t.anomaly_name,
            t.anomaly_description,
            t.issue_likelihood,
            t.dq_dimension,
            t.suggested_action,
            r.detail,
            r.disposition
        FROM {schema}.profile_anomaly_results r
        INNER JOIN {schema}.profile_anomaly_types t ON r.anomaly_id = t.id
        WHERE r.table_groups_id = :tg_id
          AND r.profile_run_id = (
              SELECT id FROM {schema}.profiling_runs
              WHERE  table_groups_id = :tg_id
                AND  status = 'Complete'
              ORDER  BY profiling_starttime DESC
              LIMIT  1
          )
          AND COALESCE(r.disposition, 'Confirmed') != 'Inactive'
        ORDER BY
            CASE t.issue_likelihood
                WHEN 'Definite' THEN 1 WHEN 'Likely' THEN 2 WHEN 'Possible' THEN 3 ELSE 4
            END,
            r.table_name, r.column_name
    """
    try:
        return [dict(row) for row in fetch_dict_from_db(sql, params={"tg_id": table_group_id})]
    except Exception:
        _log.warning("_fetch_anomalies failed for tg_id=%s", table_group_id, exc_info=True)
        return []


@with_database_session
def _fetch_suite_scope(table_group_id: str, snapshot_suite_id: str | None = None) -> dict:
    """Return which test suites are included/excluded from the contract.

    When *snapshot_suite_id* is provided the result is scoped exclusively to
    that snapshot suite, which is the authoritative source of truth for a
    versioned contract snapshot.
    """
    schema = get_tg_schema()
    if snapshot_suite_id:
        sql = f"""
            SELECT test_suite, TRUE AS include_in_contract
            FROM {schema}.test_suites
            WHERE id = CAST(:snapshot_suite_id AS uuid)
        """
        params: dict = {"snapshot_suite_id": snapshot_suite_id}
    else:
        sql = f"""
            SELECT test_suite, COALESCE(include_in_contract, TRUE) AS include_in_contract
            FROM {schema}.test_suites
            WHERE table_groups_id = :tg_id
              AND is_monitor IS NOT TRUE
              AND is_contract_snapshot IS NOT TRUE
            ORDER BY LOWER(test_suite)
        """
        params = {"tg_id": table_group_id}
    try:
        rows = fetch_dict_from_db(sql, params=params)
        included = [r["test_suite"] for r in rows if r["include_in_contract"]]
        excluded = [r["test_suite"] for r in rows if not r["include_in_contract"]]
        return {"included": included, "excluded": excluded, "total": len(rows)}
    except Exception:
        _log.warning("_fetch_suite_scope failed for tg_id=%s", table_group_id, exc_info=True)
        return {"included": [], "excluded": [], "total": 0}


@with_database_session
def _fetch_governance_data(table_group_id: str) -> dict[tuple[str, str], dict]:
    """Return governance metadata keyed by (table_name, col_name) from data_column_chars."""
    schema = get_tg_schema()
    sql = f"""
        SELECT
            column_id::text AS column_id,
            table_name,
            column_name,
            critical_data_element,
            excluded_data_element,
            pii_flag,
            description,
            data_source,
            source_system,
            source_process,
            business_domain,
            stakeholder_group,
            transform_level,
            aggregation_level,
            data_product
        FROM {schema}.data_column_chars
        WHERE table_groups_id = :tg_id
    """
    try:
        rows = fetch_dict_from_db(sql, params={"tg_id": table_group_id})
        return {(r["table_name"], r["column_name"]): dict(r) for r in (rows or [])}
    except Exception:
        _log.warning("_fetch_governance_data failed for tg_id=%s", table_group_id, exc_info=True)
        return {}


@with_database_session
def _lookup_column_id(table_group_id: str, table_name: str, col_name: str) -> str:
    """Return the column_id UUID string for a given table/column, or '' if not found."""
    schema = get_tg_schema()
    sql = f"""
        SELECT column_id::text AS column_id
        FROM {schema}.data_column_chars
        WHERE table_groups_id = :tg_id
          AND table_name = :tbl
          AND column_name = :col
        LIMIT 1
    """
    try:
        rows = fetch_dict_from_db(sql, params={"tg_id": table_group_id, "tbl": table_name, "col": col_name})
        return (rows[0]["column_id"] or "") if rows else ""
    except Exception:
        _log.warning("_lookup_column_id failed", exc_info=True)
        return ""


@with_database_session
def _fetch_test_live_info(test_def_id: str) -> dict:
    """Return live suite_id, status, last run timestamp, test name, and descriptions."""
    schema = get_tg_schema()
    sql = f"""
        SELECT
            td.test_suite_id::text          AS suite_id,
            td.test_description             AS user_description,
            tt.test_name_short,
            tt.test_name_long,
            tt.test_description             AS type_description,
            tr.result_status,
            tr.test_time
        FROM {schema}.test_definitions td
        LEFT JOIN {schema}.test_types tt ON tt.test_type = td.test_type
        LEFT JOIN LATERAL (
            SELECT result_status, test_time
            FROM   {schema}.test_results
            WHERE  test_definition_id = td.id
              AND  disposition IS DISTINCT FROM 'Inactive'
            ORDER  BY test_time DESC
            LIMIT  1
        ) tr ON TRUE
        WHERE td.id = :tid
        LIMIT 1
    """
    try:
        rows = fetch_dict_from_db(sql, params={"tid": test_def_id})
        if not rows:
            return {}
        row = dict(rows[0])
        status_map = {"Passed": "passing", "Failed": "failing", "Warning": "warning", "Error": "error"}
        return {
            "suite_id":         row.get("suite_id") or "",
            "status":           status_map.get(row.get("result_status") or "", "") or "",
            "test_time":        row.get("test_time"),
            "test_name_short":  row.get("test_name_short") or "",
            "test_name_long":   row.get("test_name_long") or "",
            "user_description": row.get("user_description") or "",
            "type_description": row.get("type_description") or "",
        }
    except Exception:
        _log.warning("_fetch_test_live_info failed for test_def_id=%s", test_def_id, exc_info=True)
        return {}


@with_database_session
def _fetch_test_statuses(table_group_id: str, snapshot_suite_id: str | None = None) -> dict[str, str]:
    """Return {test_def_id: odcs_status} for the latest result of every active test in the contract.

    When *snapshot_suite_id* is provided the query is scoped exclusively to that suite,
    which is the authoritative source of truth for a versioned contract snapshot.
    """
    schema = get_tg_schema()
    if snapshot_suite_id:
        sql = f"""
            SELECT DISTINCT ON (COALESCE(td.source_test_definition_id, td.id))
                COALESCE(td.source_test_definition_id, td.id)::text                   AS test_def_id,
                CASE tr.result_status
                    WHEN 'Passed'  THEN 'passing'
                    WHEN 'Failed'  THEN 'failing'
                    WHEN 'Warning' THEN 'warning'
                    WHEN 'Error'   THEN 'error'
                    ELSE NULL
                END                                                                   AS status
            FROM {schema}.test_definitions td
            LEFT JOIN {schema}.test_results tr ON tr.test_definition_id = td.id
                                              AND tr.disposition IS DISTINCT FROM 'Inactive'
            WHERE td.test_suite_id = CAST(:snapshot_suite_id AS uuid)
              AND td.test_active   = 'Y'
            ORDER BY COALESCE(td.source_test_definition_id, td.id), tr.test_time DESC NULLS LAST
        """
        params: dict = {"snapshot_suite_id": snapshot_suite_id}
    else:
        sql = f"""
            SELECT DISTINCT ON (td.id)
                td.id::text                                                           AS test_def_id,
                CASE tr.result_status
                    WHEN 'Passed'  THEN 'passing'
                    WHEN 'Failed'  THEN 'failing'
                    WHEN 'Warning' THEN 'warning'
                    WHEN 'Error'   THEN 'error'
                    ELSE NULL
                END                                                                   AS status
            FROM {schema}.test_definitions td
            JOIN {schema}.test_suites s      ON s.id  = td.test_suite_id
            LEFT JOIN {schema}.test_results tr ON tr.test_definition_id = td.id
                                              AND tr.disposition IS DISTINCT FROM 'Inactive'
            WHERE s.table_groups_id        = :tg_id
              AND s.include_in_contract    IS NOT FALSE
              AND COALESCE(s.is_monitor, FALSE) = FALSE
              AND COALESCE(s.is_contract_snapshot, FALSE) = FALSE
              AND td.test_active           = 'Y'
            ORDER BY td.id, tr.test_time DESC NULLS LAST
        """
        params = {"tg_id": table_group_id}
    try:
        rows = fetch_dict_from_db(sql, params=params)
        return {r["test_def_id"]: r["status"] for r in (rows or []) if r["status"]}
    except Exception:
        _log.exception("_fetch_test_statuses failed for tg_id=%s", table_group_id)
        return {}


@with_database_session
def _fetch_last_run_dates(table_group_id: str, snapshot_suite_id: str | None = None) -> dict:
    """Return last test run dates and per-suite run summaries.

    When *snapshot_suite_id* is provided the query is scoped exclusively to
    that snapshot suite, which is the authoritative source of truth for a
    versioned contract snapshot.
    """
    schema = get_tg_schema()

    if snapshot_suite_id:
        suite_sql = f"""
            SELECT
                suite_id,
                suite_name,
                is_monitor,
                run_id,
                run_start,
                test_ct,
                passed_ct,
                warning_ct,
                failed_ct,
                error_ct
            FROM (
                SELECT DISTINCT ON (s.id)
                    s.id::text                    AS suite_id,
                    s.test_suite                  AS suite_name,
                    COALESCE(s.is_monitor, FALSE) AS is_monitor,
                    tr.id::text                   AS run_id,
                    tr.test_starttime             AS run_start,
                    COALESCE(tr.test_ct,    0)    AS test_ct,
                    COALESCE(tr.passed_ct,  0)    AS passed_ct,
                    COALESCE(tr.warning_ct, 0)    AS warning_ct,
                    COALESCE(tr.failed_ct,  0)    AS failed_ct,
                    COALESCE(tr.error_ct,   0)    AS error_ct
                FROM {schema}.test_suites s
                JOIN {schema}.test_runs tr ON tr.test_suite_id = s.id
                WHERE s.id = CAST(:snapshot_suite_id AS uuid)
                ORDER BY s.id, tr.test_starttime DESC
            ) latest
            ORDER BY is_monitor ASC, run_start DESC
        """
        suite_params: dict = {"snapshot_suite_id": snapshot_suite_id}
    else:
        suite_sql = f"""
            SELECT
                suite_id,
                suite_name,
                is_monitor,
                run_id,
                run_start,
                test_ct,
                passed_ct,
                warning_ct,
                failed_ct,
                error_ct
            FROM (
                SELECT DISTINCT ON (s.id)
                    s.id::text                    AS suite_id,
                    s.test_suite                  AS suite_name,
                    COALESCE(s.is_monitor, FALSE) AS is_monitor,
                    tr.id::text                   AS run_id,
                    tr.test_starttime             AS run_start,
                    COALESCE(tr.test_ct,    0)    AS test_ct,
                    COALESCE(tr.passed_ct,  0)    AS passed_ct,
                    COALESCE(tr.warning_ct, 0)    AS warning_ct,
                    COALESCE(tr.failed_ct,  0)    AS failed_ct,
                    COALESCE(tr.error_ct,   0)    AS error_ct
                FROM {schema}.test_suites s
                JOIN {schema}.test_runs tr ON tr.test_suite_id = s.id
                WHERE s.table_groups_id = :tg_id
                  AND s.include_in_contract IS NOT FALSE
                  AND COALESCE(s.is_contract_snapshot, FALSE) = FALSE
                ORDER BY s.id, tr.test_starttime DESC
            ) latest
            ORDER BY is_monitor ASC, run_start DESC
        """
        suite_params = {"tg_id": table_group_id}

    profiling_sql = f"""
        SELECT id, profiling_starttime
        FROM {schema}.profiling_runs
        WHERE table_groups_id = :tg_id
          AND status = 'Complete'
        ORDER BY profiling_starttime DESC
        LIMIT 1
    """

    try:
        suite_rows = fetch_dict_from_db(suite_sql, params=suite_params)
        pr_rows    = fetch_dict_from_db(profiling_sql, params={"tg_id": table_group_id})
    except Exception:
        _log.exception("_fetch_last_run_dates failed for tg_id=%s", table_group_id)
        return {}

    all_runs   = [dict(r) for r in (suite_rows or [])]
    suite_runs = [r for r in all_runs if not r.get("is_monitor")]
    _log.debug(
        "_fetch_last_run_dates: tg_id=%s all_runs=%d suite_runs=%d totals=%s",
        table_group_id, len(all_runs), len(suite_runs),
        [(r["suite_name"], r.get("test_ct")) for r in suite_runs],
    )

    nav_run = (suite_runs or all_runs or [None])[0]
    result: dict = {
        "suite_runs":            suite_runs,
        "last_profiling_run_id": None,
        "last_profiling_run":    None,
        "last_test_run_id":      nav_run["run_id"]    if nav_run else None,
        "last_test_run":         nav_run["run_start"] if nav_run else None,
    }

    if pr_rows:
        pr = dict(pr_rows[0])
        result["last_profiling_run_id"] = str(pr["id"]) if pr.get("id") else None
        result["last_profiling_run"]    = pr.get("profiling_starttime")

    return result


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

@with_database_session
def _save_governance_data(column_id: str, updates: dict) -> None:
    """Persist governance field updates to data_column_chars."""
    if not column_id:
        _log.warning("_save_governance_data called with empty column_id — skipping")
        return
    schema     = get_tg_schema()
    set_clauses: list[str] = []
    params: dict = {"col_id": column_id}
    bool_fields  = {"critical_data_element", "excluded_data_element"}
    for key, val in updates.items():
        if key not in COLUMN_GOVERNANCE_FIELDS:
            _log.warning("_save_governance_data: ignoring unknown field %r", key)
            continue
        if key in bool_fields:
            set_clauses.append(f"{key} = :{key}")
            params[key] = val
        elif key == "pii_flag":
            set_clauses.append(f"{key} = :{key}")
            params[key] = val  # None or string
        else:
            set_clauses.append(f"{key} = NULLIF(:{key}, '')")
            params[key] = val or ""
    if not set_clauses:
        return
    sql = (
        f"UPDATE {schema}.data_column_chars "
        f"SET {', '.join(set_clauses)} "
        f"WHERE column_id = CAST(:col_id AS uuid)"
    )
    execute_db_queries([(sql, params)])


@with_database_session
def _persist_pending_edits(table_group_id: str, pending: dict) -> None:
    """Apply all pending governance and test edits to the database.

    Called when the user saves a new contract version so that the DB reflects
    every in-memory edit captured during the session.
    """
    from testgen.commands.odcs_contract import _ALLOWED_TEST_UPDATE_COLS as _ALLOWED_TEST_COLS

    schema = get_tg_schema()

    # 1. Governance edits → data_column_chars
    for e in pending.get("governance", []):
        mapping = _GOVERNANCE_LABEL_TO_FIELD.get(e["field"])
        if not mapping:
            continue
        db_col, _ = mapping
        raw_val = e["value"]
        db_val: object = bool(raw_val) if db_col == "critical_data_element" else raw_val
        execute_db_queries([(
            f"UPDATE {schema}.data_column_chars SET {db_col} = :val "
            "WHERE table_groups_id = CAST(:tg_id AS uuid) AND table_name = :tbl AND column_name = :col",
            {"val": db_val, "tg_id": table_group_id, "tbl": e["table"], "col": e["col"]},
        )])

    # 2. Test edits → test_definitions
    for e in pending.get("tests", []):
        rule_id = e["rule_id"]
        updates = {k: v for k, v in e.items() if k != "rule_id"}
        safe_updates = {k: v for k, v in updates.items() if k in _ALLOWED_TEST_COLS}
        if not safe_updates:
            continue
        params: dict = {"test_id": rule_id, "lock_y": "Y"}
        set_parts: list[str] = []
        for col, val in safe_updates.items():
            params[f"p_{col}"] = val
            set_parts.append(f"{col} = :p_{col}")
        execute_db_queries([(
            f"UPDATE {schema}.test_definitions SET {', '.join(set_parts)}, "
            "last_manual_update = NOW(), lock_refresh = :lock_y WHERE id = :test_id",
            params,
        )])


@with_database_session
def _persist_governance_deletion(
    term_name: str,
    table_group_id: str,
    table_name: str,
    col_name: str,
) -> None:
    """Write a governance term deletion directly to data_column_chars so it survives the next export."""
    if not col_name:
        _log.warning("_persist_governance_deletion: col_name is empty for term %r — governance terms are column-scoped only", term_name)
        return
    entry = _GOVERNANCE_LABEL_TO_FIELD.get(term_name)
    if not entry:
        _log.warning("_persist_governance_deletion: unknown governance term %r — skipping", term_name)
        return
    db_col, db_val = entry
    if db_col not in COLUMN_GOVERNANCE_FIELDS:
        _log.error("_persist_governance_deletion: column %r not in allowlist — aborting", db_col)
        return
    schema = get_tg_schema()
    execute_db_queries([(
        f"UPDATE {schema}.data_column_chars SET {db_col} = :val "
        "WHERE table_groups_id = CAST(:tg_id AS uuid) AND table_name = :tbl AND column_name = :col",
        {"val": db_val, "tg_id": table_group_id, "tbl": table_name, "col": col_name},
    )])


@with_database_session
def _dismiss_hygiene_anomaly(
    table_group_id: str,
    table_name: str,
    col_name: str,
    anomaly_type: str,
) -> None:
    """Set disposition='Inactive' on the matching anomaly in the latest profiling run."""
    schema = get_tg_schema()
    execute_db_queries([(
        f"""
        UPDATE {schema}.profile_anomaly_results r
           SET disposition = 'Inactive'
          FROM {schema}.profile_anomaly_types t
         WHERE r.anomaly_id = t.id
           AND r.table_groups_id = :tg_id
           AND r.table_name = :tbl
           AND r.column_name = :col
           AND t.anomaly_type = :atype
           AND r.profile_run_id = (
               SELECT id FROM {schema}.profiling_runs
                WHERE table_groups_id = :tg_id
                  AND status = 'Complete'
                ORDER BY profiling_starttime DESC
                LIMIT 1
           )
        """,
        {"tg_id": table_group_id, "tbl": table_name, "col": col_name, "atype": anomaly_type},
    )])
