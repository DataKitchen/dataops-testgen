"""Tests for the MCP test-suite write tools — create / update for regular (non-monitor) suites."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.test_generation import ContractGenerationResult
from testgen.common.contract_service import InitializedContract
from testgen.common.enums import SuiteType
from testgen.common.odcs.servers import CustomServerReason, ServerType
from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.test_suites"
CREATION = "testgen.common.contract_creation"


def _patch_perms(allowed=("demo",), memberships=None, permission="edit", role="role_a"):
    memberships = memberships or dict.fromkeys(allowed, role)
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(memberships=memberships, permission=permission, username="test_user"),
    )


def _mock_table_group(**overrides) -> MagicMock:
    tg_id = overrides.get("id", uuid4())
    tg = MagicMock()
    tg.id = tg_id
    tg.project_code = overrides.get("project_code", "demo")
    tg.connection_id = overrides.get("connection_id", 42)
    tg.table_groups_name = overrides.get("table_groups_name", "Sample TG")
    return tg


def _mock_test_suite(**overrides) -> MagicMock:
    suite = MagicMock()
    suite.id = overrides.get("id", uuid4())
    suite.project_code = overrides.get("project_code", "demo")
    suite.test_suite = overrides.get("test_suite", "Sample Suite")
    suite.connection_id = overrides.get("connection_id", 42)
    suite.table_groups_id = overrides.get("table_groups_id", uuid4())
    suite.test_suite_description = overrides.get("test_suite_description", None)
    suite.severity = overrides.get("severity", None)
    suite.export_to_observability = overrides.get("export_to_observability", False)
    suite.dq_score_exclude = overrides.get("dq_score_exclude", False)
    suite.deactivate_invalid_tests = overrides.get("deactivate_invalid_tests", False)
    suite.component_key = overrides.get("component_key", None)
    suite.component_type = overrides.get("component_type", None)
    suite.component_name = overrides.get("component_name", None)
    suite.suite_type = overrides.get("suite_type", SuiteType.REGULAR)
    suite.generation_sets = overrides.get("generation_sets", None)
    return suite


# ---------------------------------------------------------------------------
# create_test_suite
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_happy_path(mock_resolve, mock_suite_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(
        test_suite="Sales Tests",
        project_code="demo",
        table_groups_id=tg.id,
    )
    mock_suite_cls.return_value = instance

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        out = create_test_suite(table_group_id=str(tg.id), test_suite_name="Sales Tests")

    # The tool does not call instance.save(); it relies on session.add + flush.
    # This checks that wiring only — the smoke test exercises actual DB persistence.
    mock_suite_cls.assert_called_once()
    instance.save.assert_not_called()
    db_session_mock.add.assert_called_once_with(instance)
    db_session_mock.flush.assert_called_once()
    assert "Test Suite `Sales Tests` created" in out
    assert "**Project:** `demo`" in out
    assert "Sample TG" in out


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_default_export_matches_ui(mock_resolve, mock_suite_cls, db_session_mock):
    """S1 review feedback: export_to_observability defaults to False (matches the UI dialog),
    not the model's legacy Y default."""
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(table_group_id=str(tg.id), test_suite_name="Anything")

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["export_to_observability"] is False
    # S3 review feedback: component_type defaults to "dataset" on create
    assert kwargs["component_type"] == "dataset"
    assert kwargs["dq_score_exclude"] is False
    assert kwargs["deactivate_invalid_tests"] is False


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_passes_all_new_args_to_model(mock_resolve, mock_suite_cls, db_session_mock):
    """S9: create_test_suite accepts the full UI-editable surface (export, dq_score_exclude, component_*)
    so the LLM can configure the suite in one round-trip."""
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(
            table_group_id=str(tg.id),
            test_suite_name="Full",
            description="d",
            severity_default="Warning",
            export_to_observability=True,
            component_key="ck",
            component_type="dataset",
            component_name="cn",
            dq_score_exclude=True,
            deactivate_invalid_tests=True,
        )

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["test_suite_description"] == "d"
    assert kwargs["severity"] == "Warning"
    assert kwargs["export_to_observability"] is True
    assert kwargs["component_key"] == "ck"
    assert kwargs["component_type"] == "dataset"
    assert kwargs["component_name"] == "cn"
    assert kwargs["dq_score_exclude"] is True
    assert kwargs["deactivate_invalid_tests"] is True


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_normalizes_empty_text_args_to_none(mock_resolve, mock_suite_cls, db_session_mock):
    """S4: NullIfEmptyString writes "" -> NULL; pre-normalize on the way in so the model
    receives the canonical value."""
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(
            table_group_id=str(tg.id),
            test_suite_name="x",
            description="",
            component_key="",
            component_type="",
            component_name="",
        )

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["test_suite_description"] is None
    assert kwargs["component_key"] is None
    assert kwargs["component_type"] is None
    assert kwargs["component_name"] is None


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_with_severity(mock_resolve, mock_suite_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(test_suite="Sev Suite", severity="Fail")
    mock_suite_cls.return_value = instance

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        out = create_test_suite(
            table_group_id=str(tg.id),
            test_suite_name="Sev Suite",
            severity_default="Fail",
        )

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["severity"] == "Fail"
    assert kwargs["suite_type"] == SuiteType.REGULAR
    assert "Fail" in out


@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_invalid_severity(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_table_group()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_test_suite(
            table_group_id=str(uuid4()),
            test_suite_name="Anything",
            severity_default="Critical",
        )
    msg = str(exc.value)
    # S6: error is field-scoped and enumerates valid values without double-labeling.
    assert "severity_default" in msg
    assert "Fail" in msg and "Warning" in msg
    assert "Critical" in msg
    assert "Invalid severity" not in msg  # the double-labeled phrasing is gone


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_defaults_to_regular(mock_resolve, mock_suite_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(table_group_id=str(tg.id), test_suite_name="Anything")

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["suite_type"] == SuiteType.REGULAR


@patch(f"{CREATION}.initialize_contract")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_contract_type_initializes_the_contract(
    mock_resolve, mock_suite_cls, mock_connection_cls, mock_initialize_contract, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(suite_type=SuiteType.CONTRACT)
    mock_suite_cls.return_value = instance
    connection = MagicMock()
    mock_connection_cls.get.return_value = connection

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(
            table_group_id=str(tg.id), test_suite_name="Orders contract", suite_type="Contract"
        )

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["suite_type"] == SuiteType.CONTRACT
    mock_connection_cls.get.assert_called_once_with(tg.connection_id)
    mock_initialize_contract.assert_called_once_with(instance, tg, connection)


def _create_contract(table_names, *, catalog=("orders", "customers"), generation=None):
    """Create a contract through the tool with the catalog and the generation stubbed out."""
    tg = _mock_table_group(table_groups_name="sales")
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_table_group", return_value=tg),
        patch(f"{MODULE}.TestSuite", return_value=_mock_test_suite(suite_type=SuiteType.CONTRACT)),
        patch(f"{MODULE}.Connection"),
        patch(f"{CREATION}.initialize_contract") as initialize,
        patch(f"{MODULE}.contract_document.catalog_table_names", return_value=list(catalog)),
        patch(f"{CREATION}.run_contract_generation", return_value=generation) as generate,
    ):
        from testgen.mcp.tools.test_suites import create_test_suite

        out = create_test_suite(
            table_group_id=str(tg.id), test_suite_name="Orders contract", suite_type="Contract",
            table_names=table_names,
        )
    return out, initialize, generate


def test_create_test_suite_contract_with_tables_generates_them_and_reports_it(db_session_mock):
    generation = ContractGenerationResult(
        term_count=42, tables_declared=["orders", "customers"], tables_not_in_catalog=[], tables_not_profiled=[],
    )

    out, initialize, generate = _create_contract(["orders", "customers", "orders"], generation=generation)

    initialize.assert_called_once()
    generate.assert_called_once_with(initialize.call_args.args[0].id,
                                     table_names=["orders", "customers"])
    assert "**Declared tables:** `orders`, `customers`" in out
    assert "**Tests:** 42" in out
    assert "no profiling results" not in out


def test_create_test_suite_contract_names_the_tables_profiling_has_no_results_for(db_session_mock):
    generation = ContractGenerationResult(
        term_count=3, tables_declared=["orders", "customers"], tables_not_in_catalog=[],
        tables_not_profiled=["customers"],
    )

    out, _, _ = _create_contract(["orders", "customers"], generation=generation)

    assert "`sales` has no profiling results for `customers`, so" in out
    assert "generate_tests" in out


def test_create_test_suite_contract_names_a_table_missing_from_the_catalog_only_once(db_session_mock):
    generation = ContractGenerationResult(
        term_count=0, tables_declared=["orders"], tables_not_in_catalog=["orders"], tables_not_profiled=["orders"],
    )

    out, _, _ = _create_contract(["orders"], generation=generation)

    assert "holds no columns for `orders`" in out
    assert "no profiling results" not in out


def test_create_test_suite_contract_whose_generation_fails_still_reports_the_contract(db_session_mock):
    """The contract is committed before generation, so a failure rolls back to it, and the caller needs
    its ID rather than an error to retry into a duplicate."""
    tg = _mock_table_group(table_groups_name="sales")
    suite = _mock_test_suite(suite_type=SuiteType.CONTRACT)
    calls = MagicMock()
    db_session_mock.commit.side_effect = lambda: calls.commit()
    db_session_mock.rollback.side_effect = lambda: calls.rollback()

    def fail_generation(*_args, **_kwargs):
        calls.generate()
        raise RuntimeError("generation broke")

    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_table_group", return_value=tg),
        patch(f"{MODULE}.TestSuite", return_value=suite),
        patch(f"{MODULE}.Connection"),
        patch(f"{CREATION}.initialize_contract"),
        patch(f"{MODULE}.contract_document.catalog_table_names", return_value=["orders"]),
        patch(f"{CREATION}.run_contract_generation", side_effect=fail_generation),
    ):
        from testgen.mcp.tools.test_suites import create_test_suite

        out = create_test_suite(
            table_group_id=str(tg.id), test_suite_name="Orders contract", suite_type="Contract",
            table_names=["orders"],
        )

    assert str(suite.id) in out
    assert "generating its tables failed" in out
    assert "generate_tests" in out
    assert [name for name, _, _ in calls.mock_calls][:3] == ["commit", "generate", "rollback"]


def test_create_test_suite_contract_without_tables_generates_nothing(db_session_mock):
    out, initialize, generate = _create_contract(None)

    initialize.assert_called_once()
    generate.assert_not_called()
    assert "Declared tables" not in out


def test_create_test_suite_refuses_a_table_the_table_group_does_not_hold_before_creating_anything(db_session_mock):
    with pytest.raises(MCPUserError, match="no tables named `ghost`"):
        _create_contract(["orders", "ghost"])


def test_create_test_suite_refuses_table_names_for_a_regular_suite(db_session_mock):
    tg = _mock_table_group()
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_table_group", return_value=tg),
        patch(f"{MODULE}.TestSuite") as suite_cls,
    ):
        from testgen.mcp.tools.test_suites import create_test_suite

        with pytest.raises(MCPUserError, match="applies only to contracts"):
            create_test_suite(table_group_id=str(tg.id), test_suite_name="Anything", table_names=["orders"])

    suite_cls.assert_not_called()


@patch(f"{CREATION}.initialize_contract")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_contract_card_names_the_type(
    mock_resolve, mock_suite_cls, mock_connection_cls, mock_initialize_contract, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite(suite_type=SuiteType.CONTRACT)
    mock_connection_cls.get.return_value = MagicMock()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        out = create_test_suite(
            table_group_id=str(tg.id), test_suite_name="Orders contract", suite_type="Contract"
        )

    assert "**Type:** Contract" in out


@patch(f"{CREATION}.initialize_contract")
@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_regular_type_does_not_create_a_contract(
    mock_resolve, mock_suite_cls, mock_initialize_contract, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(table_group_id=str(tg.id), test_suite_name="Anything")

    mock_initialize_contract.assert_not_called()


@patch(f"{CREATION}.initialize_contract")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_contract_on_a_flavor_with_no_server_type_says_its_entry_is_custom(
    mock_resolve, mock_suite_cls, mock_connection_cls, mock_initialize_contract, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite(suite_type=SuiteType.CONTRACT)
    connection = MagicMock()
    connection.sql_flavor_code = "redshift_spectrum"
    mock_connection_cls.get.return_value = connection
    mock_initialize_contract.return_value = InitializedContract(
        draft=MagicMock(), custom_server_reason=CustomServerReason(server_type=None)
    )

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        out = create_test_suite(
            table_group_id=str(tg.id), test_suite_name="Orders contract", suite_type="Contract"
        )

    assert (
        "The contract's server entry uses the custom type, because a `Amazon Redshift Spectrum` connection "
        "has no matching server type in the standard."
    ) in out
    assert "redshift_spectrum" not in out


def test_create_test_suite_contract_composition_creates_a_custom_entry_for_a_real_unmapped_flavor(db_session_mock):
    """Keeps contract_service.initialize_contract and build_server_block REAL, so this proves a
    genuinely unmapped flavor creates the contract with a custom entry and says so."""
    tg = _mock_table_group()
    connection = MagicMock(project_host="rs.example", project_port="5439", project_db="analytics", parameters={})
    connection.sql_flavor_code = "redshift_spectrum"

    from testgen.mcp.tools.test_suites import create_test_suite

    with (
        patch(f"{MODULE}.resolve_table_group", return_value=tg),
        patch(f"{MODULE}.TestSuite", return_value=_mock_test_suite(suite_type=SuiteType.CONTRACT)),
        patch(f"{MODULE}.Connection") as mock_connection_cls,
        patch("testgen.common.contract_service.SuiteVersion.next_version_for", return_value=1),
        _patch_perms(),
    ):
        mock_connection_cls.get.return_value = connection
        out = create_test_suite(
            table_group_id=str(tg.id), test_suite_name="Orders contract", suite_type="Contract"
        )

    assert "Test Suite `" in out
    assert "uses the custom type, because a `Amazon Redshift Spectrum` connection" in out
    draft = db_session_mock.add.call_args_list[-1].args[0]
    assert draft.metadata_document["servers"][0]["type"] == "custom"


@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_invalid_suite_type(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_table_group()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_test_suite(
            table_group_id=str(uuid4()),
            test_suite_name="Anything",
            suite_type="Bogus",
        )
    msg = str(exc.value)
    assert "suite_type" in msg
    assert "Regular" in msg and "Contract" in msg
    assert "Bogus" in msg


@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_rejects_monitor_suite_type(mock_resolve, db_session_mock):
    """Monitor suites are created through monitoring setup, not this tool."""
    mock_resolve.return_value = _mock_table_group()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_test_suite(
            table_group_id=str(uuid4()),
            test_suite_name="Anything",
            suite_type="Monitor",
        )
    msg = str(exc.value)
    assert "must be one of Regular, Contract" in msg


@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_empty_name_rejected(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_table_group()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_test_suite(table_group_id=str(uuid4()), test_suite_name="   ")
    assert "`test_suite_name` is required." in str(exc.value)
    db_session_mock.add.assert_not_called()


@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_rejects_values_wider_than_their_columns(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_table_group()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_test_suite(table_group_id=str(uuid4()), test_suite_name="x" * 201, component_key="k" * 101)
    msg = str(exc.value)
    assert "`test_suite_name` must be at most 200 characters." in msg
    assert "`component_key` must be at most 100 characters." in msg
    db_session_mock.add.assert_not_called()


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_strips_whitespace(mock_resolve, mock_suite_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(test_suite="Sales Tests")
    mock_suite_cls.return_value = instance

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(table_group_id=str(tg.id), test_suite_name="  Sales Tests  ")

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["test_suite"] == "Sales Tests"


@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_table_group_not_accessible(mock_resolve, db_session_mock):
    mock_resolve.side_effect = MCPResourceNotAccessible("Table group", str(uuid4()))

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(allowed=("other",)), pytest.raises(MCPResourceNotAccessible):
        create_test_suite(table_group_id=str(uuid4()), test_suite_name="Anything")


def test_create_test_suite_requires_edit(db_session_mock):
    """role_c lacks edit (per conftest matrix)."""
    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(memberships={"demo": "role_c"}), pytest.raises(MCPPermissionDenied):
        create_test_suite(table_group_id=str(uuid4()), test_suite_name="Anything")


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_allows_role_with_edit_but_not_administer(
    mock_resolve, mock_suite_cls, db_session_mock,
):
    """role_d has edit but NOT administer (per conftest matrix) — must still be allowed.

    Mirrors the production data_quality role: write access to suites without
    project-level administer rights.
    """
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(test_suite="DQ Suite")
    mock_suite_cls.return_value = instance

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(memberships={"demo": "role_d"}):
        out = create_test_suite(table_group_id=str(tg.id), test_suite_name="DQ Suite")

    mock_suite_cls.assert_called_once()
    instance.save.assert_not_called()
    assert "Test Suite `DQ Suite` created" in out


# ---------------------------------------------------------------------------
# update_test_suite
# ---------------------------------------------------------------------------


def test_update_test_suite_no_fields_supplied(db_session_mock):
    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_test_suite(test_suite_id=str(uuid4()))
    assert str(exc.value) == "No fields supplied to update."


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_renames(mock_resolve, db_session_mock):
    suite = _mock_test_suite(test_suite="Original Name")
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(test_suite_id=str(suite.id), test_suite_name="New Name")

    suite.save.assert_called_once()
    assert "Test Suite `New Name` updated" in out
    assert "| Field | Before | After |" in out
    assert "Original Name" in out
    assert "New Name" in out


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_multi_field_diff(mock_resolve, db_session_mock):
    suite = _mock_test_suite(
        test_suite="Suite",
        severity=None,
        export_to_observability=True,
        dq_score_exclude=False,
    )
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(
            test_suite_id=str(suite.id),
            severity_default="Warning",
            export_to_observability=False,
            dq_score_exclude=True,
            deactivate_invalid_tests=True,
        )

    suite.save.assert_called_once()
    assert "Default severity" in out
    assert "Warning" in out
    # S13/S15: column header capitalises "Observability" (product name).
    assert "Export to Observability" in out
    assert "Exclude from quality scoring" in out
    assert "Automatically deactivate tests that fail validation" in out
    assert suite.deactivate_invalid_tests is True


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_no_op(mock_resolve, db_session_mock):
    suite = _mock_test_suite(test_suite_description="same", severity="Fail")
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(
            test_suite_id=str(suite.id),
            description="same",
            severity_default="Fail",
        )

    suite.save.assert_not_called()
    assert "No fields changed" in out
    db_session_mock.rollback.assert_called_once()


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_empty_text_arg_on_null_field_is_noop(mock_resolve, db_session_mock):
    """S4 phantom-diff regression: an "" arg on a currently-NULL NullIfEmptyString column must
    NOT show up as a "changed" diff row (the DB would read back identical to before)."""
    suite = _mock_test_suite(
        test_suite_description=None,
        component_key=None,
        component_type=None,
        component_name=None,
    )
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(
            test_suite_id=str(suite.id),
            description="",
            component_key="",
            component_type="",
            component_name="",
        )

    suite.save.assert_not_called()
    assert "No fields changed" in out
    db_session_mock.rollback.assert_called_once()


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_empty_text_arg_clears_populated_field(mock_resolve, db_session_mock):
    """S4 complement: "" on a currently-populated field clears it to NULL and shows in the diff."""
    suite = _mock_test_suite(component_key="existing-key")
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(test_suite_id=str(suite.id), component_key="")

    suite.save.assert_called_once()
    assert "Component key" in out
    assert "existing-key" in out


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_empty_name_rejected(mock_resolve, db_session_mock):
    suite = _mock_test_suite()
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_test_suite(test_suite_id=str(suite.id), test_suite_name="   ")
    assert "`test_suite_name` is required." in str(exc.value)
    suite.save.assert_not_called()


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_invalid_severity_collected(mock_resolve, db_session_mock):
    """Field-level validation collected, then raised together — name + severity errors in one message."""
    suite = _mock_test_suite()
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_test_suite(
            test_suite_id=str(suite.id),
            test_suite_name="",
            severity_default="Critical",
        )
    msg = str(exc.value)
    assert "Update rejected" in msg
    assert "`test_suite_name` is required." in msg
    # S6: field-scoped phrasing, no double-labeled "Invalid severity"
    assert "severity_default" in msg
    assert "Fail" in msg and "Warning" in msg
    assert "Invalid severity" not in msg
    suite.save.assert_not_called()


def test_update_test_suite_monitor_suite_unified_wording(db_session_mock):
    """Exercising a monitor suite must surface the unified missing-or-inaccessible
    error, not a distinct rejection. The filter side-effect is in
    ``resolve_test_suite``; this test exercises it end-to-end with the real
    TestSuite.get patched to behave as it would in DB (filter applied → None)."""
    with patch("testgen.mcp.tools.common.TestSuite") as mock_ts:
        mock_ts.get.return_value = None  # filter excluded the monitor suite
        from testgen.mcp.tools.test_suites import update_test_suite

        with _patch_perms(), pytest.raises(MCPResourceNotAccessible) as exc:
            update_test_suite(test_suite_id=str(uuid4()), test_suite_name="Anything")
    assert "Test suite" in str(exc.value)
    assert "not found or not accessible" in str(exc.value)


def test_update_test_suite_not_accessible(db_session_mock):
    """Suite in a project the user can't access → unified wording."""
    with patch("testgen.mcp.tools.common.TestSuite") as mock_ts:
        mock_ts.get.return_value = None
        from testgen.mcp.tools.test_suites import update_test_suite

        with _patch_perms(allowed=("other",)), pytest.raises(MCPResourceNotAccessible):
            update_test_suite(test_suite_id=str(uuid4()), test_suite_name="Anything")


def test_update_test_suite_requires_edit(db_session_mock):
    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(memberships={"demo": "role_c"}), pytest.raises(MCPPermissionDenied):
        update_test_suite(test_suite_id=str(uuid4()), test_suite_name="Anything")


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_allows_role_with_edit_but_not_administer(mock_resolve, db_session_mock):
    """role_d has edit but NOT administer — must be allowed (mirrors production data_quality)."""
    suite = _mock_test_suite(test_suite="DQ Suite")
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(memberships={"demo": "role_d"}):
        out = update_test_suite(test_suite_id=str(suite.id), description="updated by data_quality")

    suite.save.assert_called_once()
    assert "Test Suite `DQ Suite` updated" in out


@patch(f"{CREATION}.initialize_contract")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_contract_missing_fields_names_the_fields_and_the_type(
    mock_resolve, mock_suite_cls, mock_connection_cls, mock_initialize_contract, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite(suite_type=SuiteType.CONTRACT)
    connection = MagicMock()
    connection.sql_flavor_code = "postgresql"
    mock_connection_cls.get.return_value = connection
    mock_initialize_contract.return_value = InitializedContract(
        draft=MagicMock(),
        custom_server_reason=CustomServerReason(server_type=ServerType.POSTGRES, missing_fields=("host", "port")),
    )

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        out = create_test_suite(
            table_group_id=str(tg.id), test_suite_name="Orders contract", suite_type="Contract"
        )

    assert (
        "The contract's server entry uses the custom type, because the connection does not supply "
        "`host`, `port`, which `postgres` requires."
    ) in out


def test_a_typed_server_entry_adds_no_note():
    from testgen.mcp.tools.test_suites import _render_created_suite

    out = _render_created_suite(_mock_test_suite(suite_type=SuiteType.CONTRACT), table_group_name="TG")

    assert "custom type" not in out
