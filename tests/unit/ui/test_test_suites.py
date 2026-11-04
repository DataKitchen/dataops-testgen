"""Tests for the Test Suites dialog save path in testgen.ui.views.test_suites."""

import base64
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

import testgen
from testgen.commands.test_generation import ContractGenerationResult
from testgen.common.contract_creation import ContractCreation, ContractImportCreation
from testgen.common.contract_import import ContractTermReason, TermChange
from testgen.common.enums import JobSource, RegenerationGroup, SuiteType
from testgen.common.models.project import Project
from testgen.common.models.suite_version import ContractState
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.servers import CustomServerReason, ServerType
from testgen.common.test_definition_export_import_service import ImportAction
from testgen.ui.views import test_suites as view
from testgen.ui.views.dialogs import generate_tests_dialog as dialog

pytestmark = pytest.mark.unit

RESULT_KEY = "ts_form_dialog:result"


def _integrity_error(constraint: str) -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception(f'duplicate key value violates unique constraint "{constraint}"'))


@pytest.fixture
def session_state():
    state: dict = {}
    with (
        patch.object(view.st, "session_state", state),
        patch.object(view, "get_test_suite_summaries"),
    ):
        yield state


@pytest.fixture(autouse=True)
def test_count():
    """The suite's test count, as the card shows it; tests that report one set ``return_value``."""
    with patch.object(TestSuite, "test_definition_stats", return_value=SimpleNamespace(total=0)) as stats:
        yield stats


def _form(**overrides) -> dict:
    data = {
        "test_suite": "Orders",
        "table_groups_id": str(uuid4()),
        "test_suite_description": "",
        "severity": None,
        "export_to_observability": False,
        "dq_score_exclude": False,
        "deactivate_invalid_tests": False,
        "component_key": "",
        "component_type": "dataset",
        "component_name": "",
    }
    data.update(overrides)
    return data


@pytest.mark.usefixtures("db_session_mock")
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"test_suite": ""}, "Test Suite Name is required."),
        ({"component_key": "k" * 101}, "Component Key must be at most 100 characters."),
        ({"severity": "Failed"}, "Severity must be one of Fail, Warning, Log."),
    ],
)
def test_edit_reports_a_validation_failure_without_saving(session_state, overrides, message):
    with (
        patch.object(view, "get_test_suite") as mock_get_test_suite,
        patch.object(TestSuite, "save", autospec=True) as mock_save,
    ):
        view.save_test_suite_form(_form(test_suite_id=str(uuid4()), **overrides))

    assert session_state[RESULT_KEY] == {"success": False, "message": message}
    mock_save.assert_not_called()
    mock_get_test_suite.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_edit_rejected_by_validation_leaves_the_stored_suite_untouched(session_state):
    """The dialog's session commits on return, so a rejected edit must not have been
    applied to the stored suite first."""
    stored = MagicMock(test_suite="Orders", severity="Warning", component_name="Orders")
    with patch.object(view, "get_test_suite", return_value=stored) as mock_get:
        view.save_test_suite_form(
            _form(test_suite_id=str(uuid4()), severity="Critical", component_name="x" * 101)
        )

    assert session_state[RESULT_KEY]["success"] is False
    mock_get.assert_not_called()
    assert stored.severity == "Warning"
    assert stored.component_name == "Orders"
    stored.save.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_edit_applies_the_form_to_the_stored_suite(session_state):
    stored = MagicMock(test_suite="Orders")
    with patch.object(view, "get_test_suite", return_value=stored):
        view.save_test_suite_form(
            _form(test_suite_id=str(uuid4()), severity="Log", component_key="orders")
        )

    assert stored.severity == "Log"
    assert stored.component_key == "orders"
    stored.save.assert_called_once()


@pytest.mark.usefixtures("db_session_mock")
def test_edit_renames_the_stored_suite(session_state):
    stored = MagicMock(test_suite="Orders")
    with patch.object(view, "get_test_suite", return_value=stored):
        view.save_test_suite_form(_form(test_suite_id=str(uuid4()), test_suite="Sales Orders"))

    assert stored.test_suite == "Sales Orders"
    stored.save.assert_called_once()


def test_edit_reports_a_name_another_suite_in_the_project_holds(session_state, db_session_mock):
    stored = MagicMock(test_suite="Orders")
    stored.save.side_effect = _integrity_error("test_suites_name_unique")
    with (
        patch.object(view, "get_test_suite", return_value=stored),
        patch.object(view, "record") as record,
    ):
        view.save_test_suite_form(_form(test_suite_id=str(uuid4()), test_suite="Sales Orders"))

    assert session_state[RESULT_KEY] == {
        "success": False,
        "message": "A test suite or contract named Sales Orders already exists in this project.",
    }
    db_session_mock.rollback.assert_called_once()
    record.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_edit_lets_other_integrity_errors_through(session_state):
    stored = MagicMock(test_suite="Orders")
    stored.save.side_effect = _integrity_error("test_suites_connections_fk")
    with patch.object(view, "get_test_suite", return_value=stored), pytest.raises(IntegrityError):
        view.save_test_suite_form(_form(test_suite_id=str(uuid4())))


@pytest.mark.usefixtures("db_session_mock")
def test_a_saved_edit_drops_every_cached_read(session_state):
    with (
        patch.object(view, "get_test_suite", return_value=MagicMock(test_suite="Orders")),
        patch.object(view.st.cache_data, "clear") as clear,
    ):
        view.save_test_suite_form(_form(test_suite_id=str(uuid4()), test_suite="Sales Orders"))

    clear.assert_called_once_with()


@pytest.mark.usefixtures("db_session_mock")
def test_editing_a_contract_keeps_its_deactivation_setting(session_state):
    stored = MagicMock(test_suite="Orders", deactivate_invalid_tests=True)
    form = _form(test_suite_id=str(uuid4()), suite_type="contract")
    del form["deactivate_invalid_tests"]
    with patch.object(view, "get_test_suite", return_value=stored):
        view.save_test_suite_form(form)

    assert stored.deactivate_invalid_tests is True
    stored.save.assert_called_once()


@pytest.mark.usefixtures("db_session_mock")
def test_editing_a_regular_suite_writes_the_deactivation_setting(session_state):
    stored = MagicMock(test_suite="Orders", deactivate_invalid_tests=False)
    with patch.object(view, "get_test_suite", return_value=stored):
        view.save_test_suite_form(_form(test_suite_id=str(uuid4()), deactivate_invalid_tests=True))

    assert stored.deactivate_invalid_tests is True


def test_dialog_offers_only_severities_execution_recognizes():
    """Execution reads a suite's severity as ``Fail``, ``Warning`` or ``Log``; any other stored
    value turns the suite's failures into warnings."""
    source = (Path(testgen.__file__).parent / "ui/static/js/components/test_suite_form.js").read_text()
    block = source[source.index("const severityOptions = ["):]
    block = block[:block.index("];")]

    assert "value: 'Failed'" not in block
    for value in ("'Fail'", "'Warning'", "'Log'", "null"):
        assert f"value: {value}" in block


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, (SuiteType.REGULAR, SuiteType.CONTRACT)),
        ("regular", (SuiteType.REGULAR,)),
        ("contract", (SuiteType.CONTRACT,)),
        ("monitor", (SuiteType.REGULAR, SuiteType.CONTRACT)),
        ("nonsense", (SuiteType.REGULAR, SuiteType.CONTRACT)),
    ],
)
def test_the_type_filter_never_reaches_monitor_suites(value, expected):
    assert view.suite_types_for_filter(value) == expected


def _version(number, frozen):
    return MagicMock(version=number, frozen_at=datetime(2026, 1, 1) if frozen else None)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ContractState(active=_version(3, True), draft=None), "v3 active"),
        (ContractState(active=_version(3, True), draft=_version(4, False)), "v3 active · v4 draft"),
        (ContractState(active=None, draft=_version(1, False)), "v1 draft"),
        (None, ""),
    ],
)
def test_version_caption(state, expected):
    assert view.version_caption(state) == expected


def test_project_summary_counts_contracts():
    with patch("testgen.common.models.project.get_current_session") as session_mock:
        session_mock.return_value.execute.return_value.first.return_value = None
        Project.get_summary("demo")

    sql = " ".join(str(session_mock.return_value.execute.call_args.args[0]).split())
    assert "AND test_suites.suite_type = 'contract'" in sql
    assert "AS contract_count" in sql


@pytest.mark.usefixtures("db_session_mock")
def test_generating_a_contract_sends_its_groups_and_no_generation_sets(session_state):
    result = ContractGenerationResult(3, ["orders"], [], [], [RegenerationGroup.TESTS])
    with (
        patch.object(view.TestSuite, "get", return_value=SimpleNamespace(suite_type=SuiteType.CONTRACT)),
        patch.object(view, "run_test_generation_and_report", return_value=result) as generate,
    ):
        view.generate_tests_confirmed({
            "test_suite_id": "abc", "test_suite_name": "orders", "generation_sets": ["Standard"],
            "regenerate": ["tests"],
        })

    generate.assert_called_once_with(JobSource.ui, "abc", None, regenerate=["tests"])


@pytest.mark.usefixtures("db_session_mock")
def test_a_contracts_dialog_stays_open_and_says_what_was_regenerated(session_state):
    session_state[view.GENERATE_TESTS_DIALOG_KEY] = "abc"
    result = ContractGenerationResult(
        3, ["orders", "lines"], [], ["lines"], [RegenerationGroup.PROFILING, RegenerationGroup.CATALOG],
    )
    with (
        patch.object(view.TestSuite, "get", return_value=SimpleNamespace(suite_type=SuiteType.CONTRACT)),
        patch.object(view, "run_test_generation_and_report", return_value=result),
    ):
        view.generate_tests_confirmed(
            {"test_suite_id": "abc", "test_suite_name": "orders", "regenerate": ["profiling", "catalog"]},
        )

    assert session_state[view.GENERATE_TESTS_DIALOG_KEY] == "abc"
    assert session_state[view.GENERATE_TESTS_RESULT_KEY] == {
        "success": True,
        "message": (
            "The contract 'orders' was regenerated: profiling results and catalog metadata. "
            "The values profiling observed were not refreshed for tables that have not been profiled."
        ),
    }


def test_a_contract_regeneration_without_profiling_says_nothing_about_profiled_values():
    result = ContractGenerationResult(3, ["orders"], [], ["orders"], [RegenerationGroup.CATALOG])

    assert view.contract_regeneration_message("orders", ["catalog"], result) == (
        "The contract 'orders' was regenerated: catalog metadata."
    )


def test_a_contract_regeneration_says_when_requested_tests_found_no_profiled_table():
    result = ContractGenerationResult(0, ["orders"], [], ["orders"], [])

    assert view.contract_regeneration_message("orders", ["tests"], result) == (
        "No tests were regenerated for the contract 'orders' because none of its tables have been profiled."
    )


def test_a_contract_regeneration_names_every_part_profiling_could_not_supply():
    result = ContractGenerationResult(
        3, ["orders", "lines"], [], ["lines"], [RegenerationGroup.TESTS, RegenerationGroup.PROFILING],
    )

    assert view.contract_regeneration_message("orders", ["tests", "profiling"], result) == (
        "The contract 'orders' was regenerated: tests and profiling results. "
        "Tests and the values profiling observed were not refreshed for tables that have not been profiled."
    )


def _generate_tests_data(suite_type: SuiteType, *, profiled: bool = True) -> dict:
    with (
        patch.object(
            view.TestSuite, "get",
            return_value=SimpleNamespace(id="abc", test_suite="orders", table_groups_id="tg", suite_type=suite_type),
        ),
        patch.object(view.TableGroup, "get"),
        patch.object(view, "resolve_generation_profile_run", return_value="run" if profiled else None),
        patch.object(view, "list_generation_sets", return_value=["Standard"]),
        patch.object(view, "resolve_generation_sets", return_value=["Standard"]),
        patch.object(view, "get_generation_set_members", return_value={}),
        patch.object(view, "get_overriding_test_types", return_value={}),
        patch.object(view, "get_test_suite_refresh_warning", return_value={"test_ct": 64}),
        patch.object(view, "get_value_hash_warning", return_value=None),
        patch.object(view, "get_sampled_unavailable_test_types", return_value={}),
        patch.object(view, "get_generation_set_test_types", return_value=[]),
    ):
        return view.build_generate_tests_data("abc")


@pytest.mark.parametrize("suite_type", [SuiteType.CONTRACT, SuiteType.REGULAR])
def test_both_suite_kinds_carry_the_warning_about_the_tests_generation_replaces(session_state, suite_type):
    assert _generate_tests_data(suite_type)["refresh_warning"] == {"test_ct": 64}


def test_a_contracts_dialog_offers_the_three_regeneration_groups(session_state):
    data = _generate_tests_data(SuiteType.CONTRACT)

    assert [(group["value"], group["label"]) for group in data["regeneration_groups"]] == [
        ("tests", "Tests"), ("profiling", "Profiling results"), ("catalog", "Catalog metadata"),
    ]
    assert data["regeneration_groups"][0]["help"] == (
        "Regenerates the contract's tests from the latest profiling. Locked tests are kept."
    )
    assert data["tests_disabled_reason"] is None
    assert data["generation_sets"] == []


def test_an_unprofiled_contracts_dialog_disables_tests_with_its_reason(session_state):
    data = _generate_tests_data(SuiteType.CONTRACT, profiled=False)

    assert data["tests_disabled_reason"] == "The table group has not been profiled. Run profiling to regenerate tests."


def test_a_test_suites_dialog_offers_no_regeneration_groups(session_state):
    data = _generate_tests_data(SuiteType.REGULAR)

    assert "regeneration_groups" not in data
    assert data["generation_sets"] == ["Standard"]


@pytest.mark.parametrize(
    ("suite_type", "expected"),
    [
        (SuiteType.REGULAR, {"LOV_Match": "Value Match", "Match_Lead_Space_Ct": "Match Leading Spaces"}),
        (SuiteType.CONTRACT, {"LOV_Match": "Value Match"}),
    ],
)
def test_notes_the_test_types_a_sampled_profile_cannot_support_for_what_the_suite_generates(
    session_state, suite_type, expected
):
    unavailable = {"LOV_Match": "Value Match", "Match_Lead_Space_Ct": "Match Leading Spaces"}
    with (
        patch.object(
            view.TestSuite, "get",
            return_value=SimpleNamespace(id="abc", test_suite="orders", table_groups_id="tg", suite_type=suite_type),
        ),
        patch.object(view.TableGroup, "get"),
        patch.object(view, "resolve_generation_profile_run", return_value="run"),
        patch.object(view, "list_generation_sets", return_value=["Standard"]),
        patch.object(view, "resolve_generation_sets", return_value=["Standard"]),
        patch.object(view, "get_generation_set_members", return_value={}),
        patch.object(view, "get_overriding_test_types", return_value={}),
        patch.object(view, "get_test_suite_refresh_warning", return_value=None),
        patch.object(view, "get_value_hash_warning", return_value=None),
        patch.object(view, "get_sampled_unavailable_test_types", return_value=unavailable) as sampled_unavailable,
        patch.object(view, "get_generation_set_test_types", return_value=["LOV_Match", "Required"]) as contract_set,
    ):
        data = view.build_generate_tests_data("abc")

    assert data["sampled_unavailable_test_types"] == expected
    sampled_unavailable.assert_called_once_with("tg")
    if suite_type == SuiteType.CONTRACT:
        contract_set.assert_called_once_with(view.CONTRACT_GENERATION_SET)


@pytest.mark.usefixtures("db_session_mock")
def test_generating_a_test_suite_sends_its_sets_whatever_the_payload_claims(session_state):
    with (
        patch.object(view.TestSuite, "get", return_value=SimpleNamespace(suite_type=SuiteType.REGULAR)),
        patch.object(view, "run_test_generation_and_report") as generate,
    ):
        view.generate_tests_confirmed({
            "test_suite_id": "abc", "test_suite_name": "orders", "generation_sets": ["Standard"], "is_contract": True,
            "regenerate": ["tests"],
        })

    generate.assert_called_once_with(JobSource.ui, "abc", ["Standard"], regenerate=None)


@pytest.mark.usefixtures("db_session_mock")
@pytest.mark.parametrize(("suite_type", "opens_draft"), [(SuiteType.CONTRACT, True), (SuiteType.REGULAR, False)])
def test_locking_edited_tests_of_a_contract_lands_on_its_draft(suite_type, opens_draft):
    events = []
    with (
        patch.object(dialog.TestSuite, "get", return_value=SimpleNamespace(suite_type=suite_type)),
        patch.object(
            dialog.TestDefinition, "resolve_write_target", side_effect=lambda _id: events.append("draft") or ("v", {}),
        ),
        patch.object(dialog, "execute_db_query", side_effect=lambda *_: events.append("lock")),
    ):
        dialog.lock_edited_tests("abc")

    assert events == (["draft", "lock"] if opens_draft else ["lock"])


MIB = 1024 * 1024


def _wizard(**overrides) -> dict:
    payload = {
        "suite_type": "regular",
        "test_suite": "Orders",
        "table_groups_id": str(uuid4()),
        "test_suite_description": "",
        "severity": None,
        "export_to_observability": False,
        "dq_score_exclude": False,
        "deactivate_invalid_tests": False,
        "component_key": "",
        "component_type": "dataset",
        "component_name": "",
        "tests": {"generate": False, "generation_sets": []},
    }
    payload.update(overrides)
    return payload


def _table_group(group_id=None):
    return MagicMock(
        id=group_id or uuid4(), project_code="demo", connection_id=3, table_groups_name="sales", profiling_delay_days=0
    )


def _data_url(text: bytes) -> str:
    return f"data:application/x-yaml;base64,{base64.b64encode(text).decode()}"


def _saved(suite):
    suite.id = uuid4()


def _definitions_link(suite_id):
    return {
        "label": "View them on the test definitions page",
        "href": "test-suites:definitions",
        "params": {"test_suite_id": str(suite_id), "project_code": "demo"},
    }


def _contract(tests=None, **overrides):
    return _wizard(suite_type="contract", tests=tests or {"start_from": "tables", "table_names": ["orders"]}, **overrides)


def _creation(generation=None, failed=False, reason=None):
    def create(suite, *_):
        suite.id = uuid4()
        return ContractCreation(suite, reason, generation, failed)

    return create


def _generated(term_count=142, not_in_catalog=(), not_profiled=()):
    return ContractGenerationResult(term_count, ["orders", "lines"], list(not_in_catalog), list(not_profiled))


def _rows(session_state):
    return [(row["icon"], row["text"]) for row in session_state[view.WIZARD_RESULT_KEY]["rows"]]


@pytest.mark.usefixtures("db_session_mock")
def test_a_validation_failure_writes_nothing(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(TestSuite, "save", autospec=True) as save,
        patch.object(view, "create_contract") as create,
    ):
        view.add_test_suite_confirmed(_wizard(test_suite=""))

    assert session_state[view.WIZARD_RESULT_KEY] == {"success": False, "message": "Test Suite Name is required."}
    save.assert_not_called()
    create.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_a_test_suite_without_generation_is_saved_and_reports_skipped(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(TestSuite, "save", autospec=True, side_effect=_saved) as save,
        patch.object(view, "run_test_generation_and_report") as generate,
    ):
        view.add_test_suite_confirmed(_wizard())

    save.assert_called_once()
    assert save.call_args.args[0].suite_type == "regular"
    generate.assert_not_called()
    assert session_state[view.WIZARD_RESULT_KEY]["rows"] == [
        {"icon": "success", "text": "Test suite Orders created.", "link": None},
        {"icon": "skipped", "text": "Tests: skipped. Generate them later on the Test Suites page.", "link": None},
    ]


@pytest.mark.usefixtures("db_session_mock")
def test_the_wizard_reports_a_name_another_suite_in_the_project_holds(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(TestSuite, "save", autospec=True, side_effect=_integrity_error("test_suites_name_unique")),
    ):
        view.add_test_suite_confirmed(_wizard(test_suite=" Orders "))

    assert session_state[view.WIZARD_RESULT_KEY] == {
        "success": False,
        "message": "A test suite or contract named Orders already exists in this project.",
    }


@pytest.mark.usefixtures("db_session_mock")
def test_the_wizard_reports_a_contract_name_another_suite_in_the_project_holds(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view, "catalog_table_names", return_value=["orders"]),
        patch.object(view, "create_contract", side_effect=_integrity_error("test_suites_name_unique")),
    ):
        view.add_test_suite_confirmed(_contract())

    assert session_state[view.WIZARD_RESULT_KEY]["message"] == (
        "A test suite or contract named Orders already exists in this project."
    )


@pytest.mark.usefixtures("db_session_mock")
def test_the_wizard_saves_the_name_without_surrounding_spaces(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(TestSuite, "save", autospec=True, side_effect=_saved) as save,
    ):
        view.add_test_suite_confirmed(_wizard(test_suite=" Orders  "))

    assert save.call_args.args[0].test_suite == "Orders"


@pytest.mark.usefixtures("db_session_mock")
def test_a_test_suite_with_generation_generates_with_the_chosen_sets(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(TestSuite, "save", autospec=True, side_effect=_saved) as save,
        patch.object(view, "run_test_generation_and_report") as generate,
        patch.object(TestSuite, "test_definition_stats", return_value=SimpleNamespace(total=96)),
    ):
        view.add_test_suite_confirmed(_wizard(tests={"generate": True, "generation_sets": ["Standard"]}))

    saved = save.call_args.args[0]
    generate.assert_called_once_with(JobSource.ui, saved.id, ["Standard"])
    assert session_state[view.WIZARD_RESULT_KEY]["rows"][1] == {
        "icon": "success", "text": "Tests: 96 generated.", "link": _definitions_link(saved.id),
    }


def test_a_test_suite_generation_failure_rolls_back_to_the_suite_and_reports_it(session_state, db_session_mock):
    calls = MagicMock()
    db_session_mock.commit.side_effect = lambda: calls.commit()
    db_session_mock.rollback.side_effect = lambda: calls.rollback()

    def fail_generation(*_args):
        calls.generate()
        raise RuntimeError("generation broke")

    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(TestSuite, "save", autospec=True, side_effect=_saved),
        patch.object(view, "run_test_generation_and_report", side_effect=fail_generation),
    ):
        view.add_test_suite_confirmed(_wizard(tests={"generate": True, "generation_sets": ["Standard"]}))

    assert [name for name, _, _ in calls.mock_calls][:3] == ["commit", "generate", "rollback"]
    assert session_state[view.WIZARD_RESULT_KEY]["success"] is True
    assert _rows(session_state)[1] == ("warning", "Tests: generation failed. Generate them on the Test Suites page.")


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_from_tables_is_created_with_those_tables(session_state, test_count):
    test_count.return_value = SimpleNamespace(total=144)
    group = _table_group()
    connection = MagicMock()
    with (
        patch.object(view.TableGroup, "get", return_value=group),
        patch.object(view.Connection, "get", return_value=connection),
        patch.object(view, "create_contract", side_effect=_creation(_generated())) as create,
    ):
        view.add_test_suite_confirmed(_contract(tests={"start_from": "tables", "table_names": ["orders", "lines"]}))

    suite, table_group, connection, tables = create.call_args.args
    assert suite.suite_type == "contract"
    assert (table_group, connection, tables) == (group, connection, ["orders", "lines"])
    assert _rows(session_state) == [("success", "Contract Orders created with 144 tests.")]
    assert session_state[view.WIZARD_RESULT_KEY]["rows"][0]["link"] == {
        **_definitions_link(suite.id), "label": "View it on the test definitions page",
    }


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_on_an_unprofiled_table_group_says_why_it_has_no_quality_tests(session_state):
    generated = _generated(term_count=0, not_profiled=["orders", "lines"])
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(generated)),
    ):
        view.add_test_suite_confirmed(_contract())

    assert _rows(session_state) == [
        ("success", "Contract Orders created."),
        ("skipped", "No quality tests were generated because sales has not been profiled."),
    ]


@pytest.mark.usefixtures("db_session_mock")
@pytest.mark.parametrize(("delay_days", "cause"), [
    (1, "has no profiling run that has reached its minimum profiling age of 1 day"),
    (3, "has no profiling run that has reached its minimum profiling age of 3 days"),
])
def test_a_contract_whose_profiling_runs_are_too_recent_says_so(session_state, delay_days, cause):
    group = _table_group()
    group.profiling_delay_days = delay_days
    generated = _generated(term_count=0, not_profiled=["orders", "lines"])
    with (
        patch.object(view.TableGroup, "get", return_value=group),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(generated)),
        patch.object(view, "resolve_generation_profile_run", return_value=None),
        patch.object(view.ProfilingRun, "latest_readable_id", return_value=uuid4()),
    ):
        view.add_test_suite_confirmed(_contract())

    assert _rows(session_state) == [
        ("success", "Contract Orders created."),
        ("skipped", f"No quality tests were generated because sales {cause}."),
    ]


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_with_no_quality_tests_counts_its_schema_tests(session_state, test_count):
    test_count.return_value = SimpleNamespace(total=2)
    generated = _generated(term_count=0, not_profiled=["orders", "lines"])
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(generated)),
    ):
        view.add_test_suite_confirmed(_contract())

    assert _rows(session_state) == [
        ("success", "Contract Orders created with 2 schema tests."),
        ("skipped", "No quality tests were generated because sales has not been profiled."),
    ]


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_whose_profiled_tables_yield_no_quality_tests_names_the_unprofiled_ones(session_state):
    generated = _generated(term_count=0, not_profiled=["lines"])
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(generated)),
    ):
        view.add_test_suite_confirmed(_contract())

    assert _rows(session_state) == [
        ("success", "Contract Orders created."),
        ("skipped", "No quality tests were generated because sales has no profiling results for lines."),
    ]


@pytest.mark.usefixtures("db_session_mock")
def test_a_partly_profiled_contract_names_the_tables_without_quality_tests(session_state, test_count):
    test_count.return_value = SimpleNamespace(total=13)
    generated = _generated(term_count=12, not_in_catalog=["ghost"], not_profiled=["lines", "ghost"])
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(generated)),
    ):
        view.add_test_suite_confirmed(_contract())

    assert _rows(session_state) == [
        ("success", "Contract Orders created with 13 tests."),
        ("info", "No profiling results, so no quality tests for: lines."),
        ("warning", "Not in the data catalog: ghost."),
    ]


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_generation_failure_still_reports_the_contract(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(failed=True)),
    ):
        view.add_test_suite_confirmed(_contract())

    assert session_state[view.WIZARD_RESULT_KEY]["success"] is True
    assert _rows(session_state) == [
        ("success", "Contract Orders created."),
        ("warning", "Generating the contract failed. Generate its tests on the Test Suites page."),
    ]


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_never_sends_the_deactivation_setting(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(_generated())) as create,
    ):
        view.add_test_suite_confirmed(_contract(deactivate_invalid_tests=True))

    assert not create.call_args.args[0].deactivate_invalid_tests


def _change(action, table, column, test_type="Unique", reason=ContractTermReason.NEW):
    return TermChange(action, reason, test_type, table, column, None)


def _plan(changes=(), unverifiable=(), **overrides):
    plan = MagicMock(
        document_name="Vendor",
        changes=list(changes),
        unverifiable_rules=list(unverifiable),
        server_type_warning=None,
        tables_not_in_catalog=[],
    )
    plan.count.side_effect = lambda action: sum(1 for change in plan.changes if change.action is action)
    for key, value in overrides.items():
        setattr(plan, key, value)
    return plan


def _file_creation(**fields):
    def create(suite, *_):
        suite.id = uuid4()
        return ContractImportCreation(suite, fields.get("reason"), uuid4(), fields.get("conformance_failed", False))

    return create


def _stored_file(group_id):
    return {"table_group_id": group_id, "content": "<yaml>"}


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_from_a_file_replans_the_stored_payload_and_keeps_the_step_one_name(session_state, test_count):
    test_count.return_value = SimpleNamespace(total=57)
    group = _table_group()
    connection = MagicMock()
    payload = _contract(tests={"start_from": "file"}, table_groups_id=str(group.id))
    session_state[view.WIZARD_FILE_KEY] = _stored_file(str(group.id))
    plan = _plan([_change(ImportAction.create, "t", f"c{i}") for i in range(56)], unverifiable=["a", "b"])
    with (
        patch.object(view.TableGroup, "get", return_value=group),
        patch.object(view.Connection, "get", return_value=connection),
        patch.object(view, "prepare_import", return_value=plan) as prepare,
        patch.object(view, "create_contract_from_import", side_effect=_file_creation()) as create,
    ):
        view.add_test_suite_confirmed(payload)

    prepare.assert_called_once_with("<yaml>", group, connection, None)
    assert create.call_args.args[0].test_suite == "Orders"
    assert _rows(session_state) == [("success", "Contract Orders created with 57 tests. 2 rules cannot be verified.")]
    assert session_state[view.WIZARD_RESULT_KEY]["rows"][0]["link"] == {
        **_definitions_link(create.call_args.args[0].id), "label": "View it on the test definitions page",
    }


@pytest.mark.usefixtures("db_session_mock")
def test_a_file_with_one_unverifiable_rule_uses_the_singular(session_state, test_count):
    test_count.return_value = SimpleNamespace(total=1)
    group = _table_group()
    session_state[view.WIZARD_FILE_KEY] = _stored_file(str(group.id))
    plan = _plan([_change(ImportAction.create, "t", "c")], unverifiable=["a"])
    with (
        patch.object(view.TableGroup, "get", return_value=group),
        patch.object(view.Connection, "get"),
        patch.object(view, "prepare_import", return_value=plan),
        patch.object(view, "create_contract_from_import", side_effect=_file_creation()),
    ):
        view.add_test_suite_confirmed(_contract(tests={"start_from": "file"}, table_groups_id=str(group.id)))

    assert _rows(session_state) == [("success", "Contract Orders created with 1 test. 1 rule cannot be verified.")]


@pytest.mark.usefixtures("db_session_mock")
def test_a_file_plan_for_another_table_group_is_refused(session_state):
    session_state[view.WIZARD_FILE_KEY] = _stored_file(str(uuid4()))
    with patch.object(view, "create_contract_from_import") as create:
        view.add_test_suite_confirmed(_contract(tests={"start_from": "file"}))

    assert session_state[view.WIZARD_RESULT_KEY] == {
        "success": False, "message": "The file was read for another table group. Choose it again.",
    }
    create.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_from_a_file_without_a_stored_file_is_refused(session_state):
    with patch.object(view, "create_contract_from_import") as create:
        view.add_test_suite_confirmed(_contract(tests={"start_from": "file"}))

    assert session_state[view.WIZARD_RESULT_KEY] == {"success": False, "message": "Choose an ODCS contract file."}
    create.assert_not_called()


def _import_with(session_state, creation, plan=None):
    group = _table_group()
    session_state[view.WIZARD_FILE_KEY] = _stored_file(str(group.id))
    with (
        patch.object(view.TableGroup, "get", return_value=group),
        patch.object(view.Connection, "get", return_value=MagicMock(sql_flavor_code="postgresql")),
        patch.object(view, "prepare_import", return_value=plan or _plan([_change(ImportAction.create, "t", "c")])),
        patch.object(view, "create_contract_from_import", side_effect=creation),
    ):
        view.add_test_suite_confirmed(_contract(tests={"start_from": "file"}, table_groups_id=str(group.id)))


def _created_with(text: str) -> str:
    return re.search(r"created with \d+ ([^.]+)\.", text).group(1)


@pytest.mark.usefixtures("db_session_mock")
def test_a_contract_names_its_tests_alike_from_tables_and_from_a_file(session_state, test_count):
    test_count.return_value = SimpleNamespace(total=2)
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(_generated(term_count=2))),
    ):
        view.add_test_suite_confirmed(_contract())
    from_tables = _rows(session_state)[0][1]

    session_state.pop(view.WIZARD_RESULT_KEY)
    _import_with(
        session_state, _file_creation(),
        _plan([_change(ImportAction.create, "t", "a"), _change(ImportAction.create, "t", "b")]),
    )
    from_file = _rows(session_state)[0][1]

    assert _created_with(from_tables) == _created_with(from_file)


@pytest.mark.usefixtures("db_session_mock")
def test_an_import_whose_conformance_failed_says_so(session_state):
    _import_with(session_state, _file_creation(conformance_failed=True))

    assert (
        "warning", "Its schema conformance tests were not updated. Generate Tests updates them.",
    ) in _rows(session_state)


@pytest.mark.usefixtures("db_session_mock")
def test_a_custom_server_reason_is_shown(session_state):
    _import_with(session_state, _file_creation(reason=CustomServerReason(server_type=None, missing_fields=())))

    assert ("warning", "The contract's server entry is custom because a PostgreSQL connection has no matching server type in the standard.") in _rows(session_state)


@pytest.mark.usefixtures("db_session_mock")
def test_a_custom_server_with_missing_fields_names_them(session_state):
    reason = CustomServerReason(server_type=ServerType.POSTGRES, missing_fields=("host", "port"))
    _import_with(session_state, _file_creation(reason=reason))

    assert (
        "warning",
        "The contract's server entry is custom because the connection does not supply host, port, "
        "which postgres requires.",
    ) in _rows(session_state)


@pytest.mark.usefixtures("db_session_mock")
def test_tables_missing_from_the_catalog_are_named(session_state):
    _import_with(session_state, _file_creation(), _plan([_change(ImportAction.create, "t", "c")], tables_not_in_catalog=["ghost"]))

    assert ("warning", "Not in the data catalog: ghost.") in _rows(session_state)


@pytest.mark.usefixtures("db_session_mock")
def test_tables_missing_from_the_catalog_are_named_for_a_contract_from_tables(session_state):
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(_generated(not_in_catalog=["ghost"]))),
    ):
        view.add_test_suite_confirmed(_contract())

    assert _rows(session_state)[-1] == ("warning", "Not in the data catalog: ghost.")


@pytest.mark.usefixtures("db_session_mock")
def test_add_after_a_success_creates_nothing_more(session_state):
    session_state[view.WIZARD_RESULT_KEY] = {"success": True, "rows": []}
    with (
        patch.object(TestSuite, "save", autospec=True) as save,
        patch.object(view, "create_contract") as create,
        patch.object(view, "create_contract_from_import") as create_import,
    ):
        view.add_test_suite_confirmed(_wizard())

    save.assert_not_called()
    create.assert_not_called()
    create_import.assert_not_called()
    assert session_state[view.WIZARD_RESULT_KEY] == {"success": True, "rows": []}


@pytest.mark.usefixtures("db_session_mock")
def test_an_unexpected_failure_before_creation_writes_nothing(session_state):
    with (
        patch.object(view.TableGroup, "get", side_effect=RuntimeError),
        patch.object(TestSuite, "save", autospec=True) as save,
    ):
        view.add_test_suite_confirmed(_wizard())

    assert session_state[view.WIZARD_RESULT_KEY] == {
        "success": False, "message": "Something went wrong while adding the test suite.",
    }
    save.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_selecting_a_table_group_loads_its_tables_and_profiling(session_state):
    group = _table_group()
    run = MagicMock(profiling_starttime=datetime(2026, 8, 14, 9, 30, tzinfo=UTC))
    with (
        patch.object(view.TableGroup, "get", return_value=group),
        patch.object(view, "catalog_table_names", return_value=["a", "b"]),
        patch.object(view, "resolve_generation_profile_run", return_value=uuid4()),
        patch.object(view.ProfilingRun, "get", return_value=run),
    ):
        view.wizard_table_group_selected({"table_group_id": str(group.id)})

    assert session_state[view.WIZARD_TABLE_GROUP_KEY] == {
        "id": str(group.id),
        "name": "sales",
        "profiled_at": 1786699800,
        "unreached_profiling_age": None,
        "tables": ["a", "b"],
    }


@pytest.mark.usefixtures("db_session_mock")
@pytest.mark.parametrize(
    ("delay_days", "latest_run", "expected_age"),
    [
        (0, None, None),
        (0, uuid4(), None),
        (3, None, None),
        (3, uuid4(), 3),
    ],
    ids=["never-profiled", "no-delay", "delay-never-profiled", "runs-younger-than-delay"],
)
def test_selecting_a_table_group_without_a_generation_run_says_whether_its_runs_are_too_recent(
    session_state, delay_days, latest_run, expected_age
):
    group = _table_group()
    group.profiling_delay_days = delay_days
    with (
        patch.object(view.TableGroup, "get", return_value=group),
        patch.object(view, "catalog_table_names", return_value=[]),
        patch.object(view, "resolve_generation_profile_run", return_value=None),
        patch.object(view.ProfilingRun, "latest_readable_id", return_value=latest_run),
    ):
        view.wizard_table_group_selected({"table_group_id": str(group.id)})

    selected = session_state[view.WIZARD_TABLE_GROUP_KEY]
    assert selected["profiled_at"] is None
    assert selected["unreached_profiling_age"] == expected_age


@pytest.mark.usefixtures("db_session_mock")
def test_selecting_another_table_group_drops_the_file_and_preview(session_state):
    session_state[view.WIZARD_FILE_KEY] = {"content": "x"}
    session_state[view.WIZARD_PREVIEW_KEY] = {"rows": []}
    view.wizard_table_group_selected({"table_group_id": None})

    assert view.WIZARD_FILE_KEY not in session_state
    assert view.WIZARD_PREVIEW_KEY not in session_state


def _upload(content: bytes, group_id=None) -> dict:
    return {"table_group_id": group_id or str(uuid4()), "file": {"content": _data_url(content)}}


def test_an_unreadable_file_is_reported_without_planning(session_state):
    with patch.object(view, "import_preview") as preview:
        view.contract_file_uploaded(_upload(b""))

    assert session_state[view.WIZARD_PREVIEW_KEY] == {"error": "The file is empty.", "problems": []}
    assert view.WIZARD_FILE_KEY not in session_state
    preview.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_a_file_that_cannot_be_imported_keeps_no_payload(session_state):
    refusal = {"error": "This file cannot be imported.", "problems": ["a", "b"]}
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "import_preview", return_value=refusal),
    ):
        view.contract_file_uploaded(_upload(b"x: 1"))

    assert session_state[view.WIZARD_PREVIEW_KEY] == refusal
    assert view.WIZARD_FILE_KEY not in session_state


@pytest.mark.usefixtures("db_session_mock")
def test_a_valid_file_stores_its_payload_and_a_creation_preview(session_state):
    group_id = str(uuid4())
    table_group = _table_group()
    preview = {"creating": True, "rows": []}
    with (
        patch.object(view.TableGroup, "get", return_value=table_group),
        patch.object(view.Connection, "get") as connection,
        patch.object(view, "import_preview", return_value=preview) as build,
    ):
        view.contract_file_uploaded(_upload(b"text", group_id))

    assert session_state[view.WIZARD_FILE_KEY] == {"table_group_id": group_id, "content": "text"}
    assert session_state[view.WIZARD_PREVIEW_KEY] == preview
    build.assert_called_once_with("text", table_group, connection.return_value, None)


def test_clearing_the_file_drops_its_payload_and_preview(session_state):
    session_state[view.WIZARD_FILE_KEY] = {}
    session_state[view.WIZARD_PREVIEW_KEY] = {}
    view.contract_file_cleared()

    assert view.WIZARD_FILE_KEY not in session_state
    assert view.WIZARD_PREVIEW_KEY not in session_state


def test_closing_the_wizard_clears_its_state(session_state):
    keys = (
        view.ADD_DIALOG_KEY, view.WIZARD_TABLE_GROUP_KEY, view.WIZARD_FILE_KEY,
        view.WIZARD_PREVIEW_KEY, view.WIZARD_RESULT_KEY,
    )
    session_state.update(dict.fromkeys(keys, True))
    view.wizard_closed()

    assert not any(key in session_state for key in keys)


def test_opening_the_wizard_drops_the_state_of_a_previous_one(session_state):
    keys = (view.WIZARD_TABLE_GROUP_KEY, view.WIZARD_FILE_KEY, view.WIZARD_PREVIEW_KEY)
    session_state.update(dict.fromkeys(keys, True))
    session_state[view.WIZARD_RESULT_KEY] = {"success": True, "rows": []}
    view.add_test_suite_clicked()

    assert session_state == {view.ADD_DIALOG_KEY: True}


def _regular_generation(session_state, total):
    order = []
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(TestSuite, "save", autospec=True, side_effect=_saved),
        patch.object(view, "get_current_session", return_value=MagicMock(commit=lambda: order.append("commit"))),
        patch.object(view, "run_test_generation_and_report", side_effect=lambda *_: order.append("generate")),
        patch.object(TestSuite, "test_definition_stats", return_value=SimpleNamespace(total=total)),
    ):
        view.add_test_suite_confirmed(_wizard(tests={"generate": True, "generation_sets": ["Standard"]}))
    return order


@pytest.mark.usefixtures("db_session_mock")
def test_the_suite_is_committed_before_tests_are_generated(session_state):
    assert _regular_generation(session_state, 96) == ["commit", "generate"]


@pytest.mark.usefixtures("db_session_mock")
def test_a_suite_that_generated_no_tests_says_so(session_state):
    _regular_generation(session_state, 0)

    assert session_state[view.WIZARD_RESULT_KEY]["rows"][1] == {
        "icon": "skipped", "text": "Tests: none were generated.", "link": None,
    }


@pytest.mark.usefixtures("db_session_mock")
@pytest.mark.parametrize(
    ("total", "text"),
    [(1, "Contract Orders created with 1 test."), (0, "Contract Orders created.")],
)
def test_a_contract_counts_its_tests_only_when_there_are_some(session_state, test_count, total, text):
    test_count.return_value = SimpleNamespace(total=total)
    with (
        patch.object(view.TableGroup, "get", return_value=_table_group()),
        patch.object(view.Connection, "get"),
        patch.object(view, "create_contract", side_effect=_creation(_generated(term_count=total))),
    ):
        view.add_test_suite_confirmed(_contract())

    assert _rows(session_state) == [("success", text)]


@pytest.mark.usefixtures("db_session_mock")
def test_a_file_with_no_creates_states_no_count(session_state):
    _import_with(session_state, _file_creation(), _plan([_change(ImportAction.skip, "t", "c")]))

    assert _rows(session_state) == [("success", "Contract Orders created.")]


@pytest.mark.parametrize(
    "payload",
    [None, {"table_group_id": "x", "file": None}, {"table_group_id": "x", "file": "text"}, {"file": {"content": 5}}],
)
def test_a_malformed_upload_never_raises(session_state, payload):
    view.contract_file_uploaded(payload)

    assert session_state[view.WIZARD_PREVIEW_KEY]["error"] == "The file could not be read."


def test_a_malformed_data_url_is_not_reported_as_empty(session_state):
    view.contract_file_uploaded({"table_group_id": "x", "file": {"content": "no-comma"}})

    assert session_state[view.WIZARD_PREVIEW_KEY]["error"] == "The file could not be read."


@pytest.mark.usefixtures("db_session_mock")
@pytest.mark.parametrize(
    ("suite_type", "message"),
    [(SuiteType.CONTRACT, "Contract Orders has been deleted."), (SuiteType.REGULAR, "Test Suite Orders has been deleted.")],
)
def test_the_delete_message_names_the_suite_by_its_type(session_state, suite_type, message):
    session_state["ts_delete_dialog"] = {"test_suite_name": "Orders", "suite_type": suite_type}
    with (
        patch.object(view.TestRun, "has_active_job_for", return_value=False),
        patch.object(view.TestSuite, "cascade_delete"),
        patch.object(view, "get_project_summary"),
        patch.object(view.st, "toast") as toast,
    ):
        view.execute_ts_delete(str(uuid4()))

    assert toast.call_args.args[0] == message
