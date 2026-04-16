# testgen/commands/contract_management.py
"""Create, delete, and manage data contracts (contracts table)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import execute_db_queries, fetch_dict_from_db
from testgen.common.models import get_current_session, with_database_session

LOG = logging.getLogger("testgen")


@with_database_session
def get_contract(contract_id: str) -> dict[str, Any] | None:
    """Return contract metadata dict or None if not found."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"""
        SELECT c.id::text AS contract_id,
               c.name,
               c.project_code,
               c.table_group_id::text,
               c.test_suite_id::text,
               c.is_active,
               c.created_at
          FROM {schema}.contracts c
         WHERE c.id = CAST(:contract_id AS uuid)
        """,
        params={"contract_id": contract_id},
    )
    if not rows:
        return None
    row = dict(rows[0])
    return row


@with_database_session
def create_contract(name: str, project_code: str, table_group_id: str) -> dict[str, str]:
    """
    Atomically create a linked test_suite (is_contract_suite=TRUE) and a contracts row.

    Returns dict with keys 'contract_id' and 'test_suite_id'.
    Raises ValueError if creation fails.
    """
    schema = get_tg_schema()
    session = get_current_session()

    sql = text(f"""
        WITH tg AS (
            SELECT connection_id, project_code
              FROM {schema}.table_groups
             WHERE id = CAST(:tg_id AS uuid)
        ),
        new_suite AS (
            INSERT INTO {schema}.test_suites
                   (test_suite, project_code, connection_id, table_groups_id, is_contract_suite)
            SELECT :name, tg.project_code, tg.connection_id, CAST(:tg_id AS uuid), TRUE
              FROM tg
            RETURNING id
        ),
        new_contract AS (
            INSERT INTO {schema}.contracts
                   (name, project_code, table_group_id, test_suite_id)
            SELECT :name, :project_code, CAST(:tg_id AS uuid), new_suite.id
              FROM new_suite
            RETURNING id::text AS contract_id, test_suite_id::text AS test_suite_id
        )
        SELECT contract_id, test_suite_id FROM new_contract
    """)

    result = session.execute(sql, {"name": name, "project_code": project_code, "tg_id": table_group_id})
    row = result.mappings().first()
    if not row:
        raise ValueError(f"Failed to create contract '{name}' for table group {table_group_id}")

    LOG.info("Contract '%s' created: contract_id=%s suite_id=%s", name, row["contract_id"], row["test_suite_id"])
    return {"contract_id": str(row["contract_id"]), "test_suite_id": str(row["test_suite_id"])}


@with_database_session
def delete_contract(contract_id: str, primary_suite_id: str, snapshot_suite_ids: list[str]) -> None:
    """
    Delete a contract and all its versions (via CASCADE), then delete the test suites.

    Ordering is critical:
    1. DELETE contracts row (cascades to contract_versions, clearing snapshot FK refs)
    2. Cascade-delete all linked suites (clears test_definitions, test_results, test_runs first)
    """
    from testgen.common.models.test_suite import TestSuite

    schema = get_tg_schema()

    # Step 1: delete contracts row — cascades to contract_versions, sets snapshot_suite_id = NULL
    execute_db_queries([(
        f"DELETE FROM {schema}.contracts WHERE id = CAST(:contract_id AS uuid)",
        {"contract_id": contract_id},
    )])

    # Step 2: cascade-delete all linked suites (snapshot suites + primary suite).
    # TestSuite.cascade_delete removes test_definitions, test_results, test_runs,
    # job_schedules, then the suite rows — in the correct order.
    all_suite_ids = [s for s in snapshot_suite_ids + [primary_suite_id] if s]
    if all_suite_ids:
        TestSuite.cascade_delete(all_suite_ids)

    LOG.info("Contract %s deleted (suite %s + %d snapshots)", contract_id, primary_suite_id, len(snapshot_suite_ids))


@with_database_session
def set_contract_active(contract_id: str, active: bool) -> None:
    """Set is_active flag on a contract."""
    schema = get_tg_schema()
    execute_db_queries([(
        f"UPDATE {schema}.contracts SET is_active = :active WHERE id = CAST(:contract_id AS uuid)",
        {"contract_id": contract_id, "active": active},
    )])
    LOG.info("Contract %s set is_active=%s", contract_id, active)
