from collections import namedtuple
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.expression import Delete, Update

from testgen.common import test_definition_export_import_service as service
from testgen.common.enums import SuiteType
from testgen.common.models.suite_version import VersionState
from testgen.common.models.test_definition import TestDefinition
from testgen.common.test_definition_export_import_service import (
    ImportAction,
    ImportReason,
    _apply_actions,
    _build_response,
    _PlannedAction,
)
from tests.unit.sql_assertions import scopes_to_a_version

pytestmark = pytest.mark.unit

ExistingRow = namedtuple("ExistingRow", "id test_type lock_refresh")


def _planned(action, target_id=None):
    target = ExistingRow(target_id, "Row_Ct", False) if target_id else None
    td_import = MagicMock() if action in (ImportAction.create, ImportAction.update) else None
    return _PlannedAction(action, ImportReason.matched, 0, td_import, target)


def _apply(actions, *, writable):
    session = MagicMock()
    with (
        patch.object(service, "get_current_session", return_value=session),
        patch.object(service, "table_group_qualifies_table_refs", return_value=False),
        patch.object(service, "_create_td", side_effect=lambda *a: MagicMock(version_id=a[5])) as create,
        patch.object(service, "_update_td") as update,
        patch.object(TestDefinition, "assign_missing_term_ids"),
        patch.object(TestDefinition, "resolve_writable", return_value=writable) as route,
    ):
        _apply_actions(actions, MagicMock(id=uuid4()), MagicMock(), MagicMock())
    return session, create, update, route


def _compiled(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_updates_and_deletes_land_on_the_drafts_copies():
    draft, updated, deleted = uuid4(), uuid4(), uuid4()
    updated_copy, deleted_copy = uuid4(), uuid4()
    actions = [_planned(ImportAction.update, updated), _planned(ImportAction.delete, deleted)]
    session, _, update, route = _apply(actions, writable=(draft, {updated: updated_copy, deleted: deleted_copy}))

    assert sorted(route.call_args.args[1]) == sorted([updated, deleted])
    assert update.call_args.args[1].id == updated_copy
    delete_sql = _compiled(session.execute.call_args.args[0])
    assert str(deleted_copy) in delete_sql
    assert str(deleted) not in delete_sql


def test_the_response_reports_the_drafts_ids():
    draft, updated, deleted = uuid4(), uuid4(), uuid4()
    updated_copy, deleted_copy = uuid4(), uuid4()
    actions = [_planned(ImportAction.update, updated), _planned(ImportAction.delete, deleted)]
    _apply(actions, writable=(draft, {updated: updated_copy, deleted: deleted_copy}))

    reported = {td.target_id for item in _build_response(actions, None).items for td in item.tds}
    assert reported == {updated_copy, deleted_copy}


def test_creates_land_on_the_writable_version():
    draft = uuid4()
    _, create, _, _ = _apply([_planned(ImportAction.create)], writable=(draft, {}))
    assert create.call_args.args[5] == draft


def test_a_plan_with_nothing_to_apply_opens_no_draft():
    _, _, _, route = _apply([_planned(ImportAction.skip)], writable=(uuid4(), {}))
    route.assert_not_called()


def _export(*, frozen, version_id=None):
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    table_group = MagicMock(table_groups_name="tg", table_group_schema="public")
    suite = MagicMock(id=uuid4(), project_code="demo", test_suite="orders")
    with (
        patch.object(service, "get_current_session", return_value=session),
        patch.object(service.TableGroup, "get", return_value=table_group),
        patch.object(service.SuiteVersion, "is_frozen_agreement", return_value=frozen) as frozen_check,
    ):
        service.export_definitions(suite, service.Origin.manual, None, None, version_id=version_id)
    return session, frozen_check


def _stamps(session) -> list:
    return [c.args[0] for c in session.execute.call_args_list if isinstance(c.args[0], Update)]


def test_export_does_not_stamp_a_frozen_version():
    version_id = uuid4()
    session, frozen_check = _export(frozen=True, version_id=version_id)
    assert _stamps(session) == []
    frozen_check.assert_called_once_with(version_id)


def test_export_stamps_a_writable_version():
    session, _ = _export(frozen=False)
    assert len(_stamps(session)) == 1


def test_export_without_a_version_checks_the_one_the_suite_resolves_to():
    session, frozen_check = _export(frozen=False)
    resolution = _compiled(session.scalar.call_args.args[0])
    assert "suite_versions" in resolution
    assert frozen_check.call_args.args[0] is session.scalar.return_value


def test_the_import_delete_still_scopes_to_a_version():
    deleted = uuid4()
    session, _, _, _ = _apply([_planned(ImportAction.delete, deleted)], writable=(uuid4(), {deleted: deleted}))
    deletes = [c.args[0] for c in session.execute.call_args_list if isinstance(c.args[0], Delete)]
    assert len(deletes) == 1
    assert scopes_to_a_version(deletes[0])


def test_a_target_that_no_longer_exists_is_refused_by_name():
    vanished = uuid4()
    with pytest.raises(service.ImportTargetMissing, match=f"{vanished} no longer exists") as refused:
        _apply([_planned(ImportAction.update, vanished)], writable=(uuid4(), {}))
    assert refused.value.row_id == vanished


def _export_document(suite_type: SuiteType):
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    suite = MagicMock(id=uuid4(), project_code="demo", test_suite="orders", suite_type=suite_type)
    with (
        patch.object(service, "get_current_session", return_value=session),
        patch.object(service.TableGroup, "get", return_value=MagicMock(table_groups_name="tg", table_group_schema="s")),
        patch.object(service.SuiteVersion, "is_frozen_agreement", return_value=True),
        patch.object(service.SuiteVersion, "get", return_value=MagicMock(version=3)) as get_version,
    ):
        document = service.export_definitions(suite, service.Origin.both, None, None, version_id=uuid4())
    return document, get_version


def test_a_contract_export_names_the_version_it_holds():
    document, _ = _export_document(SuiteType.CONTRACT)
    assert document.source.contract_version == 3


def test_a_regular_export_names_no_version():
    document, get_version = _export_document(SuiteType.REGULAR)
    assert document.source.contract_version is None
    get_version.assert_not_called()


@pytest.mark.parametrize("preview", [True, False])
def test_a_contract_import_reports_where_it_lands(preview):
    suite = MagicMock(suite_type=SuiteType.CONTRACT)
    with patch.object(
        service.contract_service, "import_destination", return_value=(4, VersionState.DRAFT)
    ) as destination:
        version = service._contract_version(suite, preview=preview)
    destination.assert_called_once_with(suite, preview=preview)
    assert version == service.ContractVersion(number=4, state=VersionState.DRAFT)


def test_a_regular_import_reports_no_version():
    with patch.object(service.contract_service, "import_destination") as destination:
        assert service._contract_version(MagicMock(suite_type=SuiteType.REGULAR), preview=True) is None
    destination.assert_not_called()
