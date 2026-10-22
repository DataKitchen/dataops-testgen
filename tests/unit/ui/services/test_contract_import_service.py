import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.contract_import import (
    AppliedImport,
    ContractIdentityError,
    ContractImportPlan,
    ContractTermReason,
    TermChange,
)
from testgen.common.contract_service import InvalidContractDocumentError
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.test_definition_export_import_service import ImportAction
from testgen.ui.services import contract_import_service as service

pytestmark = pytest.mark.unit

MIB = 1024 * 1024
MB = 1_000_000
TARGET_ID = "2a91b0d4-0000-0000-0000-000000000001"
INCOMING_ID = "77d0c1e2-0000-0000-0000-000000000002"


def _data_url(text: bytes) -> str:
    return f"data:application/x-yaml;base64,{base64.b64encode(text).decode()}"


def _change(action, table, column, test_type="Unique", reason=ContractTermReason.NEW):
    return TermChange(action, reason, test_type, table, column, None)


def _plan(changes=(), unverifiable=()) -> ContractImportPlan:
    return ContractImportPlan(
        document_id=TARGET_ID,
        document_name="orders_contract",
        metadata_document={},
        changes=list(changes),
        unverifiable_rules=list(unverifiable),
        unresolved_declarations=[],
    )


@pytest.fixture
def short_names():
    rows = [SimpleNamespace(test_type="Unique", test_name_short="Unique Values")]
    with patch.object(service.TestType, "select_where", return_value=rows):
        yield


@pytest.mark.parametrize(
    ("configured", "state_mb", "expected"),
    [
        (10 * MIB, 25, 10 * MIB),
        (20 * MIB, 25, 25 * MB * 3 // 4 - 64 * 1024),
        (10 * MIB, 8, 8 * MB * 3 // 4 - 64 * 1024),
    ],
)
def test_the_contract_file_limit_is_capped_by_streamlits_widget_state_size(configured, state_mb, expected):
    with (
        patch.object(service.settings, "CONTRACT_IMPORT_MAX_BYTES", configured),
        patch.object(service.st.config, "get_option", return_value=state_mb) as get_option,
    ):
        assert service.contract_file_max_bytes() == expected

    get_option.assert_called_once_with("server.maxWidgetStateSize")


def test_a_file_is_read_as_text():
    assert service.read_contract_file(_data_url("name: orders ✓".encode())) == "name: orders ✓"


def test_an_oversize_file_is_refused_before_it_is_read():
    with (
        patch.object(service, "contract_file_max_bytes", return_value=10),
        patch.object(service.base64, "b64decode") as decode,
        pytest.raises(service.UnreadableContractFileError, match=r"^The file is larger than the 10 bytes limit\.$"),
    ):
        service.read_contract_file(_data_url(b"x" * 2000))
    decode.assert_not_called()


def test_a_file_over_the_limit_once_decoded_is_refused():
    with (
        patch.object(service, "contract_file_max_bytes", return_value=10),
        pytest.raises(service.UnreadableContractFileError, match="larger than the 10 bytes limit"),
    ):
        service.read_contract_file(_data_url(b"x" * 11))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (_data_url(b""), "The file is empty."),
        (_data_url(b"\xff\xfe\x00"), "The file is not a text file."),
        ("not a data url", "The file could not be read."),
        ("data:application/x-yaml;base64,%%%", "The file could not be read."),
    ],
    ids=["empty", "not-utf8", "no-header", "not-base64"],
)
def test_an_unreadable_file_is_refused(content, message):
    with pytest.raises(service.UnreadableContractFileError) as raised:
        service.read_contract_file(content)
    assert str(raised.value) == message


@pytest.mark.usefixtures("short_names")
def test_a_preview_lists_deletions_first_with_display_names():
    changes = [
        _change(ImportAction.create, "orders", "id"),
        _change(ImportAction.delete, "orders", "ship", "Required", ContractTermReason.ABSENT),
        _change(ImportAction.create, "lines", "qty", "Value Range"),
    ]
    with patch.object(service, "prepare_import", return_value=_plan(changes)):
        preview = service.import_preview("text", MagicMock(), MagicMock(), None)

    assert [row["action_code"] for row in preview["rows"]] == ["delete", "create", "create"]
    assert preview["rows"][1]["test_name"] == "Value Range"
    assert preview["rows"][2]["test_name"] == "Unique Values"
    assert preview["rows"][0]["reason"] == "Not in the file"
    assert preview["summary"] == {"create": 2, "update": 0, "delete": 1, "skip": 0}
    assert preview["creating"] is True


@pytest.mark.usefixtures("short_names")
def test_a_preview_into_an_existing_contract_is_not_a_creation():
    suite = MagicMock()
    table_group, connection = MagicMock(), MagicMock()
    with patch.object(service, "prepare_import", return_value=_plan()) as prepare:
        preview = service.import_preview("text", table_group, connection, suite)

    assert preview["creating"] is False
    prepare.assert_called_once_with("text", table_group, connection, suite)


@pytest.mark.usefixtures("short_names")
def test_a_long_preview_is_truncated_at_500_rows():
    changes = [_change(ImportAction.create, "t", f"c{i:03}") for i in range(501)]
    with patch.object(service, "prepare_import", return_value=_plan(changes)):
        preview = service.import_preview("text", MagicMock(), MagicMock(), None)

    assert len(preview["rows"]) == 500
    assert preview["truncated"] is True
    assert preview["total_rows"] == 501


@pytest.mark.usefixtures("short_names")
def test_a_preview_counts_the_rules_that_cannot_be_verified():
    with patch.object(service, "prepare_import", return_value=_plan(unverifiable=["a", "b"])):
        assert service.import_preview("text", MagicMock(), MagicMock(), None)["unverifiable_count"] == 2


def test_an_invalid_document_lists_its_problems():
    with patch.object(service, "prepare_import", side_effect=InvalidContractDocumentError(["a", "b"])):
        preview = service.import_preview("x: 1", MagicMock(), MagicMock(), None)

    assert preview == {"error": "This file cannot be imported.", "problems": ["a", "b"]}


def test_a_file_of_another_contract_says_how_to_import_it():
    with patch.object(service, "prepare_import", side_effect=ContractIdentityError(TARGET_ID, INCOMING_ID)):
        preview = service.import_preview("text", MagicMock(), MagicMock(), MagicMock())

    assert preview == {
        "error": "This file is a different contract.",
        "problems": [
            f"Its id is {INCOMING_ID}, but this contract's is {TARGET_ID}. To import it into this contract, "
            f"change the file's id to {TARGET_ID}.",
        ],
    }


def test_an_unexpected_failure_is_reported_without_details():
    with patch.object(service, "prepare_import", side_effect=RuntimeError("boom")):
        preview = service.import_preview("text", MagicMock(), MagicMock(), None)

    assert preview == {"error": "Something went wrong while reading this file.", "problems": []}


@pytest.mark.usefixtures("short_names")
def test_a_failure_while_serializing_the_preview_falls_back_to_the_generic_error():
    with (
        patch.object(service, "prepare_import", return_value=_plan()),
        patch.object(service, "_serialize_plan", side_effect=KeyError("x")),
    ):
        preview = service.import_preview("text", MagicMock(), MagicMock(), None)

    assert preview == {"error": "Something went wrong while reading this file.", "problems": []}


def _import(plan, delete_confirmed=False, applied=None, draft=None):
    suite = MagicMock(id=uuid4(), table_groups_id=uuid4())
    table_group = MagicMock()
    connection = MagicMock(sql_flavor_code="postgresql")
    draft = draft or SuiteVersion(id=uuid4(), version=4, frozen_at=None)
    applied = applied or AppliedImport(version_id=draft.id, conformance_failed=False)
    with (
        patch.object(service.TableGroup, "get", return_value=table_group),
        patch.object(service.Connection, "get", return_value=connection),
        patch.object(service, "prepare_import", side_effect=[plan] if not isinstance(plan, Exception) else plan),
        patch.object(service, "apply_import", return_value=applied) as apply,
        patch.object(service.SuiteVersion, "get", return_value=draft),
    ):
        result = service.import_into_contract("text", suite, delete_confirmed)
    return result, apply, suite, table_group


def test_an_import_lands_in_the_draft():
    plan = _plan([_change(ImportAction.create, "orders", "id")])
    result, apply, suite, table_group = _import(plan)

    assert result == {"success": True, "message": "The contract was imported into v4 draft."}
    apply.assert_called_once_with(plan, suite, table_group, service.SqlFlavorCode("postgresql"))


def test_an_import_with_deletions_needs_them_confirmed():
    plan = _plan([_change(ImportAction.delete, "orders", "ship", reason=ContractTermReason.ABSENT)])
    result, apply, *_ = _import(plan, delete_confirmed=False)

    assert result == {
        "success": False,
        "message": "This import deletes terms. Confirm the deletion to import the file.",
    }
    apply.assert_not_called()


def test_an_import_with_confirmed_deletions_is_applied():
    plan = _plan([_change(ImportAction.delete, "orders", "ship", reason=ContractTermReason.ABSENT)])
    result, apply, *_ = _import(plan, delete_confirmed=True)

    assert result["success"] is True
    apply.assert_called_once()


def test_an_import_whose_conformance_failed_says_so():
    draft = SuiteVersion(id=uuid4(), version=4, frozen_at=None)
    result, *_ = _import(_plan(), applied=AppliedImport(version_id=draft.id, conformance_failed=True), draft=draft)

    assert result == {
        "success": True,
        "message": "The contract was imported into v4 draft. Its schema conformance tests were not updated. "
        "Generate Tests updates them.",
    }


def test_an_import_refused_on_confirm_writes_nothing():
    result, apply, *_ = _import(InvalidContractDocumentError(["a"]))

    assert result == {"success": False, "message": "This file cannot be imported."}
    apply.assert_not_called()
