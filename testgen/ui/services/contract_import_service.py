"""Reading an uploaded ODCS file, previewing its import, and importing it into a contract's draft."""

import base64
import binascii
import logging
from typing import Any

import streamlit as st

from testgen import settings
from testgen.common.contract_import import (
    ContractIdentityError,
    ContractImportPlan,
    ContractTermReason,
    apply_import,
    prepare_import,
)
from testgen.common.contract_service import InvalidContractDocumentError
from testgen.common.flavors import SqlFlavorCode
from testgen.common.models.connection import Connection
from testgen.common.models.suite_version import SuiteVersion, VersionState, format_version
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_suite import TestSuite
from testgen.common.test_definition_export_import_service import ImportAction

LOG = logging.getLogger("testgen")

IMPORT_PREVIEW_ROW_LIMIT = 500

_FILE_MESSAGE_ENVELOPE_BYTES = 64 * 1024
_PREVIEW_ACTION_ORDER = {ImportAction.delete: 0, ImportAction.create: 1, ImportAction.update: 2, ImportAction.skip: 3}
_TERM_REASON_LABELS = {
    ContractTermReason.NEW: "New rule",
    ContractTermReason.ABSENT: "Not in the file",
    ContractTermReason.MATCHED_BY_ID: "Changed",
    ContractTermReason.MATCHED_BY_KEY: "Changed",
    ContractTermReason.UNCHANGED: "Unchanged",
}


class UnreadableContractFileError(ValueError):
    """Raised for an uploaded contract file that cannot be read as text."""


def contract_file_max_bytes() -> int:
    """The largest contract file accepted: the configured limit, capped by the largest message Streamlit
    accepts from the browser once the file is base64-encoded into the component value."""
    # Streamlit counts this option in decimal megabytes.
    transport_bytes = st.config.get_option("server.maxWidgetStateSize") * 1_000_000
    return min(settings.CONTRACT_IMPORT_MAX_BYTES, transport_bytes * 3 // 4 - _FILE_MESSAGE_ENVELOPE_BYTES)


def read_contract_file(content: str) -> str:
    """The text of an uploaded contract file.

    :param content: the file as the file input sends it, a base64 data URL
    :raises UnreadableContractFileError: when the file is too large, empty, or not UTF-8 text
    """
    max_bytes = contract_file_max_bytes()
    too_large = f"The file is larger than the {max_bytes:,} bytes limit."
    if len(content) > max_bytes * 4 // 3 + 1024:
        raise UnreadableContractFileError(too_large)
    try:
        raw = base64.b64decode(content.split(",", 1)[1], validate=True)
    except (IndexError, binascii.Error) as e:
        raise UnreadableContractFileError("The file could not be read.") from e
    if len(raw) > max_bytes:
        raise UnreadableContractFileError(too_large)
    if not raw:
        raise UnreadableContractFileError("The file is empty.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise UnreadableContractFileError("The file is not a text file.") from e


def import_preview(text: str, table_group: TableGroup, connection: Connection, suite: TestSuite | None) -> dict:
    """What importing ``text`` would change, as the import preview shows it, or why it cannot be imported.

    :param suite: the contract to import into; None to preview creating a contract in ``table_group``
    :return: the preview, or a dict with ``error`` and ``problems`` when the file cannot be imported
    """
    try:
        plan = prepare_import(text, table_group, connection, suite)
        short_names = {row.test_type: row.test_name_short for row in TestType.select_where()}
        return _serialize_plan(plan, short_names, creating=suite is None)
    except InvalidContractDocumentError as e:
        return {"error": "This file cannot be imported.", "problems": e.problems}
    except ContractIdentityError as e:
        return {
            "error": "This file is a different contract.",
            "problems": [
                f"Its id is {e.incoming_id}, but this contract's is {e.target_id}. To import it into this contract, "
                f"change the file's id to {e.target_id}.",
            ],
        }
    except Exception:
        LOG.exception("Could not build contract import preview")
        return {"error": "Something went wrong while reading this file.", "problems": []}


def _serialize_plan(plan: ContractImportPlan, short_names: dict[str, str], creating: bool) -> dict[str, Any]:
    changes = sorted(
        plan.changes,
        key=lambda change: (_PREVIEW_ACTION_ORDER[change.action], change.table_name, change.column_name or ""),
    )
    rows = [
        {
            "action_code": change.action.value,
            "reason": _TERM_REASON_LABELS[change.reason],
            "table_name": change.table_name,
            "column_name": change.column_name or "",
            "test_name": short_names.get(change.test_type) or change.test_type,
        }
        for change in changes
    ]
    return {
        "creating": creating,
        "summary": {action.value: plan.count(action) for action in _PREVIEW_ACTION_ORDER},
        "rows": rows[:IMPORT_PREVIEW_ROW_LIMIT],
        "total_rows": len(rows),
        "truncated": len(rows) > IMPORT_PREVIEW_ROW_LIMIT,
        "unverifiable_count": len(plan.unverifiable_rules),
        "server_type_warning": plan.server_type_warning,
        "tables_not_in_catalog": plan.tables_not_in_catalog,
    }


def import_into_contract(text: str, suite: TestSuite, delete_confirmed: bool) -> dict[str, Any]:
    """Import ``text`` into the contract's draft, opening one when it has none.

    The file is planned again rather than trusting an earlier preview, so the import applies what the
    contract holds now.

    :param delete_confirmed: whether the user confirmed deleting the terms the file does not state
    :return: ``success`` and the ``message`` to show
    """
    table_group = TableGroup.get(suite.table_groups_id)
    connection = Connection.get(table_group.connection_id)
    try:
        plan = prepare_import(text, table_group, connection, suite)
    except (InvalidContractDocumentError, ContractIdentityError):
        return {"success": False, "message": "This file cannot be imported."}
    if plan.count(ImportAction.delete) and not delete_confirmed:
        return {"success": False, "message": "This import deletes terms. Confirm the deletion to import the file."}

    applied = apply_import(plan, suite, table_group, SqlFlavorCode(connection.sql_flavor_code))
    version = SuiteVersion.get(applied.version_id)
    message = f"The contract was imported into {format_version(version.version, VersionState.DRAFT)}."
    if applied.conformance_failed:
        message += " Its schema conformance tests were not updated. Generate Tests updates them."
    return {"success": True, "message": message}
