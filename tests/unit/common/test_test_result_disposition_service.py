from collections import namedtuple
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.expression import Update

from testgen.common.enums import Disposition
from testgen.common.models.test_definition import TestDefinition
from testgen.common.test_result_disposition_service import (
    DispositionUpdate,
    coerce_ui_disposition,
    coupled_test_definition_state,
    set_test_results_disposition,
)
from tests.unit.sql_assertions import scopes_to_a_version

pytestmark = pytest.mark.unit

MODULE = "testgen.common.test_result_disposition_service"

AffectedRow = namedtuple(
    "AffectedRow", "test_suite_id test_definition_id test_active lock_refresh", defaults=(True, False)
)


def _session(affected, rowcount=1, passed=0):
    session = MagicMock()
    session.scalar.return_value = passed
    session.execute.side_effect = lambda statement: (
        MagicMock(rowcount=rowcount) if isinstance(statement, Update) else MagicMock(all=lambda: affected)
    )
    return session


def _td_updates(session):
    return [
        call.args[0]
        for call in session.execute.call_args_list
        if isinstance(call.args[0], Update) and call.args[0].table.name == "test_definitions"
    ]


def _compiled(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class Test_coupled_test_definition_state:
    def test_muted_deactivates_and_locks(self):
        # (test_active, lock_refresh)
        assert coupled_test_definition_state(Disposition.INACTIVE) == (False, True)

    @pytest.mark.parametrize("disposition", [Disposition.CONFIRMED, Disposition.DISMISSED, None])
    def test_other_values_reactivate_and_unlock(self, disposition):
        assert coupled_test_definition_state(disposition) == (True, False)


class Test_coerce_ui_disposition:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("Confirmed", Disposition.CONFIRMED),
            ("Dismissed", Disposition.DISMISSED),
            ("Inactive", Disposition.INACTIVE),
            ("No Decision", None),
            (None, None),
            ("", None),
        ],
    )
    def test_maps_ui_string_to_stored_value(self, value, expected):
        assert coerce_ui_disposition(value) is expected


class Test_set_test_results_disposition:
    @pytest.fixture(autouse=True)
    def _writes_land_on_a_writable_version(self):
        with patch(f"{MODULE}.SuiteVersion.is_frozen_agreement", return_value=False) as frozen:
            self.frozen = frozen
            yield

    def test_empty_ids_is_noop(self):
        with patch(f"{MODULE}.get_current_session") as get_session:
            result = set_test_results_disposition([], Disposition.CONFIRMED)
        assert result == DispositionUpdate(matched=0, passed_skipped=0)
        get_session.assert_not_called()

    def test_returns_matched_and_passed_counts(self):
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, td)], rowcount=3, passed=2)
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: td})),
        ):
            result = set_test_results_disposition([uuid4(), uuid4()], Disposition.DISMISSED)
        assert result == DispositionUpdate(matched=3, passed_skipped=2)
        assert len(_td_updates(session)) == 1

    def test_muted_couples_td_to_inactive(self):
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, td)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: td})),
        ):
            set_test_results_disposition([uuid4()], Disposition.INACTIVE)
        params = _td_updates(session)[0].compile().params
        # YNString stores 'N'/'Y'; bound values are the Python bools before type processing.
        assert params["test_active"] is False
        assert params["lock_refresh"] is True

    def test_clear_passes_null_disposition(self):
        session = _session([])
        with patch(f"{MODULE}.get_current_session", return_value=session):
            set_test_results_disposition([uuid4()], None)
        tr_stmt = session.execute.call_args_list[0].args[0]
        assert tr_stmt.compile().params["disposition"] is None

    def test_regular_suite_couples_its_own_definitions(self):
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, td)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: td})) as route,
        ):
            set_test_results_disposition([uuid4()], Disposition.INACTIVE)
        assert route.call_args == ((suite, [td]), {"skip_unwritable": True})
        (td_update,) = _td_updates(session)
        assert str(td) in _compiled(td_update)
        assert scopes_to_a_version(td_update)

    def test_muting_an_active_version_result_writes_the_drafts_copy(self):
        suite, active, draft_copy = uuid4(), uuid4(), uuid4()
        session = _session([AffectedRow(suite, active)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {active: draft_copy})),
        ):
            result = set_test_results_disposition([uuid4()], Disposition.INACTIVE)
        assert result.matched == 1
        (td_update,) = _td_updates(session)
        sql = _compiled(td_update)
        assert str(draft_copy) in sql
        assert str(active) not in sql
        assert scopes_to_a_version(td_update)

    def test_definitions_are_routed_once_per_suite_leaving_out_the_unwritable(self):
        suite, blocked, active, draft_copy = uuid4(), uuid4(), uuid4(), uuid4()
        session = _session([AffectedRow(suite, blocked), AffectedRow(suite, active)], rowcount=2)
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {active: draft_copy})) as route,
        ):
            result = set_test_results_disposition([uuid4(), uuid4()], Disposition.DISMISSED)

        assert result.matched == 2
        route.assert_called_once_with(suite, [blocked, active], skip_unwritable=True)
        (td_update,) = _td_updates(session)
        sql = _compiled(td_update)
        assert str(draft_copy) in sql
        assert str(blocked) not in sql
        assert str(active) not in sql

    def test_a_result_without_a_definition_keeps_its_disposition(self):
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, None), AffectedRow(suite, td)], rowcount=2)
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: td})) as route,
        ):
            result = set_test_results_disposition([uuid4(), uuid4()], Disposition.INACTIVE)
        assert result.matched == 2
        assert route.call_args == ((suite, [td]), {"skip_unwritable": True})
        (td_update,) = _td_updates(session)
        assert str(td) in _compiled(td_update)

    def test_no_definition_update_when_none_is_writable(self):
        suite, blocked = uuid4(), uuid4()
        session = _session([AffectedRow(suite, blocked)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {})),
        ):
            result = set_test_results_disposition([uuid4()], Disposition.INACTIVE)
        assert result.matched == 1
        assert _td_updates(session) == []

    def test_confirming_a_frozen_contract_definition_whose_state_holds_opens_no_draft(self):
        self.frozen.return_value = True
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, td, test_active=True, lock_refresh=False)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {})) as route,
        ):
            result = set_test_results_disposition([uuid4()], Disposition.CONFIRMED)
        assert result.matched == 1
        route.assert_not_called()
        assert _td_updates(session) == []

    def test_confirming_a_muted_frozen_contract_definition_routes_it_to_the_draft(self):
        self.frozen.return_value = True
        suite, muted, holding, draft_copy = uuid4(), uuid4(), uuid4(), uuid4()
        session = _session([
            AffectedRow(suite, muted, test_active=False, lock_refresh=True),
            AffectedRow(suite, holding, test_active=True, lock_refresh=False),
        ])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {muted: draft_copy})) as route,
        ):
            set_test_results_disposition([uuid4(), uuid4()], Disposition.CONFIRMED)
        route.assert_called_once_with(suite, [muted], skip_unwritable=True)
        (td_update,) = _td_updates(session)
        assert str(draft_copy) in _compiled(td_update)

    def test_an_open_draft_receives_the_coupling_even_where_the_frozen_row_already_holds_it(self):
        suite, td, draft_copy = uuid4(), uuid4(), uuid4()
        session = _session([AffectedRow(suite, td, test_active=True, lock_refresh=False)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: draft_copy})) as route,
        ):
            set_test_results_disposition([uuid4()], Disposition.CONFIRMED)
        route.assert_called_once_with(suite, [td], skip_unwritable=True)
        (td_update,) = _td_updates(session)
        assert str(draft_copy) in _compiled(td_update)

    def test_the_affected_definitions_are_read_with_their_current_state(self):
        session = _session([])
        with patch(f"{MODULE}.get_current_session", return_value=session):
            set_test_results_disposition([uuid4()], Disposition.CONFIRMED)
        reads = [call.args[0] for call in session.execute.call_args_list if not isinstance(call.args[0], Update)]
        sql = _compiled(reads[0])
        assert "test_definitions.test_active" in sql
        assert "test_definitions.lock_refresh" in sql

    def test_muting_leaves_out_and_counts_the_results_of_managed_tests(self):
        session = _session([], rowcount=2)
        session.scalar.side_effect = [0, 3]
        with patch(f"{MODULE}.get_current_session", return_value=session):
            result = set_test_results_disposition([uuid4()], Disposition.INACTIVE)

        assert result == DispositionUpdate(matched=2, passed_skipped=0, managed_skipped=3)
        tr_update = session.execute.call_args_list[0].args[0]
        assert "test_results.test_type NOT IN ('Schema_Conformance')" in _compiled(tr_update)

    @pytest.mark.parametrize("disposition", [Disposition.CONFIRMED, Disposition.DISMISSED, None])
    def test_other_dispositions_apply_to_the_results_of_managed_tests(self, disposition):
        session = _session([])
        with patch(f"{MODULE}.get_current_session", return_value=session):
            result = set_test_results_disposition([uuid4()], disposition)

        assert result.managed_skipped == 0
        tr_update = session.execute.call_args_list[0].args[0]
        assert "Schema_Conformance" not in _compiled(tr_update)

    @pytest.mark.parametrize("disposition", [Disposition.CONFIRMED, Disposition.INACTIVE, None])
    def test_the_definitions_of_managed_tests_are_never_coupled(self, disposition):
        session = _session([])
        with patch(f"{MODULE}.get_current_session", return_value=session):
            set_test_results_disposition([uuid4()], disposition)
        reads = [call.args[0] for call in session.execute.call_args_list if not isinstance(call.args[0], Update)]
        assert "test_results.test_type NOT IN ('Schema_Conformance')" in _compiled(reads[0])
