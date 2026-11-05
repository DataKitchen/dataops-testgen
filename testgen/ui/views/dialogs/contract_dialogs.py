"""The contract's part of its test-definitions page: the summary row's dialogs and the Contract Metadata tab."""

from collections.abc import Callable
from enum import StrEnum
from typing import Any
from uuid import uuid4

import streamlit as st

from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.ui.navigation.router import Router
from testgen.ui.services import (
    contract_history_service,
    contract_import_service,
    contract_lifecycle_service,
    contract_metadata_service,
)
from testgen.ui.services.contract_export_service import contract_export
from testgen.ui.services.contract_page_service import ContractPage, editable_version_number
from testgen.ui.session import session

_STATE_KEY = "td:contract:{}"


class ContractTab(StrEnum):
    RULES = "rules"
    METADATA = "metadata"


class _Dialog(StrEnum):
    EXPORT = "export"
    IMPORT = "import"
    FREEZE = "freeze"
    DISCARD = "discard"
    HISTORY = "history"
    REMOVE_TABLES = "remove_tables"
    DOCUMENT_RESULT = "document_result"
    TABLES_RESULT = "tables_result"
    SECTION_RESULT = "section_result"


def _state(suite: TestSuite, dialog: _Dialog) -> dict[str, Any] | None:
    """A dialog's stored state, kept only for the suite it was opened on."""
    stored = st.session_state.get(_STATE_KEY.format(dialog))
    return stored["state"] if stored and stored["suite_id"] == str(suite.id) else None


def _set_state(suite: TestSuite, dialog: _Dialog, state: dict[str, Any]) -> None:
    st.session_state[_STATE_KEY.format(dialog)] = {"suite_id": str(suite.id), "state": state}


def _clear_state(dialog: _Dialog) -> None:
    st.session_state.pop(_STATE_KEY.format(dialog), None)


def follow_editable_version(suite: TestSuite) -> None:
    """Point the page at the contract's editable version after a write, which may have opened a draft."""
    number = editable_version_number(suite)
    if number is not None and st.query_params.get("version") not in (None, str(number)):
        Router().set_query_params({"version": str(number)})


def contract_props(
    suite: TestSuite, page: ContractPage, project_code: str, tab: str | None
) -> tuple[dict[str, Any], dict[str, Callable]]:
    """The page's ``contract`` prop and the event handlers its summary row, dialogs and tabs emit to.

    :param page: the version on screen and what the page offers for it
    :param tab: the ``tab`` query parameter
    """
    selected = SuiteVersion.get(page.selected_version_id)
    table_group = TableGroup.get(suite.table_groups_id)

    def written(message: str) -> None:
        st.cache_data.clear()
        st.toast(message, icon=":material/task_alt:")
        follow_editable_version(suite)

    def on_version_changed(payload: dict) -> None:
        Router().set_query_params({"version": str(payload["version"])})

    def on_tab_changed(payload: dict) -> None:
        if payload.get("tab") != (tab or ContractTab.RULES):
            Router().set_query_params({"tab": payload.get("tab")})

    def opener(dialog: _Dialog) -> Callable[..., None]:
        def open_dialog(*_) -> None:
            _set_state(suite, dialog, {})
        return open_dialog

    def closer(dialog: _Dialog) -> Callable[..., None]:
        def close_dialog(*_) -> None:
            _clear_state(dialog)
        return close_dialog

    @with_database_session
    def on_import_file(payload: dict) -> None:
        state: dict[str, Any] = {}
        _set_state(suite, _Dialog.IMPORT, state)
        try:
            text = contract_import_service.read_contract_file(payload.get("content") or "")
        except contract_import_service.UnreadableContractFileError as e:
            state["preview"] = {"error": str(e), "problems": []}
            return
        state["preview"] = contract_import_service.import_preview(
            text, TableGroup.get(suite.table_groups_id), Connection.get(table_group.connection_id), suite,
        )
        if not state["preview"].get("error"):
            state["text"] = text

    @with_database_session
    def on_import_confirmed(payload: dict) -> None:
        state = _state(suite, _Dialog.IMPORT)
        if not state or "text" not in state:
            return
        state["result"] = contract_import_service.import_into_contract(
            state["text"], suite, bool(payload.get("delete_confirmed")),
        )
        if state["result"]["success"]:
            st.cache_data.clear()
            follow_editable_version(suite)

    @with_database_session
    def on_freeze_confirmed(payload: dict) -> None:
        username = session.auth.user.username if session.auth.user else None
        result = contract_lifecycle_service.freeze(suite, payload.get("label"), username)
        if result["success"]:
            _clear_state(_Dialog.FREEZE)
            written(result["message"])
        else:
            _set_state(suite, _Dialog.FREEZE, {"result": result})

    @with_database_session
    def on_discard_confirmed(*_) -> None:
        result = contract_lifecycle_service.discard(suite)
        if result["success"]:
            _clear_state(_Dialog.DISCARD)
            written(result["message"])
        else:
            _set_state(suite, _Dialog.DISCARD, {"result": result})

    def on_history_opened(payload: dict | None = None) -> None:
        _clear_state(_Dialog.DISCARD)
        _set_state(suite, _Dialog.HISTORY, {"open_comparison": (payload or {}).get("comparison")})

    @with_database_session
    def on_compare(payload: dict) -> None:
        state = _state(suite, _Dialog.HISTORY) or {}
        source, target = int(payload["source"]), int(payload["target"])
        state["comparison"] = contract_history_service.version_comparison(suite, source, target)
        state["changes"] = contract_history_service.version_changes(
            suite, source, target, mask_pii=not session.auth.user_has_permission("view_pii"),
        )
        _set_state(suite, _Dialog.HISTORY, state)

    @with_database_session
    def on_save_document(payload: dict) -> None:
        result = contract_metadata_service.save_document(suite, payload["text"])
        _set_state(suite, _Dialog.DOCUMENT_RESULT, {**result, "token": str(uuid4())})
        if result["success"]:
            written(result["message"])

    @with_database_session
    def on_save_section(payload: dict) -> None:
        section = contract_metadata_service.MetadataSection(payload["section"])
        result = contract_metadata_service.save_section(suite, section, payload["values"])
        target = {key: payload["values"].get(key) for key in ("table", "column")}
        _set_state(
            suite, _Dialog.SECTION_RESULT, {**result, "section": section.value, "target": target, "token": str(uuid4())},
        )
        if result["success"]:
            written(result["message"])

    @with_database_session
    def apply_tables(tables: list[str]) -> None:
        result = contract_metadata_service.save_tables(suite, tables)
        _set_state(suite, _Dialog.TABLES_RESULT, {**result, "token": str(uuid4())})
        if result["success"]:
            written(result["message"])
        else:
            st.cache_data.clear()
            follow_editable_version(suite)

    @with_database_session
    def on_save_tables(payload: dict) -> None:
        if dialog := contract_metadata_service.remove_tables_dialog(suite, payload["tables"]):
            _set_state(suite, _Dialog.REMOVE_TABLES, {"dialog": dialog, "tables": payload["tables"]})
        else:
            apply_tables(payload["tables"])

    def on_remove_tables_confirmed(*_) -> None:
        if state := _state(suite, _Dialog.REMOVE_TABLES):
            _clear_state(_Dialog.REMOVE_TABLES)
            apply_tables(state["tables"])

    open_tab = tab if tab in tuple(ContractTab) else ContractTab.RULES
    data = {
        "summary": page.summary,
        "tab": open_tab,
        "metadata": {
            **contract_metadata_service.metadata_tab(suite, selected, page.editable),
            "document_result": _state(suite, _Dialog.DOCUMENT_RESULT),
            "tables_result": _state(suite, _Dialog.TABLES_RESULT),
            "section_result": _state(suite, _Dialog.SECTION_RESULT),
        } if open_tab == ContractTab.METADATA else None,
        "export": None,
        "import": None,
        "freeze": None,
        "discard": None,
        "history": None,
        "remove_tables": None,
    }
    if _state(suite, _Dialog.EXPORT) is not None:
        data["export"] = contract_export(suite, page.summary["selected_version"])
    if (state := _state(suite, _Dialog.IMPORT)) is not None:
        data["import"] = {
            "max_file_bytes": contract_import_service.contract_file_max_bytes(),
            "preview": state.get("preview"),
            "result": state.get("result"),
        }
    if (state := _state(suite, _Dialog.FREEZE)) is not None and (dialog := contract_lifecycle_service.freeze_dialog(suite)):
        data["freeze"] = {**dialog, "result": state.get("result")}
    if (state := _state(suite, _Dialog.DISCARD)) is not None and (dialog := contract_lifecycle_service.discard_dialog(suite)):
        data["discard"] = {**dialog, "result": state.get("result")}
    if (state := _state(suite, _Dialog.HISTORY)) is not None:
        data["history"] = {
            **contract_history_service.version_history(suite),
            "project_code": project_code,
            "open_comparison": state.get("open_comparison"),
            "comparison": state.get("comparison"),
            "changes": state.get("changes"),
        }
    if state := _state(suite, _Dialog.REMOVE_TABLES):
        data["remove_tables"] = state["dialog"]

    handlers = {
        "on_ContractVersionChanged_change": on_version_changed,
        "on_ContractTabChanged_change": on_tab_changed,
        "on_ContractHistoryOpened_change": on_history_opened,
        "on_ContractHistoryClosed_change": closer(_Dialog.HISTORY),
        "on_ContractCompare_change": on_compare,
        "on_ContractExportOpened_change": opener(_Dialog.EXPORT),
        "on_ContractExportClosed_change": closer(_Dialog.EXPORT),
        "on_ContractImportOpened_change": opener(_Dialog.IMPORT),
        "on_ContractImportClosed_change": closer(_Dialog.IMPORT),
        "on_ContractImportFile_change": on_import_file,
        "on_ContractImportCleared_change": opener(_Dialog.IMPORT),
        "on_ContractImportConfirmed_change": on_import_confirmed,
        "on_ContractFreezeOpened_change": opener(_Dialog.FREEZE),
        "on_ContractFreezeClosed_change": closer(_Dialog.FREEZE),
        "on_ContractFreezeConfirmed_change": on_freeze_confirmed,
        "on_ContractDiscardOpened_change": opener(_Dialog.DISCARD),
        "on_ContractDiscardClosed_change": closer(_Dialog.DISCARD),
        "on_ContractDiscardConfirmed_change": on_discard_confirmed,
        "on_ContractSaveDocument_change": on_save_document,
        "on_ContractSaveTables_change": on_save_tables,
        "on_ContractSaveSection_change": on_save_section,
        "on_ContractRemoveTablesConfirmed_change": on_remove_tables_confirmed,
        "on_ContractRemoveTablesClosed_change": closer(_Dialog.REMOVE_TABLES),
    }
    return data, handlers
