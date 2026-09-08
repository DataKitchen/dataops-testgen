import base64
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.test_definition_export_import_service import (
    EXPORT_FORMAT_VERSION,
    ImportAction,
    ImportItem,
    ImportItemTD,
    ImportMode,
    ImportReason,
    ImportResponse,
    ImportSummary,
    InvalidImportPayload,
    OnAbsence,
    OnMatch,
    OnNew,
    Origin,
)
from testgen.ui.views.test_definitions import (
    IMPORT_POLICY_DEFAULTS,
    _build_import_preview,
    _import_config,
    _import_policy,
    _import_result_message,
    _refuse_import,
    _run_import,
    get_test_definitions_json_data,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _stub_database_session():
    """The preview and apply paths open their own session inside a try so a failure rolls
    back. Nothing here talks to a real database."""
    with patch("testgen.ui.views.test_definitions.database_session"):
        yield


def _policy(**overrides) -> dict:
    return {**IMPORT_POLICY_DEFAULTS, **overrides}


def _encode(payload: dict) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"data:application/json;base64,{encoded}"


def _payload(**overrides) -> dict:
    return {
        "version": EXPORT_FORMAT_VERSION,
        "definitions": [{"test_type": "Alpha_Trunc", "table_name": "orders", "column_name": "email"}],
        **overrides,
    }


def _summary(created=0, updated=0, skipped=0, deleted=0):
    return MagicMock(created=created, updated=updated, skipped=skipped, deleted=deleted)


# --- import policy ---


def test_policy_defaults_match_the_rest_and_mcp_surfaces():
    """The dialog exposes the same three axes as the API, so it must not drift into
    friendlier or more destructive defaults than the surfaces it mirrors."""
    assert IMPORT_POLICY_DEFAULTS == {
        "on_new": OnNew.create,
        "on_match": OnMatch.overwrite_unlocked,
        "on_absence": OnAbsence.do_nothing,
    }


def test_policy_reads_each_axis_from_the_payload():
    policy = _import_policy({
        "on_new": "create_and_lock",
        "on_match": "overwrite_all",
        "on_absence": "delete_unlocked",
    })
    assert policy == {
        "on_new": OnNew.create_and_lock,
        "on_match": OnMatch.overwrite_all,
        "on_absence": OnAbsence.delete_unlocked,
    }


def test_unrecognized_axis_falls_back_without_dragging_down_the_others():
    policy = _import_policy({"on_new": "nonsense", "on_absence": "delete_all"})
    assert policy["on_new"] == OnNew.create
    assert policy["on_match"] == OnMatch.overwrite_unlocked
    assert policy["on_absence"] == OnAbsence.delete_all


def test_config_carries_the_policy_and_the_mode():
    config = _import_config(_policy(on_absence=OnAbsence.delete_all), ImportMode.apply)
    assert config.mode == ImportMode.apply
    assert config.on_absence == OnAbsence.delete_all
    assert config.on_new == OnNew.create


# --- export ---


def test_export_serializes_with_exclude_defaults():
    """Import distinguishes set fields from defaulted ones via model_fields_set. Exporting
    without exclude_defaults would force-write every default over the target on re-import."""
    document = MagicMock()
    document.model_dump_json.return_value = "{}"
    test_suite = MagicMock(project_code="proj", test_suite="suite")

    with patch("testgen.ui.views.test_definitions.export_definitions", return_value=document) as export:
        get_test_definitions_json_data(MagicMock(), test_suite)

    export.assert_called_once_with(test_suite, Origin.both, None, None)
    assert document.model_dump_json.call_args.kwargs["exclude_defaults"] is True


def test_export_returns_json_mime_and_sanitized_filename():
    document = MagicMock()
    document.model_dump_json.return_value = "{}"
    test_suite = MagicMock(project_code="my proj", test_suite="suite/one")

    with patch("testgen.ui.views.test_definitions.export_definitions", return_value=document):
        file_name, mime, content = get_test_definitions_json_data(MagicMock(), test_suite)

    assert mime == "application/json"
    assert content == "{}"
    assert file_name.startswith("test_definitions_my_proj_suite_one_")
    assert file_name.endswith(".json")


# --- import preview ---


def test_preview_rejects_unparseable_file():
    result = _build_import_preview("data:application/json;base64,!!!not json!!!", _policy(), MagicMock())
    assert "error" in result
    assert "summary" not in result


def test_preview_rejects_json_that_is_not_an_export_document():
    result = _build_import_preview(_encode({"nope": True}), _policy(), MagicMock())
    assert "error" in result


def test_preview_surfaces_service_rejection_message():
    with patch(
        "testgen.ui.views.test_definitions.import_definitions",
        side_effect=InvalidImportPayload(MagicMock(), "Unsupported export document version 99"),
    ):
        result = _build_import_preview(_encode(_payload()), _policy(), MagicMock())

    assert result["error"] == "Unsupported export document version 99"


def test_preview_runs_in_preview_mode_and_never_applies():
    response = MagicMock(summary=_summary(created=1), items=[])
    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response) as import_defs,
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = []
        _build_import_preview(_encode(_payload()), _policy(on_absence=OnAbsence.delete_all), MagicMock())

    assert import_defs.call_args.args[1].mode == ImportMode.preview


def test_preview_resolves_file_rows_to_readable_labels():
    item = MagicMock(action=ImportAction.create, reason=ImportReason.no_match)
    item.tds = [MagicMock(idx=0, target_id=None)]
    response = MagicMock(summary=_summary(created=1), items=[item])

    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = [
            {"test_type": "Alpha_Trunc", "test_name_short": "Alpha Truncation"}
        ]
        result = _build_import_preview(_encode(_payload()), _policy(), MagicMock())

    row = result["preview_rows"][0]
    assert row["test_name"] == "Alpha Truncation"
    assert row["table_name"] == "orders"
    assert row["column_name"] == "email"
    assert row["action"] == "Create"


def test_preview_leads_with_the_rows_that_need_attention():
    """A skip is the row that silently will not import. Sorted among many routine updates
    it lands off the bottom of a scrolling table, so ordering is by actionability."""
    definitions = [
        {"test_type": "Alpha_Trunc", "table_name": "aaa", "column_name": "c"},
        {"test_type": "Alpha_Trunc", "table_name": "zzz", "column_name": "c"},
        {"test_type": "Alpha_Trunc", "table_name": "mmm", "column_name": "c"},
    ]
    update = MagicMock(action=ImportAction.update, reason=ImportReason.matched)
    update.tds = [MagicMock(idx=0, target_id=None)]
    skip = MagicMock(action=ImportAction.skip, reason=ImportReason.invalid_test_type)
    skip.tds = [MagicMock(idx=1, target_id=None)]
    delete = MagicMock(action=ImportAction.delete, reason=ImportReason.absent)
    delete.tds = [MagicMock(idx=2, target_id=None)]

    response = MagicMock(summary=_summary(updated=1, skipped=1, deleted=1), items=[update, skip, delete])

    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = []
        result = _build_import_preview(_encode(_payload(definitions=definitions)), _policy(), MagicMock())

    assert [row["action_code"] for row in result["preview_rows"]] == ["skip", "delete", "update"]


def test_preview_resolves_delete_rows_from_the_target_test():
    """A delete names an existing test, not a file entry: idx is None and only target_id
    identifies it. Built with real service types so a rename in the service breaks this."""
    target_id = uuid4()
    response = ImportResponse(
        summary=ImportSummary(deleted=1),
        items=[
            ImportItem(
                action=ImportAction.delete,
                reason=ImportReason.absent,
                tds=[ImportItemTD(idx=None, target_id=target_id)],
            )
        ],
    )
    existing = MagicMock(id=target_id, test_type="Alpha_Trunc", table_name="orders", column_name="email")

    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response),
        patch("testgen.ui.views.test_definitions.select_test_definitions_where", return_value=[existing]),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = [
            {"test_type": "Alpha_Trunc", "test_name_short": "Alpha Truncation"}
        ]
        result = _build_import_preview(_encode(_payload()), _policy(), MagicMock())

    assert result["summary"]["deleted"] == 1
    row = result["preview_rows"][0]
    assert row["action_code"] == "delete"
    assert (row["test_name"], row["table_name"], row["column_name"]) == ("Alpha Truncation", "orders", "email")


def test_delete_row_for_an_unknown_test_type_falls_back_to_its_code():
    """Symmetric with a file-sourced row, which also degrades to the raw code rather than
    rendering an unidentifiable blank row the user is asked to authorize."""
    target_id = uuid4()
    response = ImportResponse(
        summary=ImportSummary(deleted=1),
        items=[
            ImportItem(
                action=ImportAction.delete,
                reason=ImportReason.absent,
                tds=[ImportItemTD(idx=None, target_id=target_id)],
            )
        ],
    )
    existing = MagicMock(id=target_id, test_type="Retired_Type", table_name="orders", column_name="email")

    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response),
        patch("testgen.ui.views.test_definitions.select_test_definitions_where", return_value=[existing]),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = []
        result = _build_import_preview(_encode(_payload()), _policy(), MagicMock())

    assert result["preview_rows"][0]["test_name"] == "Retired_Type"


def test_preview_reports_a_readable_error_instead_of_raising():
    with patch(
        "testgen.ui.views.test_definitions.import_definitions", side_effect=RuntimeError("connection reset")
    ):
        result = _build_import_preview(_encode(_payload()), _policy(), MagicMock())

    assert "connection reset" not in result["error"]
    assert "summary" not in result


def test_preview_truncates_long_row_lists_but_reports_the_true_total():
    definitions = [
        {"test_type": "Alpha_Trunc", "table_name": f"t{i}", "column_name": "c"} for i in range(600)
    ]
    item = MagicMock(action=ImportAction.create, reason=ImportReason.no_match)
    item.tds = [MagicMock(idx=i, target_id=None) for i in range(600)]
    response = MagicMock(summary=_summary(created=600), items=[item])

    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = []
        result = _build_import_preview(_encode(_payload(definitions=definitions)), _policy(), MagicMock())

    assert result["truncated"] is True
    assert result["total_rows"] == 600
    assert len(result["preview_rows"]) == 500


# --- result message ---


def test_result_message_lists_only_nonzero_counts():
    assert _import_result_message(_summary(created=5, updated=2)) == "Test definitions imported: 5 created, 2 updated."


def test_result_message_when_nothing_changed():
    assert _import_result_message(_summary()) == "No test definitions were changed."


# --- apply-path guards ---
#
# These live at module level rather than in render's closure so they can be asserted here:
# the browser can be made to send anything, and the delete confirmation never leaves it.


# Preview identifiers. Named, not inline literals, so the "token" keyword does not read
# to ruff as a hardcoded credential.
RENDERED = "preview-a"
REPLACED = "preview-b"


def _preview(deleted=0, token=RENDERED):
    return {"summary": {"created": 1, "updated": 0, "deleted": deleted, "skipped": 0}, "token": token}


def _refusal(**overrides):
    kwargs = {
        "user_can_edit": True,
        "targets_this_suite": True,
        "content": "data:application/json;base64,e30=",
        "preview": _preview(),
        "submitted_token": RENDERED,
        "delete_confirmed": False,
    }
    return _refuse_import(**{**kwargs, **overrides})


def test_a_valid_import_is_not_refused():
    assert _refusal() is None


def test_import_refused_without_edit_permission():
    assert _refusal(user_can_edit=False) is not None


def test_import_refused_when_armed_for_another_test_suite():
    """The dialog state outlives navigation, so an import must land where it was built."""
    assert _refusal(targets_this_suite=False) is not None


@pytest.mark.parametrize("preview", [None, {"error": "Could not read this file."}])
def test_import_refused_without_a_usable_preview(preview):
    assert _refusal(preview=preview) is not None


def test_import_refused_without_content():
    assert _refusal(content=None) is not None


def test_deletions_refused_until_confirmed():
    """The confirmation toggle never leaves the browser, so the count that authorizes the
    delete is re-checked against the stored preview here."""
    assert _refusal(preview=_preview(deleted=209), delete_confirmed=False) is not None
    assert _refusal(preview=_preview(deleted=209), delete_confirmed=True) is None


def test_confirmation_is_not_demanded_when_nothing_would_be_deleted():
    assert _refusal(preview=_preview(deleted=0), delete_confirmed=False) is None


def test_import_refused_when_the_preview_on_screen_is_stale():
    """A policy change and a confirm click can land in the same rerun, the change applied
    first, so the stored preview is already the new one by the time the click is handled.
    The token is what the browser rendered, so an older one means the projection the user
    authorized is gone."""
    assert _refusal(preview=_preview(token=REPLACED), submitted_token=RENDERED) is not None
    assert _refusal(preview=_preview(token=REPLACED), submitted_token=REPLACED) is None


def test_import_refused_when_no_token_is_submitted():
    """A hand-made payload does not get to skip the check by omitting the field."""
    assert _refusal(submitted_token=None) is not None
    assert _refusal(submitted_token="") is not None


# --- apply ---


def test_apply_uses_the_stored_policy_in_apply_mode():
    response = MagicMock(summary=_summary(created=2))
    with patch("testgen.ui.views.test_definitions.import_definitions", return_value=response) as import_defs:
        result = _run_import(MagicMock(), _encode(_payload()), _policy(on_new=OnNew.create_and_lock))

    config = import_defs.call_args.args[1]
    assert config.mode == ImportMode.apply
    assert config.on_new == OnNew.create_and_lock
    assert result["success"] is True


def test_a_failed_apply_rolls_back_rather_than_reporting_success():
    """The session is opened inside the try. Catching outside it would take
    database_session's clean-exit path and commit a partially applied import."""
    with (
        patch("testgen.ui.views.test_definitions.database_session") as session_cm,
        patch("testgen.ui.views.test_definitions.import_definitions", side_effect=RuntimeError("deadlock")),
    ):
        result = _run_import(MagicMock(), _encode(_payload()), _policy())

    assert result["success"] is False
    assert "deadlock" not in result["message"]
    # The context manager saw the exception, which is what drives its rollback.
    assert session_cm.return_value.__exit__.call_args.args[0] is RuntimeError


def test_an_invalid_payload_surfaces_the_service_message():
    with patch(
        "testgen.ui.views.test_definitions.import_definitions",
        side_effect=InvalidImportPayload(MagicMock(), "Duplicate external_id at index 3"),
    ):
        result = _run_import(MagicMock(), _encode(_payload()), _policy())

    assert result["success"] is False
    assert result["message"] == "Duplicate external_id at index 3"
