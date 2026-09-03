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
    IMPORT_BEHAVIORS,
    _build_import_preview,
    _import_config,
    _import_result_message,
    get_test_definitions_json_data,
)

pytestmark = pytest.mark.unit


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


# --- behavior presets ---


def test_every_behavior_preset_builds_a_valid_config():
    for behavior in IMPORT_BEHAVIORS:
        config = _import_config(behavior, ImportMode.preview)
        assert config.mode == ImportMode.preview


def test_upsert_preset_does_not_delete():
    config = _import_config("upsert", ImportMode.apply)
    assert config.on_match == OnMatch.overwrite_unlocked
    assert config.on_new == OnNew.create
    assert config.on_absence == OnAbsence.do_nothing


def test_replace_preset_is_the_only_destructive_one():
    destructive = [
        name for name in IMPORT_BEHAVIORS if _import_config(name, ImportMode.apply).on_absence != OnAbsence.do_nothing
    ]
    assert destructive == ["replace"]
    assert _import_config("replace", ImportMode.apply).on_absence == OnAbsence.delete_all


def test_promote_preset_locks_created_definitions():
    assert _import_config("promote", ImportMode.apply).on_new == OnNew.create_and_lock


def test_unknown_behavior_falls_back_to_upsert():
    assert _import_config("nonsense", ImportMode.apply) == _import_config("upsert", ImportMode.apply)


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
    result = _build_import_preview("data:application/json;base64,!!!not json!!!", "upsert", MagicMock())
    assert "error" in result
    assert "summary" not in result


def test_preview_rejects_json_that_is_not_an_export_document():
    result = _build_import_preview(_encode({"nope": True}), "upsert", MagicMock())
    assert "error" in result


def test_preview_surfaces_service_rejection_message():
    with patch(
        "testgen.ui.views.test_definitions.import_definitions",
        side_effect=InvalidImportPayload(MagicMock(), "Unsupported export document version 99"),
    ):
        result = _build_import_preview(_encode(_payload()), "upsert", MagicMock())

    assert result["error"] == "Unsupported export document version 99"


def test_preview_runs_in_preview_mode_and_never_applies():
    response = MagicMock(summary=_summary(created=1), items=[])
    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response) as import_defs,
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = []
        _build_import_preview(_encode(_payload()), "replace", MagicMock())

    assert import_defs.call_args.args[1].mode == ImportMode.preview


def test_preview_resolves_file_rows_to_readable_labels():
    item = MagicMock(action=MagicMock(value="create"), reason=MagicMock(value="no_match"))
    item.tds = [MagicMock(idx=0, target_id=None)]
    response = MagicMock(summary=_summary(created=1), items=[item])

    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = [
            {"test_type": "Alpha_Trunc", "test_name_short": "Alpha Truncation"}
        ]
        result = _build_import_preview(_encode(_payload()), "upsert", MagicMock())

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
    update = MagicMock(action=MagicMock(value="update"), reason=MagicMock(value="matched"))
    update.tds = [MagicMock(idx=0, target_id=None)]
    skip = MagicMock(action=MagicMock(value="skip"), reason=MagicMock(value="invalid_test_type"))
    skip.tds = [MagicMock(idx=1, target_id=None)]
    delete = MagicMock(action=MagicMock(value="delete"), reason=MagicMock(value="absent"))
    delete.tds = [MagicMock(idx=2, target_id=None)]

    response = MagicMock(summary=_summary(updated=1, skipped=1, deleted=1), items=[update, skip, delete])

    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = []
        result = _build_import_preview(_encode(_payload(definitions=definitions)), "upsert", MagicMock())

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
        result = _build_import_preview(_encode(_payload()), "upsert", MagicMock())

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
        result = _build_import_preview(_encode(_payload()), "upsert", MagicMock())

    assert result["preview_rows"][0]["test_name"] == "Retired_Type"


def test_preview_reports_a_readable_error_instead_of_raising():
    with patch(
        "testgen.ui.views.test_definitions.import_definitions", side_effect=RuntimeError("connection reset")
    ):
        result = _build_import_preview(_encode(_payload()), "upsert", MagicMock())

    assert "connection reset" not in result["error"]
    assert "summary" not in result


def test_preview_truncates_long_row_lists_but_reports_the_true_total():
    definitions = [
        {"test_type": "Alpha_Trunc", "table_name": f"t{i}", "column_name": "c"} for i in range(600)
    ]
    item = MagicMock(action=MagicMock(value="create"), reason=MagicMock(value="no_match"))
    item.tds = [MagicMock(idx=i, target_id=None) for i in range(600)]
    response = MagicMock(summary=_summary(created=600), items=[item])

    with (
        patch("testgen.ui.views.test_definitions.import_definitions", return_value=response),
        patch("testgen.ui.views.test_definitions.run_test_type_lookup_query") as lookup,
    ):
        lookup.return_value.to_dict.return_value = []
        result = _build_import_preview(_encode(_payload(definitions=definitions)), "upsert", MagicMock())

    assert result["truncated"] is True
    assert result["total_rows"] == 600
    assert len(result["preview_rows"]) == 500


# --- result message ---


def test_result_message_lists_only_nonzero_counts():
    assert _import_result_message(_summary(created=5, updated=2)) == "Test definitions imported: 5 created, 2 updated."


def test_result_message_when_nothing_changed():
    assert _import_result_message(_summary()) == "No test definitions were changed."
