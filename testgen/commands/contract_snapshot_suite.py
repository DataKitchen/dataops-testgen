"""
Contract snapshot suite — create, sync, and delete snapshot test suites for saved contract versions.
"""
from __future__ import annotations

import logging
import uuid

from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import execute_db_queries, fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")


@with_database_session
def create_contract_snapshot_suite(
    contract_id: str,
    table_group_id: str,
    version: int,
    table_names: list[str] | None = None,
) -> str:
    """
    Create a snapshot test suite for the given contract version.

    Copies active test definitions from suites where:
      - table_groups_id = table_group_id
      - include_in_contract = TRUE
      - is_monitor IS NOT TRUE
      - is_contract_snapshot IS NOT TRUE

    When *table_names* is provided, only tests for those tables are copied.

    Updates contract_versions.snapshot_suite_id for the matching (contract_id, version) row.
    Returns the new suite UUID as a string.
    Creates an empty snapshot suite when there are no in-scope tests (valid for schema-only contracts).
    """
    schema = get_tg_schema()

    tg_rows = fetch_dict_from_db(
        f"SELECT table_groups_name FROM {schema}.table_groups WHERE id = CAST(:tg_id AS uuid)",
        params={"tg_id": table_group_id},
    )
    if not tg_rows:
        raise ValueError(f"Table group {table_group_id} not found")
    table_group_name = tg_rows[0]["table_groups_name"]

    suite_rows = fetch_dict_from_db(
        f"""
        SELECT connection_id, project_code, severity
        FROM {schema}.test_suites
        WHERE table_groups_id = CAST(:tg_id AS uuid)
          AND COALESCE(include_in_contract, TRUE) = TRUE
          AND COALESCE(is_monitor, FALSE) = FALSE
          AND COALESCE(is_contract_snapshot, FALSE) = FALSE
        ORDER BY LOWER(test_suite)
        LIMIT 1
        """,
        params={"tg_id": table_group_id},
    )
    if not suite_rows:
        # Fall back to the table_groups row for connection info so schema-only
        # contracts (no eligible test suites) can still produce a snapshot suite.
        tg_info_rows = fetch_dict_from_db(
            f"SELECT connection_id, project_code FROM {schema}.table_groups WHERE id = CAST(:tg_id AS uuid)",
            params={"tg_id": table_group_id},
        )
        if not tg_info_rows:
            raise ValueError(f"Table group {table_group_id} not found — cannot create snapshot suite")
        src: dict = {"connection_id": tg_info_rows[0]["connection_id"],
                     "project_code": tg_info_rows[0]["project_code"],
                     "severity": None}
    else:
        src = suite_rows[0]

    new_suite_id = str(uuid.uuid4())
    suite_name = f"[Contract v{version}] {table_group_name}"

    insert_suite_sql = f"""
        INSERT INTO {schema}.test_suites (
            id, test_suite, project_code, connection_id, table_groups_id,
            severity, is_contract_snapshot, include_in_contract,
            export_to_observability, dq_score_exclude
        )
        VALUES (
            CAST(:new_suite_id AS uuid),
            :suite_name,
            :project_code,
            :connection_id,
            CAST(:tg_id AS uuid),
            :severity,
            TRUE,
            TRUE,
            'N',
            TRUE
        )
    """

    bulk_copy_sql = f"""
        INSERT INTO {schema}.test_definitions (
            id,
            test_suite_id,
            source_test_definition_id,
            table_groups_id,
            profile_run_id,
            test_type,
            test_description,
            schema_name,
            table_name,
            column_name,
            skip_errors,
            baseline_ct,
            baseline_unique_ct,
            baseline_value,
            baseline_value_ct,
            threshold_value,
            baseline_sum,
            baseline_avg,
            baseline_sd,
            lower_tolerance,
            upper_tolerance,
            subset_condition,
            groupby_names,
            having_condition,
            window_date_column,
            window_days,
            match_schema_name,
            match_table_name,
            match_column_names,
            match_subset_condition,
            match_groupby_names,
            match_having_condition,
            history_calculation,
            history_calculation_upper,
            history_lookback,
            prediction,
            test_mode,
            custom_query,
            test_active,
            test_definition_status,
            severity,
            watch_level,
            check_result,
            lock_refresh,
            last_auto_gen_date,
            profiling_as_of_date,
            last_manual_update,
            export_to_observability,
            flagged
        )
        SELECT
            gen_random_uuid(),
            CAST(:new_suite_id AS uuid),
            td.id,
            td.table_groups_id,
            td.profile_run_id,
            td.test_type,
            td.test_description,
            td.schema_name,
            td.table_name,
            td.column_name,
            td.skip_errors,
            td.baseline_ct,
            td.baseline_unique_ct,
            td.baseline_value,
            td.baseline_value_ct,
            td.threshold_value,
            td.baseline_sum,
            td.baseline_avg,
            td.baseline_sd,
            td.lower_tolerance,
            td.upper_tolerance,
            td.subset_condition,
            td.groupby_names,
            td.having_condition,
            td.window_date_column,
            td.window_days,
            td.match_schema_name,
            td.match_table_name,
            td.match_column_names,
            td.match_subset_condition,
            td.match_groupby_names,
            td.match_having_condition,
            td.history_calculation,
            td.history_calculation_upper,
            td.history_lookback,
            td.prediction,
            td.test_mode,
            td.custom_query,
            td.test_active,
            td.test_definition_status,
            td.severity,
            td.watch_level,
            td.check_result,
            td.lock_refresh,
            td.last_auto_gen_date,
            td.profiling_as_of_date,
            td.last_manual_update,
            td.export_to_observability,
            td.flagged
        FROM {schema}.test_definitions td
        JOIN {schema}.test_suites ts ON ts.id = td.test_suite_id
        WHERE ts.table_groups_id = CAST(:tg_id AS uuid)
          AND COALESCE(ts.include_in_contract, TRUE) = TRUE
          AND COALESCE(ts.is_monitor, FALSE) = FALSE
          AND COALESCE(ts.is_contract_snapshot, FALSE) = FALSE
          {"AND td.table_name = ANY(CAST(:table_names AS text[]))" if table_names else ""}
        ON CONFLICT DO NOTHING
    """

    update_contract_sql = f"""
        UPDATE {schema}.contract_versions
        SET snapshot_suite_id = CAST(:new_suite_id AS uuid)
        WHERE contract_id = CAST(:contract_id AS uuid)
          AND version = :version
    """

    params = {
        "new_suite_id":  new_suite_id,
        "suite_name":    suite_name,
        "project_code":  src.get("project_code") or "",
        "connection_id": src.get("connection_id"),
        "tg_id":         table_group_id,
        "contract_id":   contract_id,
        "severity":      src.get("severity"),
        "version":       version,
        "table_names":   table_names,
    }

    execute_db_queries([
        (insert_suite_sql,    params),
        (bulk_copy_sql,       params),
        (update_contract_sql, params),
    ])

    LOG.info(
        "Created contract snapshot suite %s (v%d) for table group %s",
        new_suite_id, version, table_group_id,
    )
    return new_suite_id


@with_database_session
def sync_import_to_snapshot_suite(
    snapshot_suite_id: str,
    created_td_ids: list[str],
    updated_td_ids: list[str],
    deleted_td_ids: list[str],
) -> None:
    """
    Mirror YAML import mutations into the snapshot suite.
    Called after apply_import_diff when snapshot_suite_id is non-null.
    All three operations run as a single execute_db_queries call.
    If all three ID lists are empty, returns immediately without any DB call.
    """
    if not created_td_ids and not updated_td_ids and not deleted_td_ids:
        return

    schema = get_tg_schema()
    queries: list[tuple[str, dict]] = []

    if created_td_ids:
        insert_sql = f"""
            INSERT INTO {schema}.test_definitions (
                id,
                test_suite_id,
                source_test_definition_id,
                table_groups_id,
                profile_run_id,
                test_type,
                test_description,
                schema_name,
                table_name,
                column_name,
                skip_errors,
                baseline_ct,
                baseline_unique_ct,
                baseline_value,
                baseline_value_ct,
                threshold_value,
                baseline_sum,
                baseline_avg,
                baseline_sd,
                lower_tolerance,
                upper_tolerance,
                subset_condition,
                groupby_names,
                having_condition,
                window_date_column,
                window_days,
                match_schema_name,
                match_table_name,
                match_column_names,
                match_subset_condition,
                match_groupby_names,
                match_having_condition,
                history_calculation,
                history_calculation_upper,
                history_lookback,
                prediction,
                test_mode,
                custom_query,
                test_active,
                test_definition_status,
                severity,
                watch_level,
                check_result,
                lock_refresh,
                last_auto_gen_date,
                profiling_as_of_date,
                last_manual_update,
                export_to_observability,
                flagged
            )
            SELECT
                gen_random_uuid(),
                CAST(:snapshot_suite_id AS uuid),
                td.id,
                td.table_groups_id,
                td.profile_run_id,
                td.test_type,
                td.test_description,
                td.schema_name,
                td.table_name,
                td.column_name,
                td.skip_errors,
                td.baseline_ct,
                td.baseline_unique_ct,
                td.baseline_value,
                td.baseline_value_ct,
                td.threshold_value,
                td.baseline_sum,
                td.baseline_avg,
                td.baseline_sd,
                td.lower_tolerance,
                td.upper_tolerance,
                td.subset_condition,
                td.groupby_names,
                td.having_condition,
                td.window_date_column,
                td.window_days,
                td.match_schema_name,
                td.match_table_name,
                td.match_column_names,
                td.match_subset_condition,
                td.match_groupby_names,
                td.match_having_condition,
                td.history_calculation,
                td.history_calculation_upper,
                td.history_lookback,
                td.prediction,
                td.test_mode,
                td.custom_query,
                td.test_active,
                td.test_definition_status,
                td.severity,
                td.watch_level,
                td.check_result,
                td.lock_refresh,
                td.last_auto_gen_date,
                td.profiling_as_of_date,
                td.last_manual_update,
                td.export_to_observability,
                td.flagged
            FROM {schema}.test_definitions td
            WHERE td.id = ANY(CAST(:created_ids AS uuid[]))
        """
        queries.append((insert_sql, {
            "snapshot_suite_id": snapshot_suite_id,
            "created_ids": [str(i) for i in created_td_ids],
        }))

    if updated_td_ids:
        update_sql = f"""
            UPDATE {schema}.test_definitions snap
            SET
                table_name        = src.table_name,
                column_name       = src.column_name,
                test_type         = src.test_type,
                test_active       = src.test_active,
                severity          = src.severity,
                threshold_value   = src.threshold_value,
                lower_tolerance   = src.lower_tolerance,
                upper_tolerance   = src.upper_tolerance,
                test_description  = src.test_description,
                last_manual_update = src.last_manual_update,
                lock_refresh      = src.lock_refresh
            FROM {schema}.test_definitions src
            WHERE snap.source_test_definition_id = src.id
              AND snap.test_suite_id = CAST(:snapshot_suite_id AS uuid)
              AND src.id = ANY(CAST(:updated_ids AS uuid[]))
        """
        queries.append((update_sql, {
            "snapshot_suite_id": snapshot_suite_id,
            "updated_ids": [str(i) for i in updated_td_ids],
        }))

    if deleted_td_ids:
        delete_sql = f"""
            DELETE FROM {schema}.test_definitions
            WHERE source_test_definition_id = ANY(CAST(:deleted_ids AS uuid[]))
              AND test_suite_id = CAST(:snapshot_suite_id AS uuid)
        """
        queries.append((delete_sql, {
            "snapshot_suite_id": snapshot_suite_id,
            "deleted_ids": [str(i) for i in deleted_td_ids],
        }))

    execute_db_queries(queries)

    LOG.info(
        "sync_import_to_snapshot_suite: suite=%s created=%d updated=%d deleted=%d",
        snapshot_suite_id, len(created_td_ids), len(updated_td_ids), len(deleted_td_ids),
    )


@with_database_session
def delete_contract_version(contract_id: str, version: int) -> None:
    """
    Delete a contract version and its paired snapshot suite (if any).
    Raises ValueError if this is the only version for the contract.
    Promotes the previous version to is_current=TRUE if the deleted version was current.
    """
    schema = get_tg_schema()

    count_rows = fetch_dict_from_db(
        f"SELECT COUNT(*) AS ct FROM {schema}.contract_versions WHERE contract_id = CAST(:contract_id AS uuid)",
        params={"contract_id": contract_id},
    )
    version_count = int((count_rows[0]["ct"] or 0)) if count_rows else 0
    if version_count <= 1:
        raise ValueError("Cannot delete the only saved version")

    ver_rows = fetch_dict_from_db(
        f"""
        SELECT snapshot_suite_id::text AS snapshot_suite_id, is_current
        FROM {schema}.contract_versions
        WHERE contract_id = CAST(:contract_id AS uuid)
          AND version = :version
        """,
        params={"contract_id": contract_id, "version": version},
    )
    if not ver_rows:
        raise ValueError(f"Version {version} not found for contract {contract_id}")

    snapshot_suite_id: str | None = None
    if ver_rows[0].get("snapshot_suite_id"):
        snapshot_suite_id = str(ver_rows[0]["snapshot_suite_id"])
    is_current_version = bool(ver_rows[0].get("is_current", False))

    queries: list[tuple[str, dict]] = []

    # If deleting the current version, promote the next most-recent version to current
    if is_current_version:
        queries.append((
            f"""
            UPDATE {schema}.contract_versions
               SET is_current = TRUE
             WHERE contract_id = CAST(:contract_id AS uuid)
               AND version = (
                   SELECT MAX(version) FROM {schema}.contract_versions
                    WHERE contract_id = CAST(:contract_id AS uuid)
                      AND version != :version
               )
            """,
            {"contract_id": contract_id, "version": version},
        ))

    if snapshot_suite_id:
        queries.extend([
            (f"DELETE FROM {schema}.test_results WHERE test_suite_id = CAST(:sid AS uuid)", {"sid": snapshot_suite_id}),
            (f"DELETE FROM {schema}.test_runs WHERE test_suite_id = CAST(:sid AS uuid)", {"sid": snapshot_suite_id}),
            (f"DELETE FROM {schema}.test_definitions WHERE test_suite_id = CAST(:sid AS uuid)", {"sid": snapshot_suite_id}),
            (f"DELETE FROM {schema}.test_suites WHERE id = CAST(:sid AS uuid)", {"sid": snapshot_suite_id}),
        ])

    queries.append((
        f"DELETE FROM {schema}.contract_versions WHERE contract_id = CAST(:contract_id AS uuid) AND version = :version",
        {"contract_id": contract_id, "version": version},
    ))

    execute_db_queries(queries)
    LOG.info("Deleted contract version %d for contract %s (snapshot_suite_id=%s)", version, contract_id, snapshot_suite_id)
