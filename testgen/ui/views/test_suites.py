import logging
import typing
from enum import StrEnum
from uuid import UUID

import streamlit as st

from testgen.commands.run_observability_exporter import export_test_results
from testgen.commands.test_generation import (
    TESTS_NEED_PROFILING,
    ContractGenerationResult,
    resolve_generation_profile_run,
    run_test_generation_and_report,
)
from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.audit.test_suites import record_contract_created
from testgen.common.contract_creation import create_contract, create_contract_from_import
from testgen.common.contract_document import catalog_table_names
from testgen.common.contract_import import prepare_import
from testgen.common.database.test_suite_service import validate_test_suite_fields
from testgen.common.enums import TEST_SUITE_TYPES, JobSource, RegenerationGroup, SuiteType
from testgen.common.flavors import FLAVOR_CODE_TO_LABEL
from testgen.common.generation_set_service import (
    CONTRACT_GENERATION_SET,
    DEFAULT_GENERATION_SET,
    get_generation_set_members,
    get_generation_set_test_types,
    get_overriding_test_types,
    list_generation_sets,
    resolve_generation_sets,
)
from testgen.common.models import database_session, get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.notification_settings import TestRunNotificationSettings
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.suite_version import ContractState, VersionState, format_version
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.servers import CustomServerReason
from testgen.common.run_service import launch_run
from testgen.common.value_hash import VALUE_HASH_TEST_TYPES
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.services.contract_import_service import (
    UnreadableContractFileError,
    contract_file_max_bytes,
    import_preview,
    read_contract_file,
)
from testgen.ui.services.contract_run_service import run_test_suite_options
from testgen.ui.services.query_cache import (
    get_contract_states,
    get_project_summary,
    get_test_suite,
    get_test_suite_minimal,
    get_test_suite_summaries,
    select_table_groups_minimal_where,
)
from testgen.ui.session import session
from testgen.ui.views.dialogs.generate_tests_dialog import (
    get_sampled_unavailable_test_types,
    get_test_suite_refresh_warning,
    get_value_hash_warning,
    lock_edited_tests,
)
from testgen.ui.views.test_runs import TestRunNotificationSettingsDialog, TestRunScheduleDialog, run_started_message
from testgen.utils import make_json_safe

LOG = logging.getLogger("testgen")

PAGE_ICON = "rule"
PAGE_TITLE = "Test Suites"

ADD_DIALOG_KEY = "ts:add_dialog"
EDIT_DIALOG_KEY = "ts:edit_dialog"
RUN_TESTS_DIALOG_KEY = "ts:run_tests_dialog"
RUN_TESTS_RESULT_KEY = "ts:run_tests_result"
GENERATE_TESTS_DIALOG_KEY = "ts:generate_tests_dialog"
GENERATE_TESTS_RESULT_KEY = "ts:generate_tests_result"
GENERATE_TESTS_LOCK_RESULT_KEY = "ts:generate_tests_lock_result"
RUN_SCHEDULES_DIALOG_KEY = "ts:run_schedules_dialog"
RUN_NOTIFICATIONS_DIALOG_KEY = "ts:run_notifications_dialog"
WIZARD_TABLE_GROUP_KEY = "ts:wizard:table_group"
WIZARD_FILE_KEY = "ts:wizard:file"
WIZARD_PREVIEW_KEY = "ts:wizard:preview"
WIZARD_RESULT_KEY = "ts:wizard:result"
WIZARD_KEYS = (WIZARD_TABLE_GROUP_KEY, WIZARD_FILE_KEY, WIZARD_PREVIEW_KEY, WIZARD_RESULT_KEY)



class SuiteTypeFilter(StrEnum):
    REGULAR = "regular"
    CONTRACT = "contract"


_SUITE_TYPES_BY_FILTER = {
    SuiteTypeFilter.REGULAR: (SuiteType.REGULAR,),
    SuiteTypeFilter.CONTRACT: (SuiteType.CONTRACT,),
}


def suite_types_for_filter(value: str | None) -> tuple[SuiteType, ...]:
    """The suite types the list shows for a Test Suite Type filter value; all listed types when unset or unknown."""
    try:
        return _SUITE_TYPES_BY_FILTER[SuiteTypeFilter(value)]
    except ValueError:
        return TEST_SUITE_TYPES


def version_caption(state: ContractState | None) -> str:
    """A contract card's version caption, e.g. ``v3 active · v4 draft``; empty when the contract has no versions."""
    parts = []
    if state and state.active:
        parts.append(format_version(state.active.version, VersionState.ACTIVE))
    if state and state.draft:
        parts.append(format_version(state.draft.version, VersionState.DRAFT))
    return " · ".join(parts)


class TestSuitesPage(Page):
    path = "test-suites"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=2,
    )

    def render(
        self,
        project_code: str,
        table_group_id: str | None = None,
        test_suite_name: str | None = None,
        suite_type: str | None = None,
        **_kwargs,
    ) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "manage-test-suites",
        )

        table_groups = select_table_groups_minimal_where(TableGroup.project_code == project_code)
        user_can_edit = session.auth.user_has_permission("edit")
        test_suites = get_test_suite_summaries(
            project_code, table_group_id, test_suite_name, suite_types_for_filter(suite_type)
        )
        contract_ids = [ts.id for ts in test_suites if ts.suite_type == SuiteType.CONTRACT]
        states = get_contract_states(tuple(contract_ids)) if contract_ids else {}
        project_summary = get_project_summary(project_code)
        delete_dialog = st.session_state.get("ts_delete_dialog")

        # Build form_dialog prop from session state
        table_group_options = [{"value": str(tg.id), "label": tg.table_groups_name} for tg in table_groups]
        add_wizard = build_wizard_data(table_group_options) if st.session_state.get(ADD_DIALOG_KEY) else None
        form_dialog = None
        if edit_ts_id := st.session_state.get(EDIT_DIALOG_KEY):
            selected = get_test_suite(edit_ts_id)
            form_dialog = {
                "open": True,
                "test_suite_id": str(selected.id),
                "table_groups": table_group_options,
                "initial_values": {
                    "suite_type": selected.suite_type,
                    "test_suite": selected.test_suite,
                    "table_groups_id": str(selected.table_groups_id) if selected.table_groups_id else None,
                    "test_suite_description": selected.test_suite_description or "",
                    "severity": selected.severity,
                    "export_to_observability": bool(selected.export_to_observability),
                    "dq_score_exclude": bool(selected.dq_score_exclude),
                    "deactivate_invalid_tests": bool(selected.deactivate_invalid_tests),
                    "component_key": selected.component_key or "",
                    "component_type": selected.component_type or "dataset",
                    "component_name": selected.component_name or "",
                },
                "result": st.session_state.get("ts_form_dialog:result"),
            }

        def on_edit_ts_clicked(test_suite_id: str) -> None:
            st.session_state[EDIT_DIALOG_KEY] = test_suite_id

        def on_run_tests_clicked(test_suite_id: str) -> None:
            st.session_state[RUN_TESTS_DIALOG_KEY] = test_suite_id

        def on_generate_tests_clicked(test_suite_id: str) -> None:
            st.session_state[GENERATE_TESTS_DIALOG_KEY] = test_suite_id

        def on_run_schedules_clicked(*_) -> None:
            st.session_state[RUN_SCHEDULES_DIALOG_KEY] = True

        def on_run_notifications_clicked(*_) -> None:
            st.session_state[RUN_NOTIFICATIONS_DIALOG_KEY] = True

        schedule_obj = TestRunScheduleDialog(project_code)
        ns_obj = TestRunNotificationSettingsDialog(
            TestRunNotificationSettings, {"project_code": project_code}
        )

        run_tests_data = None
        if run_tests_ts_id := st.session_state.get(RUN_TESTS_DIALOG_KEY):
            run_tests_data = {
                "title": "Run Tests",
                "project_code": project_code,
                "test_suites": run_test_suite_options(
                    [ts for ts in test_suites if str(ts.id) == str(run_tests_ts_id)], states
                ),
                "default_test_suite_id": str(run_tests_ts_id) if run_tests_ts_id else None,
                "result": st.session_state.get(RUN_TESTS_RESULT_KEY),
            }

        generate_tests_data = None
        if generate_tests_ts_id := st.session_state.get(GENERATE_TESTS_DIALOG_KEY):
            generate_tests_data = build_generate_tests_data(generate_tests_ts_id)

        schedule_data = None
        if st.session_state.get(RUN_SCHEDULES_DIALOG_KEY):
            schedule_data = schedule_obj.build_data()
            schedule_data["open"] = True

        notifications_data = None
        if st.session_state.get(RUN_NOTIFICATIONS_DIALOG_KEY):
            notifications_data = ns_obj.build_data()
            notifications_data["open"] = True

        def on_run_tests_confirmed(data: dict) -> None:
            selected_id = data.get("test_suite_id")
            selected_name = data.get("test_suite_name")
            success = True
            suite_type = next((ts.suite_type for ts in test_suites if str(ts.id) == str(selected_id)), None)
            message = run_started_message(suite_type, selected_name)
            show_link = session.current_page != "test-runs"
            try:
                with database_session():
                    launch_run(
                        job_key="run-tests",
                        kwargs={
                            "test_suite_id": str(selected_id),
                            **({"version_id": str(data["version_id"])} if data.get("version_id") else {}),
                        },
                        source=JobSource.ui,
                        project_code=project_code,
                    )
            except Exception as error:
                success = False
                message = f"Test run could not be started: {error!s}."
                show_link = False
            st.session_state[RUN_TESTS_RESULT_KEY] = {"success": success, "message": message, "show_link": show_link}
            if success and not show_link:
                st.cache_data.clear()
                st.session_state.pop(RUN_TESTS_DIALOG_KEY, None)
                st.session_state.pop(RUN_TESTS_RESULT_KEY, None)

        def on_go_to_test_runs(payload: dict) -> None:
            st.session_state.pop(RUN_TESTS_DIALOG_KEY, None)
            st.session_state.pop(RUN_TESTS_RESULT_KEY, None)
            st.cache_data.clear()
            Router().queue_navigation(to="test-runs", with_args=payload)

        def on_run_tests_dialog_closed(*_) -> None:
            st.session_state.pop(RUN_TESTS_DIALOG_KEY, None)
            st.session_state.pop(RUN_TESTS_RESULT_KEY, None)

        def on_lock_edited_tests(*_) -> None:
            if ts_id := st.session_state.get(GENERATE_TESTS_DIALOG_KEY):
                lock_edited_tests(ts_id)
            st.session_state[GENERATE_TESTS_LOCK_RESULT_KEY] = "Edited tests have been successfully locked."

        def on_generate_tests_dialog_closed(*_) -> None:
            st.session_state.pop(GENERATE_TESTS_DIALOG_KEY, None)
            st.session_state.pop(GENERATE_TESTS_RESULT_KEY, None)
            st.session_state.pop(GENERATE_TESTS_LOCK_RESULT_KEY, None)

        def on_schedule_dialog_closed(*_) -> None:
            schedule_obj.clear_state()
            st.session_state.pop(RUN_SCHEDULES_DIALOG_KEY, None)

        def on_notifications_dialog_closed(*_) -> None:
            ns_obj.clear_state()
            st.session_state.pop(RUN_NOTIFICATIONS_DIALOG_KEY, None)

        def on_close_form_dialog(*_) -> None:
            st.session_state.pop(EDIT_DIALOG_KEY, None)
            st.session_state.pop("ts_form_dialog:result", None)

        testgen.test_suites_widget(
            key="test_suites",
            data={
                "project_summary": project_summary.to_dict(json_safe=True),
                "test_suites": [
                    {
                        **test_suite.to_dict(json_safe=True),
                        "version_caption": version_caption(states.get(test_suite.id))
                        if test_suite.suite_type == SuiteType.CONTRACT else None,
                    }
                    for test_suite in test_suites
                ],
                "suite_type_filter_options": [
                    {
                        "value": SuiteTypeFilter.REGULAR.value,
                        "label": "Test suite",
                        "selected": suite_type == SuiteTypeFilter.REGULAR,
                    },
                    {
                        "value": SuiteTypeFilter.CONTRACT.value,
                        "label": "Contract",
                        "selected": suite_type == SuiteTypeFilter.CONTRACT,
                    },
                ],
                "table_group_filter_options": [
                    {
                        "value": str(table_group.id),
                        "label": table_group.table_groups_name,
                        "selected": str(table_group_id) == str(table_group.id),
                    } for table_group in table_groups
                ],
                "test_suite_name": test_suite_name,
                "permissions": {
                    "can_edit": user_can_edit,
                },
                "delete_dialog": delete_dialog,
                "form_dialog": form_dialog,
                "add_wizard": add_wizard,
                "run_tests_dialog": run_tests_data,
                "generate_tests_dialog": generate_tests_data,
                "schedule_dialog": schedule_data,
                "notifications_dialog": notifications_data,
            },
            on_FilterApplied_change=on_test_suites_filtered,
            on_RunSchedulesClicked_change=on_run_schedules_clicked,
            on_AddTestSuiteClicked_change=add_test_suite_clicked,
            on_ExportActionClicked_change=observability_export_action,
            on_EditActionClicked_change=on_edit_ts_clicked,
            on_DeleteActionClicked_change=prepare_ts_delete_dialog,
            on_DeleteTestSuiteConfirmed_change=execute_ts_delete,
            on_DeleteDialogDismissed_change=lambda *_: st.session_state.pop("ts_delete_dialog", None),
            on_RunTestsClicked_change=on_run_tests_clicked,
            on_RunNotificationsClicked_change=on_run_notifications_clicked,
            on_GenerateTestsClicked_change=on_generate_tests_clicked,
            on_SaveTestSuiteForm_change=save_test_suite_form,
            on_FormDialogClosed_change=on_close_form_dialog,
            # Add Test Suite wizard events
            on_WizardTableGroupSelected_change=wizard_table_group_selected,
            on_ContractFileUploaded_change=contract_file_uploaded,
            on_ContractFileCleared_change=contract_file_cleared,
            on_AddTestSuiteConfirmed_change=add_test_suite_confirmed,
            on_WizardClosed_change=wizard_closed,
            # RunTestsDialog events
            on_RunTestsConfirmed_change=on_run_tests_confirmed,
            on_GoToTestRunsClicked_change=on_go_to_test_runs,
            on_RunTestsDialogClosed_change=on_run_tests_dialog_closed,
            # GenerateTestsDialog events
            on_LockEditedTests_change=on_lock_edited_tests,
            on_GenerateTestsConfirmed_change=generate_tests_confirmed,
            on_GenerateTestsDialogClosed_change=on_generate_tests_dialog_closed,
            # ScheduleList events
            on_PauseSchedule_change=schedule_obj.on_pause,
            on_ResumeSchedule_change=schedule_obj.on_resume,
            on_DeleteSchedule_change=schedule_obj.on_delete,
            on_GetCronSample_change=schedule_obj.on_cron_sample,
            on_AddSchedule_change=schedule_obj.on_add,
            on_ScheduleDialogClosed_change=on_schedule_dialog_closed,
            # NotificationSettings events
            on_AddNotification_change=ns_obj.on_add_item,
            on_UpdateNotification_change=ns_obj.on_update_item,
            on_DeleteNotification_change=ns_obj.on_delete_item,
            on_PauseNotification_change=ns_obj.on_pause_item,
            on_ResumeNotification_change=ns_obj.on_resume_item,
            on_NotificationsDialogClosed_change=on_notifications_dialog_closed,
        )


class TestSuiteFilters(typing.TypedDict):
    table_group_id: str
    test_suite_name: str
    suite_type: str


def on_test_suites_filtered(filters: TestSuiteFilters) -> None:
    Router().set_query_params(filters)


_FORM_FIELD_LABELS = {
    "severity": "Severity",
    "component_key": "Component Key",
    "component_type": "Component Type",
    "component_name": "Component Name",
}


def _form_field_labels(suite_type: str | None) -> dict[str, str]:
    kind = "Contract" if suite_type == SuiteType.CONTRACT else "Test Suite"
    return {"test_suite": f"{kind} Name", "test_suite_description": f"{kind} Description", **_FORM_FIELD_LABELS}


_FORM_DEFAULTS = {
    "test_suite_description": "",
    "severity": None,
    "export_to_observability": False,
    "dq_score_exclude": False,
    "component_key": "",
    "component_type": "dataset",
    "component_name": "",
}


_REGENERATION_GROUP_TEXT = {
    RegenerationGroup.TESTS: (
        "Tests",
        "Regenerates the contract's tests from the latest profiling. Locked tests are kept.",
    ),
    RegenerationGroup.PROFILING: (
        "Profiling results",
        "Updates functional types, keys, formats, and the values profiling observed.",
    ),
    RegenerationGroup.CATALOG: (
        "Catalog metadata",
        "Updates descriptions, tags, classification, and the PII, critical data element, and excluded flags "
        "from the data catalog.",
    ),
}


def contract_regeneration_message(
    contract_name: str, requested: list[str], result: ContractGenerationResult
) -> str:
    """The result message for a contract regeneration of the ``requested`` groups: what was
    regenerated, and what profiling could not supply."""
    if not result.groups:
        return (
            f"No tests were regenerated for the contract '{contract_name}' because none of its tables have been "
            "profiled."
        )
    groups = [_REGENERATION_GROUP_TEXT[group][0].lower() for group in result.groups]
    regenerated = " and ".join(groups) if len(groups) <= 2 else f"{', '.join(groups[:-1])}, and {groups[-1]}"
    message = f"The contract '{contract_name}' was regenerated: {regenerated}."
    if not result.tables_not_profiled:
        return message
    skipped = []
    if RegenerationGroup.TESTS in requested:
        skipped.append("Tests")
    if RegenerationGroup.PROFILING in requested:
        skipped.append("the values profiling observed" if skipped else "The values profiling observed")
    if skipped:
        message += f" {' and '.join(skipped)} were not refreshed for tables that have not been profiled."
    return message


def build_generate_tests_data(test_suite_id: str) -> dict:
    generate_suite = TestSuite.get(test_suite_id)
    is_contract = generate_suite.suite_type == SuiteType.CONTRACT
    contract_data = {}
    if is_contract:
        profiled = resolve_generation_profile_run(TableGroup.get(generate_suite.table_groups_id)) is not None
        contract_data = {
            "regeneration_groups": [
                {"value": str(group), "label": label, "help": help_text}
                for group, (label, help_text) in _REGENERATION_GROUP_TEXT.items()
            ],
            "tests_disabled_reason": None if profiled else TESTS_NEED_PROFILING,
        }
    sampled_unavailable = get_sampled_unavailable_test_types(str(generate_suite.table_groups_id))
    if is_contract:
        contract_test_types = set(get_generation_set_test_types(CONTRACT_GENERATION_SET))
        sampled_unavailable = {code: name for code, name in sampled_unavailable.items() if code in contract_test_types}
    return {
        "title": "Regenerate Contract" if is_contract else "Generate Tests",
        "test_suite_id": str(generate_suite.id),
        "test_suite_name": generate_suite.test_suite,
        "is_contract": is_contract,
        **contract_data,
        "generation_sets": [] if is_contract else list_generation_sets(),
        "selected_generation_sets": [] if is_contract else resolve_generation_sets(generate_suite, None),
        "generation_set_test_types": {} if is_contract else get_generation_set_members(),
        "overriding_test_types": {} if is_contract else get_overriding_test_types(),
        "sampled_unavailable_test_types": sampled_unavailable,
        "refresh_warning": get_test_suite_refresh_warning(str(generate_suite.id)),
        "value_hash_test_types": sorted(VALUE_HASH_TEST_TYPES),
        "value_hash_warning": None if is_contract else get_value_hash_warning(str(generate_suite.table_groups_id)),
        "lock_result": st.session_state.get(GENERATE_TESTS_LOCK_RESULT_KEY),
        "result": st.session_state.get(GENERATE_TESTS_RESULT_KEY),
    }


@with_database_session
def generate_tests_confirmed(data: dict) -> None:
    selected_id = data.get("test_suite_id")
    is_contract = TestSuite.get(selected_id).suite_type == SuiteType.CONTRACT
    selected_sets = None if is_contract else data.get("generation_sets")
    ts_name = data.get("test_suite_name", "")
    try:
        regenerate = data.get("regenerate") if is_contract else None
        result = run_test_generation_and_report(JobSource.ui, selected_id, selected_sets, regenerate=regenerate)
        if is_contract:
            # The dialog stays open to show what was regenerated; closing it clears the result.
            requested = list(RegenerationGroup) if regenerate is None else regenerate
            st.session_state[GENERATE_TESTS_RESULT_KEY] = {
                "success": True, "message": contract_regeneration_message(ts_name, requested, result),
            }
            st.cache_data.clear()
            return
        st.cache_data.clear()
        st.session_state.pop(GENERATE_TESTS_DIALOG_KEY, None)
        st.session_state.pop(GENERATE_TESTS_RESULT_KEY, None)
        st.session_state.pop(GENERATE_TESTS_LOCK_RESULT_KEY, None)
    except Exception as e:
        st.session_state[GENERATE_TESTS_RESULT_KEY] = {"success": False, "message": f"Test generation encountered errors: {e!s}."}


@with_database_session
def save_test_suite_form(data: dict) -> None:
    values = {key: data.get(key, default) for key, default in _FORM_DEFAULTS.items()}
    # Validated on a detached copy, so a rejected edit never touches the stored suite.
    candidate = TestSuite(
        test_suite=data.get("test_suite"),
        deactivate_invalid_tests=data.get("deactivate_invalid_tests", False),
        **values,
    )
    field_labels = _form_field_labels(data.get("suite_type"))
    if errors := validate_test_suite_fields(candidate, field_names=field_labels, quote_fields=False):
        st.session_state["ts_form_dialog:result"] = {"success": False, "message": " ".join(errors)}
        return

    test_suite = get_test_suite(data.get("test_suite_id"))
    for attr, value in values.items():
        setattr(test_suite, attr, value)
    test_suite.deactivate_invalid_tests = data.get("deactivate_invalid_tests", test_suite.deactivate_invalid_tests)
    test_suite.save()
    record(AuditAction.TEST_SUITE_UPDATED, test_suite)
    st.session_state.pop("ts_form_dialog:result", None)
    st.session_state.pop(EDIT_DIALOG_KEY, None)
    get_test_suite_summaries.clear()
    get_project_summary.clear()
    st.toast("Changes have been saved successfully.", icon=":material/check:")


@with_database_session
def prepare_ts_delete_dialog(test_suite_id: str) -> None:
    selected = get_test_suite_minimal(test_suite_id)
    is_in_use = TestSuite.is_in_use([selected.id])
    st.session_state["ts_delete_dialog"] = {
        "open": True,
        "test_suite_id": str(selected.id),
        "test_suite_name": selected.test_suite,
        "suite_type": selected.suite_type,
        "is_in_use": is_in_use,
    }


@with_database_session
def execute_ts_delete(test_suite_id: str) -> None:
    dialog = st.session_state.get("ts_delete_dialog", {})
    test_suite_name = dialog.get("test_suite_name", "")
    noun = "Contract" if dialog.get("suite_type") == SuiteType.CONTRACT else "Test Suite"
    if TestRun.has_active_job_for(TestSuite, test_suite_id):
        st.toast(f"This {noun} is in use by a running process and cannot be deleted.", icon=":material/error:")
    else:
        if test_suite := TestSuite.get(test_suite_id):
            record(AuditAction.TEST_SUITE_DELETED, test_suite)
        TestSuite.cascade_delete([test_suite_id])
        st.toast(f"{noun} {test_suite_name} has been deleted.", icon=":material/check:")
    st.session_state.pop("ts_delete_dialog", None)
    get_test_suite_summaries.clear()
    get_project_summary.clear()


@with_database_session
def observability_export_action(test_suite_id: str) -> None:
    selected_test_suite = get_test_suite_minimal(test_suite_id)
    try:
        qty_of_exported_events = export_test_results(selected_test_suite.id)
        st.toast(f"Export finished: {qty_of_exported_events} events exported.", icon=":material/check:")
    except Exception as e:
        st.toast(f"Export failed: {e!s}", icon=":material/error:")


class ContractSource(StrEnum):
    TABLES = "tables"
    FILE = "file"


class WizardRowIcon(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    WARNING = "warning"
    INFO = "info"


def _row(icon: WizardRowIcon, text: str, link: dict | None = None) -> dict:
    return {"icon": icon.value, "text": text, "link": link}


def build_wizard_data(table_group_options: list[dict]) -> dict:
    return {
        "open": True,
        "table_groups": table_group_options,
        "generation_sets": list_generation_sets(),
        "default_generation_sets": [DEFAULT_GENERATION_SET],
        "max_file_bytes": contract_file_max_bytes(),
        "table_group": st.session_state.get(WIZARD_TABLE_GROUP_KEY),
        "file_preview": st.session_state.get(WIZARD_PREVIEW_KEY),
        "result": st.session_state.get(WIZARD_RESULT_KEY),
    }


@with_database_session
def wizard_table_group_selected(payload: dict) -> None:
    st.session_state.pop(WIZARD_FILE_KEY, None)
    st.session_state.pop(WIZARD_PREVIEW_KEY, None)
    table_group = TableGroup.get(payload["table_group_id"]) if payload.get("table_group_id") else None
    if table_group is None:
        st.session_state.pop(WIZARD_TABLE_GROUP_KEY, None)
        return
    profile_run_id = resolve_generation_profile_run(table_group)
    profile_run = ProfilingRun.get(profile_run_id) if profile_run_id else None
    st.session_state[WIZARD_TABLE_GROUP_KEY] = {
        "id": str(table_group.id),
        "name": table_group.table_groups_name,
        "profiled_at": make_json_safe(profile_run.profiling_starttime) if profile_run else None,
        "unreached_profiling_age": None if profile_run else _unreached_profiling_age(table_group),
        "tables": catalog_table_names(table_group.id),
    }


def _unreached_profiling_age(table_group: TableGroup) -> int | None:
    """``table_group``'s minimum profiling age in days when it has completed profiling runs but test generation
    reads none of them, because none is that old yet. ``None`` otherwise."""
    delay_days = table_group.profiling_delay_days
    if not delay_days or resolve_generation_profile_run(table_group) is not None:
        return None
    return delay_days if ProfilingRun.latest_readable_id(table_group.id) is not None else None


def _days(count: int) -> str:
    return f"{count} {'day' if count == 1 else 'days'}"


def contract_file_uploaded(payload: dict) -> None:
    st.session_state.pop(WIZARD_FILE_KEY, None)
    payload = payload if isinstance(payload, dict) else {}
    file = payload.get("file") if isinstance(payload.get("file"), dict) else {}
    content = file.get("content") if isinstance(file.get("content"), str) else ""
    try:
        text = read_contract_file(content)
    except UnreadableContractFileError as e:
        st.session_state[WIZARD_PREVIEW_KEY] = {"error": str(e), "problems": []}
        return
    table_group_id = payload.get("table_group_id")
    with database_session():
        table_group = TableGroup.get(table_group_id)
        connection = Connection.get(table_group.connection_id)
        preview = import_preview(text, table_group, connection, None)
    if not preview.get("error"):
        st.session_state[WIZARD_FILE_KEY] = {"table_group_id": table_group_id, "content": text}
    st.session_state[WIZARD_PREVIEW_KEY] = preview


def contract_file_cleared(*_) -> None:
    st.session_state.pop(WIZARD_FILE_KEY, None)
    st.session_state.pop(WIZARD_PREVIEW_KEY, None)


def add_test_suite_clicked(*_) -> None:
    for key in WIZARD_KEYS:
        st.session_state.pop(key, None)
    st.session_state[ADD_DIALOG_KEY] = True


def wizard_closed(*_) -> None:
    for key in (ADD_DIALOG_KEY, *WIZARD_KEYS):
        st.session_state.pop(key, None)


def add_test_suite_confirmed(payload: dict) -> None:
    if (st.session_state.get(WIZARD_RESULT_KEY) or {}).get("success"):
        return
    suite_type = SuiteType.CONTRACT if payload.get("suite_type") == SuiteType.CONTRACT.value else SuiteType.REGULAR
    values = {key: payload.get(key, default) for key, default in _FORM_DEFAULTS.items()}
    if suite_type is SuiteType.REGULAR:
        values["deactivate_invalid_tests"] = payload.get("deactivate_invalid_tests", False)
    candidate = TestSuite(test_suite=payload.get("test_suite"), **values)
    if errors := validate_test_suite_fields(candidate, field_names=_form_field_labels(suite_type), quote_fields=False):
        st.session_state[WIZARD_RESULT_KEY] = {"success": False, "message": " ".join(errors)}
        return
    tests = payload.get("tests") or {}
    file = st.session_state.get(WIZARD_FILE_KEY)
    if suite_type is SuiteType.CONTRACT and tests.get("start_from") == ContractSource.FILE:
        if not file:
            st.session_state[WIZARD_RESULT_KEY] = {"success": False, "message": "Choose an ODCS contract file."}
            return
        if file["table_group_id"] != payload.get("table_groups_id"):
            st.session_state[WIZARD_RESULT_KEY] = {
                "success": False,
                "message": "The file was read for another table group. Choose it again.",
            }
            return
    try:
        with database_session():
            table_group = TableGroup.get(payload.get("table_groups_id"))
            suite = TestSuite(
                project_code=table_group.project_code,
                connection_id=table_group.connection_id,
                table_groups_id=table_group.id,
                test_suite=payload.get("test_suite"),
                suite_type=suite_type.value,
                **values,
            )
            if suite_type is SuiteType.REGULAR:
                rows = _add_test_suite(suite, tests)
            elif tests.get("start_from") == ContractSource.FILE:
                rows = _add_contract_from_file(suite, table_group, file["content"])
            else:
                rows = _add_contract_from_tables(suite, table_group, tests.get("table_names") or [])
    except Exception:
        LOG.exception("Adding a test suite failed")
        st.session_state[WIZARD_RESULT_KEY] = {
            "success": False,
            "message": "Something went wrong while adding the test suite.",
        }
        return
    st.cache_data.clear()
    st.session_state[WIZARD_RESULT_KEY] = {"success": True, "rows": rows}


def _add_test_suite(suite: TestSuite, tests: dict) -> list[dict]:
    suite.save()
    record(AuditAction.TEST_SUITE_CREATED, suite)
    get_current_session().commit()
    rows = [_row(WizardRowIcon.SUCCESS, f"Test suite {suite.test_suite} created.")]
    if not tests.get("generate"):
        rows.append(_row(WizardRowIcon.SKIPPED, "Tests: skipped. Generate them later on the Test Suites page."))
        return rows
    try:
        run_test_generation_and_report(JobSource.ui, suite.id, tests.get("generation_sets") or [])
        generated = TestSuite.test_definition_stats(suite.id).total
    except Exception:
        LOG.exception(f"Generating tests for test suite {suite.id} failed")
        get_current_session().rollback()
        rows.append(_row(WizardRowIcon.WARNING, "Tests: generation failed. Generate them on the Test Suites page."))
        return rows
    if not generated:
        rows.append(_row(WizardRowIcon.SKIPPED, "Tests: none were generated."))
        return rows
    link = {
        "label": "View them on the test definitions page",
        "href": "test-suites:definitions",
        "params": {"test_suite_id": str(suite.id), "project_code": suite.project_code},
    }
    rows.append(_row(WizardRowIcon.SUCCESS, f"Tests: {generated} generated.", link))
    return rows


def _add_contract_from_tables(suite: TestSuite, table_group: TableGroup, table_names: list[str]) -> list[dict]:
    connection = Connection.get(table_group.connection_id)
    created = create_contract(suite, table_group, connection, table_names)
    record_contract_created(created.suite)
    generation = created.generation
    name = created.suite.test_suite
    not_in_catalog = generation.tables_not_in_catalog if generation else []
    not_profiled = [table for table in generation.tables_not_profiled if table not in not_in_catalog] if generation else []
    no_quality_tests = (
        not created.generation_failed and generation is not None and generation.term_count == 0 and bool(not_profiled)
    )
    kind = " schema" if no_quality_tests else ""
    rows = [
        _row(
            WizardRowIcon.SUCCESS,
            f"Contract {name} created{_with_tests(created.suite.id, kind)}.",
            _contract_link(created.suite),
        )
    ]
    if created.generation_failed:
        rows.append(
            _row(WizardRowIcon.WARNING, "Generating the contract failed. Generate its tests on the Test Suites page.")
        )
    elif no_quality_tests:
        in_catalog = [table for table in generation.tables_declared if table not in not_in_catalog]
        if set(not_profiled) != set(in_catalog):
            cause = f"has no profiling results for {', '.join(not_profiled)}"
        elif age := _unreached_profiling_age(table_group):
            cause = f"has no profiling run that has reached its minimum profiling age of {_days(age)}"
        else:
            cause = "has not been profiled"
        rows.append(
            _row(
                WizardRowIcon.SKIPPED,
                f"No quality tests were generated because {table_group.table_groups_name} {cause}.",
            )
        )
    elif generation is not None and not_profiled:
        rows.append(
            _row(WizardRowIcon.INFO, f"No profiling results, so no quality tests for: {', '.join(not_profiled)}.")
        )
    rows += _contract_info_rows(created.custom_server_reason, connection.sql_flavor_code, not_in_catalog)
    return rows


def _add_contract_from_file(suite: TestSuite, table_group: TableGroup, content: str) -> list[dict]:
    connection = Connection.get(table_group.connection_id)
    plan = prepare_import(content, table_group, connection, None)
    created = create_contract_from_import(suite, table_group, connection, plan)
    record_contract_created(created.suite)
    text = f"Contract {created.suite.test_suite} created{_with_tests(created.suite.id)}."
    if unverifiable := len(plan.unverifiable_rules):
        text += f" {unverifiable} {'rule cannot' if unverifiable == 1 else 'rules cannot'} be verified."
    rows = [_row(WizardRowIcon.SUCCESS, text, _contract_link(created.suite))]
    if created.conformance_failed:
        rows.append(
            _row(
                WizardRowIcon.WARNING,
                "Its schema conformance tests were not updated. Generate Tests updates them.",
            )
        )
    rows += _contract_info_rows(created.custom_server_reason, connection.sql_flavor_code, plan.tables_not_in_catalog)
    return rows


def _contract_link(suite: TestSuite) -> dict:
    return {
        "label": "View it on the test definitions page",
        "href": "test-suites:definitions",
        "params": {"test_suite_id": str(suite.id), "project_code": suite.project_code},
    }


def _with_tests(suite_id: UUID, kind: str = "") -> str:
    test_count = TestSuite.test_definition_stats(suite_id).total
    if not test_count:
        return ""
    return f" with {test_count}{kind} {'test' if test_count == 1 else 'tests'}"


def _contract_info_rows(
    reason: CustomServerReason | None, sql_flavor_code: str, tables_not_in_catalog: list[str]
) -> list[dict]:
    rows = []
    if reason is not None:
        if reason.server_type is None:
            flavor = FLAVOR_CODE_TO_LABEL.get(sql_flavor_code, sql_flavor_code)
            cause = f"a {flavor} connection has no matching server type in the standard"
        else:
            cause = (
                f"the connection does not supply {', '.join(reason.missing_fields)}, "
                f"which {reason.server_type.value} requires"
            )
        rows.append(_row(WizardRowIcon.WARNING, f"The contract's server entry is custom because {cause}."))
    if tables_not_in_catalog:
        rows.append(_row(WizardRowIcon.WARNING, f"Not in the data catalog: {', '.join(tables_not_in_catalog)}."))
    return rows
