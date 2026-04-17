# testgen/commands/contract_versions.py
"""
Contract version management — save, load, list, and staleness for contract_versions table.

All version functions are scoped by contract_id (not table_group_id).
Staleness helpers remain table_group_id scoped (they update table_groups).
"""
from __future__ import annotations

import logging
from typing import Any

import yaml as _yaml

from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import execute_db_queries, fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")


def _count_terms(yaml_content: str) -> int:
    """Count schema property terms + quality rules in an ODCS YAML document."""
    try:
        doc = _yaml.safe_load(yaml_content)
        if not isinstance(doc, dict):
            return 0
        schema_terms = sum(len(t.get("properties") or []) for t in (doc.get("schema") or []))
        quality_terms = len(doc.get("quality") or [])
        return schema_terms + quality_terms
    except Exception:
        return 0


@with_database_session
def has_any_version(contract_id: str) -> bool:
    """Return True if at least one saved version exists for the contract."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"SELECT 1 FROM {schema}.contract_versions WHERE contract_id = CAST(:contract_id AS uuid) LIMIT 1",
        params={"contract_id": contract_id},
    )
    return bool(rows)


@with_database_session
def load_contract_version(contract_id: str, version: int | None = None) -> dict[str, Any] | None:
    """
    Load a contract version. Pass version=None to load the current (is_current=TRUE) version.

    Returns dict with keys: version, saved_at, label, contract_yaml, snapshot_suite_id, is_current.
    Returns None if no matching row found.
    """
    schema = get_tg_schema()

    if version is None:
        sql = f"""
            SELECT version, saved_at, label, contract_yaml, is_current,
                   snapshot_suite_id::text AS snapshot_suite_id
              FROM {schema}.contract_versions
             WHERE contract_id = CAST(:contract_id AS uuid)
               AND is_current = TRUE
             LIMIT 1
        """
        params: dict[str, Any] = {"contract_id": contract_id}
    else:
        sql = f"""
            SELECT version, saved_at, label, contract_yaml, is_current,
                   snapshot_suite_id::text AS snapshot_suite_id
              FROM {schema}.contract_versions
             WHERE contract_id = CAST(:contract_id AS uuid)
               AND version = :ver
        """
        params = {"contract_id": contract_id, "ver": version}

    rows = fetch_dict_from_db(sql, params=params)
    if not rows:
        return None

    row = dict(rows[0])
    return {
        "version":           int(row["version"]),
        "saved_at":          row["saved_at"],
        "label":             row.get("label"),
        "contract_yaml":     row["contract_yaml"],
        "snapshot_suite_id": row.get("snapshot_suite_id") or None,
        "is_current":        bool(row.get("is_current", False)),
    }


@with_database_session
def list_contract_versions(contract_id: str) -> list[dict[str, Any]]:
    """Return all versions for a contract, newest first. Each entry: version, saved_at, label, is_current."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"""
        SELECT version, saved_at, label, is_current
          FROM {schema}.contract_versions
         WHERE contract_id = CAST(:contract_id AS uuid)
         ORDER BY version DESC
        """,
        params={"contract_id": contract_id},
    )
    return [
        {
            "version":    int(r["version"]),
            "saved_at":   r["saved_at"],
            "label":      r.get("label"),
            "is_current": bool(r.get("is_current", False)),
        }
        for r in rows
    ]


@with_database_session
def save_contract_version(
    contract_id: str,
    table_group_id: str,
    yaml_content: str,
    term_count: int | None = None,
    label: str | None = None,
) -> int:
    """
    Atomically flip the current version to is_current=FALSE and insert a new is_current=TRUE version.

    Also clears the table_groups.contract_stale flag.
    Returns the new version number (int).
    """
    schema = get_tg_schema()
    if term_count is None:
        term_count = _count_terms(yaml_content)

    # Must be separate statements. A single modifying CTE sharing one snapshot
    # trips the partial unique index (contract_versions_one_current) because
    # the INSERT's is_current=TRUE is checked before the sibling UPDATE's
    # is_current=FALSE is visible to the index.
    flip_sql = f"""
        UPDATE {schema}.contract_versions
           SET is_current = FALSE
         WHERE contract_id = CAST(:contract_id AS uuid) AND is_current = TRUE
    """

    insert_sql = f"""
        WITH ins AS (
            INSERT INTO {schema}.contract_versions
                   (contract_id, version, is_current, label, contract_yaml, term_count)
            SELECT CAST(:contract_id AS uuid),
                   COALESCE(MAX(version), -1) + 1,
                   TRUE,
                   :label,
                   :yaml,
                   :term_count
              FROM {schema}.contract_versions
             WHERE contract_id = CAST(:contract_id AS uuid)
            RETURNING version
        )
        SELECT version FROM ins
    """

    clear_stale_sql = f"""
        UPDATE {schema}.table_groups
           SET contract_stale = FALSE,
               last_contract_save_date = NOW()
         WHERE id = CAST(:tg_id AS uuid)
    """

    return_values, _ = execute_db_queries([
        (flip_sql,        {"contract_id": contract_id}),
        (insert_sql,      {"contract_id": contract_id, "label": label, "yaml": yaml_content,
                           "term_count": term_count}),
        (clear_stale_sql, {"tg_id": table_group_id}),
    ])
    new_version = int(return_values[1])
    LOG.info("Contract version %d saved for contract %s", new_version, contract_id)
    return new_version


@with_database_session
def update_contract_version(contract_id: str, version: int, yaml_content: str) -> None:
    """Update the YAML of an existing version in-place (no version bump)."""
    schema = get_tg_schema()
    execute_db_queries([(
        f"UPDATE {schema}.contract_versions SET contract_yaml = :yaml "
        f" WHERE contract_id = CAST(:contract_id AS uuid) AND version = :version",
        {"contract_id": contract_id, "version": version, "yaml": yaml_content},
    )])
    LOG.info("Contract version %d updated in-place for contract %s", version, contract_id)


@with_database_session
def mark_contract_stale(table_group_id: str) -> None:
    """Mark the table group's contract as stale (only if a version exists)."""
    schema = get_tg_schema()
    execute_db_queries([(
        f"""
        UPDATE {schema}.table_groups
           SET contract_stale = TRUE
         WHERE id = CAST(:tg_id AS uuid)
           AND last_contract_save_date IS NOT NULL
        """,
        {"tg_id": table_group_id},
    )])


@with_database_session
def rollback_contract_version(contract_id: str, version: int) -> None:
    """Delete a just-created version when snapshot suite creation failed."""
    schema = get_tg_schema()
    execute_db_queries([(
        f"DELETE FROM {schema}.contract_versions "
        f" WHERE contract_id = CAST(:contract_id AS uuid) AND version = :version",
        {"contract_id": contract_id, "version": version},
    )])
    LOG.info("Rolled back version %d for contract %s", version, contract_id)


@with_database_session
def get_snapshot_suite_ids_for_contract(contract_id: str) -> list[str]:
    """Return all non-NULL snapshot_suite_ids for a contract's versions."""
    schema = get_tg_schema()
    rows = fetch_dict_from_db(
        f"""
        SELECT snapshot_suite_id::text
          FROM {schema}.contract_versions
         WHERE contract_id = CAST(:contract_id AS uuid)
           AND snapshot_suite_id IS NOT NULL
        """,
        params={"contract_id": contract_id},
    )
    return [str(r["snapshot_suite_id"]) for r in rows]
