"""Tests for test definition export/import — service and endpoint logic."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from testgen.api.schemas import (
    ExportDocument,
    ImportAction,
    ImportConfig,
    ImportMode,
    ImportPayload,
    ImportReason,
    ImportResponse,
    OnAbsence,
    OnMatch,
    OnNew,
    Origin,
    TestDefinitionExport,
)

pytestmark = pytest.mark.unit

SERVICE_MODULE = "testgen.api.test_definition_service"
ENDPOINT_MODULE = "testgen.api.test_definitions"


# --- Fixtures ---


def _make_test_suite(**overrides):
    defaults = {
        "id": uuid4(),
        "table_groups_id": uuid4(),
        "project_code": "proj",
        "test_suite": "suite_1",
        "is_monitor": False,
    }
    defaults.update(overrides)
    ts = MagicMock()
    for k, v in defaults.items():
        setattr(ts, k, v)
    return ts


def _make_table_group(**overrides):
    defaults = {
        "id": uuid4(),
        "table_groups_name": "tg_1",
        "table_group_schema": "public",
    }
    defaults.update(overrides)
    tg = MagicMock()
    for k, v in defaults.items():
        setattr(tg, k, v)
    return tg


_DEFAULT_AUTO_GEN_DATE = datetime(2024, 6, 1, tzinfo=UTC)


def _make_existing_row(
    *,
    test_type="Alpha",
    table_name="t1",
    column_name="c1",
    last_auto_gen_date=_DEFAULT_AUTO_GEN_DATE,
    external_id=None,
    lock_refresh=False,
    id_=None,
):
    row = MagicMock()
    row.id = id_ or uuid4()
    row.test_type = test_type
    row.table_name = table_name
    row.column_name = column_name
    row.last_auto_gen_date = last_auto_gen_date
    row.external_id = external_id
    row.lock_refresh = lock_refresh
    return row


def _make_import_td(
    *,
    test_type="Alpha",
    table_name="t1",
    column_name="c1",
    last_auto_gen_date=datetime(2024, 1, 1, tzinfo=UTC),
    external_id=None,
    lock_refresh=False,
    **extra,
) -> TestDefinitionExport:
    data = {
        "test_type": test_type,
        "table_name": table_name,
        "column_name": column_name,
        "lock_refresh": lock_refresh,
    }
    if last_auto_gen_date is not None:
        data["last_auto_gen_date"] = last_auto_gen_date
    if external_id is not None:
        data["external_id"] = external_id
    data.update(extra)
    return TestDefinitionExport(**data)


def _make_config(
    mode=ImportMode.preview,
    on_match=OnMatch.overwrite_unlocked,
    on_new=OnNew.create,
    on_absence=OnAbsence.do_nothing,
) -> ImportConfig:
    return ImportConfig(mode=mode, on_match=on_match, on_new=on_new, on_absence=on_absence)


def _make_payload(*tds: TestDefinitionExport) -> ImportPayload:
    return ImportPayload(definitions=list(tds))


def _count(response: ImportResponse, action: ImportAction) -> int:
    return sum(len(item.tds) for item in response.items if item.action == action)


def _reasons(response: ImportResponse, action: ImportAction) -> set[ImportReason]:
    return {item.reason for item in response.items if item.action == action}


# --- Export tests ---


class Test_export_definitions:

    @patch(f"{SERVICE_MODULE}.settings")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_export_builds_document(self, mock_session_fn, mock_tg_cls, mock_settings):
        mock_settings.VERSION = "5.12.0"
        session = MagicMock()
        mock_session_fn.return_value = session

        tg = _make_table_group()
        mock_tg_cls.get.return_value = tg

        ts = _make_test_suite(table_groups_id=tg.id)

        td_obj = MagicMock(spec=[])
        # Set all fields to None first, then override specific ones
        for field in TestDefinitionExport.model_fields:
            setattr(td_obj, field, None)
        td_obj.test_type = "Alpha"
        td_obj.table_name = "t1"
        td_obj.column_name = "c1"
        td_obj.last_auto_gen_date = datetime(2024, 1, 1, tzinfo=UTC)
        td_obj.test_active = True
        td_obj.lock_refresh = False
        td_obj.skip_errors = 0
        td_obj.window_days = 0
        td_obj.history_lookback = 0

        session.scalars.return_value.all.return_value = [td_obj]

        from testgen.api.test_definition_service import export_definitions

        result = export_definitions(ts, Origin.both, None, None)

        assert isinstance(result, ExportDocument)
        assert result.source.project_code == "proj"
        assert result.source.test_suite == "suite_1"
        assert result.source.table_group == tg.table_groups_name
        assert result.source.testgen_version == "5.12.0"
        assert len(result.definitions) == 1
        assert result.definitions[0].test_type == "Alpha"

    @patch(f"{SERVICE_MODULE}.settings")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_export_assigns_external_id_to_manual_tds(self, mock_session_fn, mock_tg_cls, mock_settings):
        mock_settings.VERSION = "5.12.0"
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()

        ts = _make_test_suite()
        session.scalars.return_value.all.return_value = []

        from testgen.api.test_definition_service import export_definitions

        export_definitions(ts, Origin.manual, None, None)

        # Should have issued an UPDATE to assign external_ids
        session.execute.assert_called_once()
        update_stmt = session.execute.call_args[0][0]
        assert "external_id" in str(update_stmt)

    @patch(f"{SERVICE_MODULE}.settings")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_export_skips_external_id_assignment_for_auto_only(self, mock_session_fn, mock_tg_cls, mock_settings):
        mock_settings.VERSION = "5.12.0"
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()

        ts = _make_test_suite()
        session.scalars.return_value.all.return_value = []

        from testgen.api.test_definition_service import export_definitions

        export_definitions(ts, Origin.auto, None, None)

        # No UPDATE for external_id assignment
        session.execute.assert_not_called()


# --- Import: matching and action resolution ---


class Test_import_matching:

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_auto_td_matches_by_natural_key(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        target_id = uuid4()
        existing = _make_existing_row(test_type="Alpha", table_name="t1", column_name="c1", id_=target_id)
        session.execute.return_value.all.return_value = [existing]

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1", column_name="c1")
        config = _make_config(on_match=OnMatch.overwrite_unlocked)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.updated == 1
        assert result.items[0].tds[0].target_id == target_id

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_manual_td_matches_by_external_id(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        ext_id = uuid4()
        target_id = uuid4()
        existing = _make_existing_row(
            last_auto_gen_date=None, external_id=ext_id, id_=target_id,
        )
        session.execute.return_value.all.return_value = [existing]

        ts = _make_test_suite()
        td = _make_import_td(last_auto_gen_date=None, external_id=ext_id, table_name="t1")
        config = _make_config(on_match=OnMatch.overwrite_unlocked)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.updated == 1
        assert result.items[0].tds[0].target_id == target_id

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_no_match_creates(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1")
        config = _make_config(on_new=OnNew.create)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.created == 1
        assert ImportReason.no_match in _reasons(result, ImportAction.create)


# --- Import: policy resolution ---


class Test_import_policies:

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_on_match_skip(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        existing = _make_existing_row()
        session.execute.return_value.all.return_value = [existing]

        ts = _make_test_suite()
        td = _make_import_td()
        config = _make_config(on_match=OnMatch.skip)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.skipped == 1
        assert ImportReason.policy in _reasons(result, ImportAction.skip)

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_on_match_overwrite_unlocked_skips_locked(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        existing = _make_existing_row(lock_refresh=True)
        session.execute.return_value.all.return_value = [existing]

        ts = _make_test_suite()
        td = _make_import_td()
        config = _make_config(on_match=OnMatch.overwrite_unlocked)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.skipped == 1
        assert ImportReason.locked in _reasons(result, ImportAction.skip)

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_on_match_overwrite_all_ignores_lock(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        existing = _make_existing_row(lock_refresh=True)
        session.execute.return_value.all.return_value = [existing]

        ts = _make_test_suite()
        td = _make_import_td()
        config = _make_config(on_match=OnMatch.overwrite_all)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.updated == 1

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_on_new_skip(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td()
        config = _make_config(on_new=OnNew.skip)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.skipped == 1
        assert ImportReason.no_match in _reasons(result, ImportAction.skip)

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_on_absence_delete_all(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        # Existing auto-gen TD not in the import file
        orphan = _make_existing_row(test_type="Beta", table_name="t2", column_name="c2")
        session.execute.return_value.all.return_value = [orphan]

        ts = _make_test_suite()
        # Import a different TD — orphan has no match
        td = _make_import_td(test_type="Alpha", table_name="t1", column_name="c1")
        config = _make_config(on_new=OnNew.create, on_absence=OnAbsence.delete_all)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.deleted == 1
        assert result.summary.created == 1

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_on_absence_delete_unlocked_spares_locked(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        locked_orphan = _make_existing_row(test_type="Beta", table_name="t2", column_name="c2", lock_refresh=True)
        session.execute.return_value.all.return_value = [locked_orphan]

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1")
        config = _make_config(on_new=OnNew.create, on_absence=OnAbsence.delete_unlocked)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        # Locked orphan is omitted entirely — not deleted, not reported
        assert result.summary.deleted == 0
        assert result.summary.created == 1


# --- Import: validation / skip reasons ---


class Test_import_validation:

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_invalid_test_type_skipped(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="NonExistent", table_name="t1")
        config = _make_config()

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.skipped == 1
        assert ImportReason.invalid_test_type in _reasons(result, ImportAction.skip)

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_invalid_table_skipped(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["other_table"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1")
        config = _make_config()

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.skipped == 1
        assert ImportReason.invalid_table in _reasons(result, ImportAction.skip)

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_manual_td_without_external_id_skipped(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        # Manual TD (no last_auto_gen_date) with no external_id
        td = _make_import_td(last_auto_gen_date=None, external_id=None, table_name="t1")
        config = _make_config()

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.skipped == 1
        assert ImportReason.missing_external_id in _reasons(result, ImportAction.skip)

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_td_with_null_table_name_passes_validation(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        """TDs with null table_name (e.g. custom queries) should not fail table validation."""
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = []
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name=None)
        config = _make_config()

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.created == 1

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_duplicate_auto_keys_rejected(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td1 = _make_import_td(test_type="Alpha", table_name="t1", column_name="c1")
        td2 = _make_import_td(test_type="Alpha", table_name="t1", column_name="c1")
        config = _make_config()

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            with pytest.raises(HTTPException) as exc_info:
                import_definitions(ts, config, _make_payload(td1, td2))
            assert exc_info.value.status_code == 400
            assert "duplicate_natural_key" in str(exc_info.value.detail)

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_duplicate_external_ids_rejected(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        ext_id = uuid4()
        td1 = _make_import_td(last_auto_gen_date=None, external_id=ext_id, table_name="t1")
        td2 = _make_import_td(last_auto_gen_date=None, external_id=ext_id, table_name="t1")
        config = _make_config()

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            with pytest.raises(HTTPException) as exc_info:
                import_definitions(ts, config, _make_payload(td1, td2))
            assert exc_info.value.status_code == 400


# --- Import: apply_strict mode ---


class Test_import_strict_mode:

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_apply_strict_does_not_apply_when_skips_exist(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        good_td = _make_import_td(test_type="Alpha", table_name="t1")
        bad_td = _make_import_td(test_type="NonExistent", table_name="t1")
        config = _make_config(mode=ImportMode.apply_strict)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(good_td, bad_td))

        # Result reports what would happen, but nothing was applied
        assert result.summary.created == 1
        assert result.summary.skipped == 1
        # No session.add calls (create not applied)
        session.add.assert_not_called()

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_apply_strict_applies_when_no_skips(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1")
        config = _make_config(mode=ImportMode.apply_strict)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            with patch(f"{SERVICE_MODULE}.TestDefinition") as mock_td_cls:
                mock_td_cls.return_value = MagicMock(id=uuid4())
                result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.created == 1
        # session.add was called — the create was applied
        session.add.assert_called_once()


# --- Import: apply — create behavior ---


class Test_import_create:

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_create_auto_td_sets_last_auto_gen_date_to_now(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1", last_auto_gen_date=datetime(2024, 1, 1, tzinfo=UTC))
        config = _make_config(mode=ImportMode.apply, on_new=OnNew.create)

        from testgen.api.test_definition_service import import_definitions

        before = datetime.now(UTC)
        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            with patch(f"{SERVICE_MODULE}.TestDefinition") as mock_td_cls:
                created_td = MagicMock(id=uuid4())
                mock_td_cls.return_value = created_td
                import_definitions(ts, config, _make_payload(td))

        # last_auto_gen_date should be set to approximately now, not the source date
        assert created_td.last_auto_gen_date >= before

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_create_manual_td_sets_null_last_auto_gen_date(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        ext_id = uuid4()
        td = _make_import_td(last_auto_gen_date=None, external_id=ext_id, table_name="t1")
        config = _make_config(mode=ImportMode.apply, on_new=OnNew.create)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            with patch(f"{SERVICE_MODULE}.TestDefinition") as mock_td_cls:
                created_td = MagicMock(id=uuid4())
                mock_td_cls.return_value = created_td
                import_definitions(ts, config, _make_payload(td))

        assert created_td.last_auto_gen_date is None

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_create_and_lock_forces_lock_for_auto_td(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1", lock_refresh=False)
        config = _make_config(mode=ImportMode.apply, on_new=OnNew.create_and_lock)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            with patch(f"{SERVICE_MODULE}.TestDefinition") as mock_td_cls:
                created_td = MagicMock(id=uuid4())
                mock_td_cls.return_value = created_td
                import_definitions(ts, config, _make_payload(td))

        assert created_td.lock_refresh is True

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_create_sets_last_manual_update(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1")
        config = _make_config(mode=ImportMode.apply, on_new=OnNew.create)

        from testgen.api.test_definition_service import import_definitions

        before = datetime.now(UTC)
        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            with patch(f"{SERVICE_MODULE}.TestDefinition") as mock_td_cls:
                created_td = MagicMock(id=uuid4())
                mock_td_cls.return_value = created_td
                import_definitions(ts, config, _make_payload(td))

        assert created_td.last_manual_update >= before


# --- Import: apply — update behavior ---


class Test_import_update:

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_update_excludes_identity_fields(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        target_id = uuid4()
        existing = _make_existing_row(id_=target_id, lock_refresh=False)
        session.execute.return_value.all.return_value = [existing]

        ts = _make_test_suite()
        td = _make_import_td(
            test_type="Alpha", table_name="t1", column_name="c1",
            threshold_value="99",
        )
        config = _make_config(mode=ImportMode.apply, on_match=OnMatch.overwrite_unlocked)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            import_definitions(ts, config, _make_payload(td))

        # Find the update() call (second execute call — first is the select for existing rows)
        update_call = session.execute.call_args_list[-1]
        update_stmt = update_call[0][0]
        compiled = str(update_stmt.compile(compile_kwargs={"literal_binds": True}))
        # Identity fields should not be in the SET clause
        assert "test_type" not in compiled.split("SET")[1] if "SET" in compiled else True

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_update_inherits_external_id_if_target_has_none(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        # Auto-gen target with no external_id
        target_id = uuid4()
        existing = _make_existing_row(id_=target_id, external_id=None, lock_refresh=False)
        session.execute.return_value.all.return_value = [existing]

        ts = _make_test_suite()
        source_ext_id = uuid4()
        # Auto-gen TD in file, also has an external_id
        td = _make_import_td(
            test_type="Alpha", table_name="t1", column_name="c1",
            external_id=source_ext_id,
        )
        config = _make_config(mode=ImportMode.apply, on_match=OnMatch.overwrite_unlocked)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            import_definitions(ts, config, _make_payload(td))

        # The update should include external_id
        update_call = session.execute.call_args_list[-1]
        update_stmt = update_call[0][0]
        compiled = str(update_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "external_id" in compiled


# --- Import: matched TDs protected from absence delete ---


class Test_import_absence_with_validation_skips:

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_invalid_td_still_protects_match_from_absence_delete(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        """A TD that matches but fails validation should still protect the target from on_absence delete."""
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]

        target_id = uuid4()
        existing = _make_existing_row(
            test_type="InvalidType", table_name="t1", column_name="c1", id_=target_id,
        )
        session.execute.return_value.all.return_value = [existing]

        ts = _make_test_suite()
        # This TD matches the existing row by natural key, but has an invalid test_type
        td = _make_import_td(test_type="InvalidType", table_name="t1", column_name="c1")
        config = _make_config(on_absence=OnAbsence.delete_all)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        # TD is skipped for invalid test type, but the matched target is NOT deleted
        assert result.summary.skipped == 1
        assert result.summary.deleted == 0


# --- Import: preview mode ---


class Test_import_preview:

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_preview_does_not_apply(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1")
        config = _make_config(mode=ImportMode.preview)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        assert result.summary.created == 1
        # No session.add — preview only
        session.add.assert_not_called()

    @patch(f"{SERVICE_MODULE}.DataTable")
    @patch(f"{SERVICE_MODULE}.TableGroup")
    @patch(f"{SERVICE_MODULE}.get_current_session")
    def test_preview_target_id_is_none_for_creates(self, mock_session_fn, mock_tg_cls, mock_dt_cls):
        session = MagicMock()
        mock_session_fn.return_value = session
        mock_tg_cls.get.return_value = _make_table_group()
        mock_dt_cls.select_table_names.return_value = ["t1"]
        session.execute.return_value.all.return_value = []

        ts = _make_test_suite()
        td = _make_import_td(test_type="Alpha", table_name="t1")
        config = _make_config(mode=ImportMode.preview)

        from testgen.api.test_definition_service import import_definitions

        with patch(f"{SERVICE_MODULE}._load_valid_test_types", return_value={"Alpha"}):
            result = import_definitions(ts, config, _make_payload(td))

        create_items = [item for item in result.items if item.action == ImportAction.create]
        assert create_items[0].tds[0].target_id is None


# --- Endpoint: strict mode raises 400 ---


class Test_import_endpoint_strict:

    def test_strict_raises_400_on_skips(self):
        from testgen.api.schemas import ImportRequest
        from testgen.api.test_definitions import import_test_definitions

        ts = _make_test_suite()
        config = _make_config(mode=ImportMode.apply_strict)
        payload = _make_payload(_make_import_td(test_type="Alpha", table_name="t1"))
        request = ImportRequest(config=config, payload=payload)

        # Mock the service to return a response with skips
        mock_result = ImportResponse(
            summary=ImportSummary(created=1, skipped=1),
            items=[],
        )

        with patch(f"{ENDPOINT_MODULE}.test_definition_service") as mock_service:
            mock_service.import_definitions.return_value = mock_result
            with pytest.raises(HTTPException) as exc_info:
                import_test_definitions(body=request, test_suite=ts)

        assert exc_info.value.status_code == 400
        assert "strict_validation_failed" in str(exc_info.value.detail)
        assert "import_result" in exc_info.value.detail

    def test_strict_returns_200_when_no_skips(self):
        from testgen.api.schemas import ImportRequest
        from testgen.api.test_definitions import import_test_definitions

        ts = _make_test_suite()
        config = _make_config(mode=ImportMode.apply_strict)
        payload = _make_payload(_make_import_td(test_type="Alpha", table_name="t1"))
        request = ImportRequest(config=config, payload=payload)

        mock_result = ImportResponse(
            summary=ImportSummary(created=1),
            items=[],
        )

        with patch(f"{ENDPOINT_MODULE}.test_definition_service") as mock_service:
            mock_service.import_definitions.return_value = mock_result
            result = import_test_definitions(body=request, test_suite=ts)

        assert result.summary.created == 1


# --- Schema: TestDefinitionExport ---


class Test_schema:

    def test_coerce_none_to_zero(self):
        td = TestDefinitionExport(test_type="Alpha", skip_errors=None, window_days=None, history_lookback=None)
        assert td.skip_errors == 0
        assert td.window_days == 0
        assert td.history_lookback == 0

    def test_model_fields_set_tracks_explicit_fields(self):
        td = TestDefinitionExport(test_type="Alpha", table_name="t1", threshold_value="99")
        assert "test_type" in td.model_fields_set
        assert "table_name" in td.model_fields_set
        assert "threshold_value" in td.model_fields_set
        # Fields not provided should not be in model_fields_set
        assert "baseline_ct" not in td.model_fields_set
        assert "test_active" not in td.model_fields_set

    def test_defaults_match_expected_values(self):
        """Defaults must match ORM column defaults — this is the compact export contract."""
        td = TestDefinitionExport(test_type="Alpha")
        assert td.test_active is True
        assert td.lock_refresh is False
        assert td.skip_errors == 0
        assert td.window_days == 0
        assert td.history_lookback == 0


# Need to import this here for the endpoint test
from testgen.api.schemas import ImportSummary
