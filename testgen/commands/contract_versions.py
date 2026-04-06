"""
Contract version management — save, load, list, and staleness for data_contracts table.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import execute_db_queries, fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")


@with_database_session
def has_any_version(table_group_id: str) -> bool:
    """Return True if at least one saved contract version exists for the table group."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"SELECT 1 FROM {schema}.data_contracts WHERE table_group_id = :tg_id LIMIT 1",
        params={"tg_id": table_group_id},
    )
    return bool(rows)


@with_database_session
def load_contract_version(table_group_id: str, version: int | None = None) -> dict[str, Any] | None:
    """
    Load a saved contract version from the database.

    Args:
        table_group_id: UUID of the table group.
        version: Specific version number to load, or None to load the latest.

    Returns:
        Dict with keys version (int), saved_at (datetime), label (str|None),
        contract_yaml (str), or None if no matching row is found.
    """
    schema = get_tg_schema()

    if version is None:
        sql = f"""
            SELECT version, saved_at, label, contract_yaml
            FROM {schema}.data_contracts
            WHERE table_group_id = :tg_id
            ORDER BY version DESC
            LIMIT 1
        """
        params: dict[str, Any] = {"tg_id": table_group_id}
    else:
        sql = f"""
            SELECT version, saved_at, label, contract_yaml
            FROM {schema}.data_contracts
            WHERE table_group_id = :tg_id
              AND version = :ver
        """
        params = {"tg_id": table_group_id, "ver": version}

    rows = fetch_dict_from_db(sql, params=params)
    if not rows:
        return None

    row = dict(rows[0])
    return {
        "version":       int(row["version"]),
        "saved_at":      row["saved_at"],
        "label":         row.get("label"),
        "contract_yaml": row["contract_yaml"],
    }


@with_database_session
def list_contract_versions(table_group_id: str) -> list[dict[str, Any]]:
    """
    Return a summary list of all saved versions for the table group, newest first.

    Each entry has keys: version (int), saved_at (datetime), label (str|None).
    """
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"""
        SELECT version, saved_at, label
        FROM {schema}.data_contracts
        WHERE table_group_id = :tg_id
        ORDER BY version DESC
        """,
        params={"tg_id": table_group_id},
    )
    return [
        {
            "version":  int(r["version"]),
            "saved_at": r["saved_at"],
            "label":    r.get("label"),
        }
        for r in rows
    ]


@with_database_session
def save_contract_version(table_group_id: str, yaml_content: str, label: str | None = None) -> int:
    """
    Atomically insert a new contract version and update the table group staleness state.

    The new version number is computed as MAX(existing_version) + 1, starting at 0
    when no previous versions exist.

    Args:
        table_group_id: UUID of the table group.
        yaml_content: Raw YAML string of the ODCS document to store.
        label: Optional human-readable label for the snapshot.

    Returns:
        The newly assigned version number (int).
    """
    schema = get_tg_schema()

    insert_sql = f"""
        INSERT INTO {schema}.data_contracts (table_group_id, version, saved_at, label, contract_yaml)
        SELECT :tg_id,
               COALESCE(MAX(version), -1) + 1,
               NOW(),
               :label,
               :yaml
        FROM {schema}.data_contracts
        WHERE table_group_id = :tg_id
        RETURNING version
    """
    update_sql = f"""
        UPDATE {schema}.table_groups
        SET contract_stale = FALSE,
            last_contract_save_date = NOW()
        WHERE id = :tg_id
    """

    # INSERT first — get version number. Only update table_groups after INSERT succeeds.
    return_values, _row_counts = execute_db_queries(
        [(insert_sql, {"tg_id": table_group_id, "label": label, "yaml": yaml_content})]
    )
    new_version = int(return_values[0])

    execute_db_queries([(update_sql, {"tg_id": table_group_id})])
    LOG.info("Contract version %d saved for table group %s", new_version, table_group_id)
    return new_version


@with_database_session
def mark_contract_stale(table_group_id: str) -> None:
    """
    Mark the contract as stale, but only if a saved version already exists
    (i.e. last_contract_save_date IS NOT NULL).
    """
    schema = get_tg_schema()
    execute_db_queries(
        [
            (
                f"""
                UPDATE {schema}.table_groups
                SET contract_stale = TRUE
                WHERE id = :tg_id
                  AND last_contract_save_date IS NOT NULL
                """,
                {"tg_id": table_group_id},
            )
        ]
    )


@with_database_session
def mark_contract_not_stale(table_group_id: str) -> None:
    """Clear the stale flag for the table group's contract."""
    schema = get_tg_schema()
    execute_db_queries(
        [
            (
                f"UPDATE {schema}.table_groups SET contract_stale = FALSE WHERE id = :tg_id",
                {"tg_id": table_group_id},
            )
        ]
    )
