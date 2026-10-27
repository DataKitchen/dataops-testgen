from collections import namedtuple
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.expression import Update

from testgen.common.enums import Disposition, SuiteType
from testgen.common.models.test_definition import TestDefinition
from testgen.common.test_result_disposition_service import (
    ContractDraftChange,
    DispositionUpdate,
    coerce_ui_disposition,
    coupled_test_definition_state,
    set_test_results_disposition,
)
from tests.unit.sql_assertions import scopes_to_a_version

pytestmark = pytest.mark.unit

MODULE = "testgen.common.test_result_disposition_service"

AffectedRow = namedtuple(
    "AffectedRow",
    "test_suite_id test_definition_id test_active lock_refresh suite_type",
    defaults=(True, False, SuiteType.REGULAR),
)
CopyRow = namedtuple("CopyRow", "id test_active lock_refresh", defaults=(True, False))


def _session(affected, rowcount=1, passed=0, copies=()):
    """``affected`` answers the read of the results' definitions, ``copies`` the read of their draft copies."""
    session = MagicMock()
    session.scalar.return_value = passed

    def execute(statement):
        if isinstance(statement, Update):
            return MagicMock(rowcount=rowcount)
        return MagicMock(all=lambda: affected if "test_results" in str(statement) else list(copies))

    session.execute.side_effect = execute
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
        with (
            patch(f"{MODULE}.SuiteVersion.is_frozen_agreement", return_value=False) as frozen,
            patch(f"{MODULE}.SuiteVersion.get", return_value=MagicMock(version=2)),
            patch(f"{MODULE}._contract_name", return_value="Orders"),
        ):
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
        session = _session([AffectedRow(suite, active)], copies=[CopyRow(draft_copy)])
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
        session = _session(
            [AffectedRow(suite, blocked), AffectedRow(suite, active)], rowcount=2,
            copies=[CopyRow(draft_copy, test_active=False, lock_refresh=True)],
        )
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
        session = _session([AffectedRow(suite, td, True, False, SuiteType.CONTRACT)])
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
        session = _session(
            [
                AffectedRow(suite, muted, False, True, SuiteType.CONTRACT),
                AffectedRow(suite, holding, True, True, SuiteType.CONTRACT),
            ],
            copies=[CopyRow(draft_copy, test_active=False, lock_refresh=True)],
        )
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
        session = _session(
            [AffectedRow(suite, td, test_active=True, lock_refresh=False)],
            copies=[CopyRow(draft_copy, test_active=False, lock_refresh=True)],
        )
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: draft_copy})) as route,
        ):
            set_test_results_disposition([uuid4()], Disposition.CONFIRMED)
        route.assert_called_once_with(suite, [td], skip_unwritable=True)
        (td_update,) = _td_updates(session)
        assert str(draft_copy) in _compiled(td_update)

    @pytest.mark.parametrize("disposition", [Disposition.CONFIRMED, Disposition.DISMISSED])
    def test_a_regular_suites_definition_is_unlocked_when_reactivated(self, disposition):
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, td, test_active=True, lock_refresh=True)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: td})),
        ):
            set_test_results_disposition([uuid4()], disposition)
        params = _td_updates(session)[0].compile().params
        assert params["test_active"] is True
        assert params["lock_refresh"] is False

    @pytest.mark.parametrize("disposition", [Disposition.CONFIRMED, Disposition.DISMISSED, None])
    def test_a_contract_term_keeps_its_lock_when_reactivated(self, disposition):
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, td, False, True, SuiteType.CONTRACT)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: td})),
        ):
            set_test_results_disposition([uuid4()], disposition)
        (td_update,) = _td_updates(session)
        params = td_update.compile().params
        assert params["test_active"] is True
        assert "lock_refresh" not in params
        assert scopes_to_a_version(td_update)

    def test_a_contract_term_is_locked_when_muted(self):
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, td, True, False, SuiteType.CONTRACT)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {td: td})),
        ):
            set_test_results_disposition([uuid4()], Disposition.INACTIVE)
        params = _td_updates(session)[0].compile().params
        assert params["test_active"] is False
        assert params["lock_refresh"] is True

    def test_dismissing_an_active_locked_term_of_a_frozen_contract_opens_no_draft(self):
        self.frozen.return_value = True
        suite, td = uuid4(), uuid4()
        session = _session([AffectedRow(suite, td, True, True, SuiteType.CONTRACT)])
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {})) as route,
        ):
            result = set_test_results_disposition([uuid4()], Disposition.DISMISSED)
        assert result.matched == 1
        assert result.contract_drafts == ()
        route.assert_not_called()
        assert _td_updates(session) == []

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


class Test_contract_draft_changes:
    """A coupling the active version of a contract keeps out of force is reported with its draft."""

    @pytest.fixture(autouse=True)
    def _contract(self):
        with (
            patch(f"{MODULE}.SuiteVersion.is_frozen_agreement", return_value=False),
            patch(f"{MODULE}.SuiteVersion.get", return_value=MagicMock(version=4)) as get_version,
            patch(f"{MODULE}._contract_name", return_value="Orders") as contract_name,
        ):
            self.get_version = get_version
            self.contract_name = contract_name
            yield

    def _set(self, affected, copies, mapping, disposition, frozen=False):
        session = _session(affected, rowcount=len(affected), copies=copies)
        draft_id = uuid4()
        with (
            patch(f"{MODULE}.get_current_session", return_value=session),
            patch(f"{MODULE}.SuiteVersion.is_frozen_agreement", return_value=frozen),
            patch.object(TestDefinition, "resolve_writable", return_value=(draft_id, mapping)),
        ):
            result = set_test_results_disposition([uuid4() for _ in affected], disposition)
        return result, session, draft_id

    def test_muting_a_frozen_only_contracts_result_names_the_draft_it_opened(self):
        suite, active, draft_copy = uuid4(), uuid4(), uuid4()
        result, session, draft_id = self._set(
            [AffectedRow(suite, active, suite_type=SuiteType.CONTRACT)], [CopyRow(draft_copy)], {active: draft_copy}, Disposition.INACTIVE, frozen=True
        )

        assert result.contract_drafts == (
            ContractDraftChange(contract_name="Orders", draft_version=4, test_count=1, muted=True),
        )
        self.get_version.assert_called_once_with(draft_id)
        self.contract_name.assert_called_once_with(suite)
        assert len(_td_updates(session)) == 1

    def test_unmuting_into_an_existing_draft_names_it_as_unmuted(self):
        suite, active, draft_copy = uuid4(), uuid4(), uuid4()
        result, _, _ = self._set(
            [AffectedRow(suite, active, False, True, SuiteType.CONTRACT)],
            [CopyRow(draft_copy, test_active=False, lock_refresh=True)],
            {active: draft_copy},
            Disposition.DISMISSED,
        )

        assert result.contract_drafts == (
            ContractDraftChange(contract_name="Orders", draft_version=4, test_count=1, muted=False),
        )

    def test_a_draft_copy_already_in_the_coupled_state_is_neither_written_nor_reported(self):
        suite, active, draft_copy = uuid4(), uuid4(), uuid4()
        result, session, _ = self._set(
            [AffectedRow(suite, active, suite_type=SuiteType.CONTRACT)],
            [CopyRow(draft_copy, test_active=False, lock_refresh=True)],
            {active: draft_copy},
            Disposition.INACTIVE,
        )

        assert result.contract_drafts == ()
        assert _td_updates(session) == []

    def test_each_rerouted_test_that_changes_is_counted(self):
        suite, first, second, holding = uuid4(), uuid4(), uuid4(), uuid4()
        copies = {first: uuid4(), second: uuid4(), holding: uuid4()}
        result, session, _ = self._set(
            [AffectedRow(suite, first, suite_type=SuiteType.CONTRACT), AffectedRow(suite, second, suite_type=SuiteType.CONTRACT),
             AffectedRow(suite, holding, suite_type=SuiteType.CONTRACT)],
            [
                CopyRow(copies[first]),
                CopyRow(copies[second]),
                CopyRow(copies[holding], test_active=False, lock_refresh=True),
            ],
            copies,
            Disposition.INACTIVE,
        )

        assert [change.test_count for change in result.contract_drafts] == [2]
        sql = _compiled(_td_updates(session)[0])
        assert str(copies[first]) in sql
        assert str(copies[second]) in sql
        assert str(copies[holding]) not in sql

    def test_a_write_to_its_own_version_is_not_reported(self):
        suite, td = uuid4(), uuid4()
        result, session, _ = self._set([AffectedRow(suite, td, suite_type=SuiteType.CONTRACT)], [], {td: td}, Disposition.INACTIVE)

        assert result.contract_drafts == ()
        assert len(_td_updates(session)) == 1
        self.contract_name.assert_not_called()

    def test_dismissing_into_a_draft_whose_copy_is_active_and_locked_neither_writes_nor_reports_it(self):
        suite, active, draft_copy = uuid4(), uuid4(), uuid4()
        result, session, _ = self._set(
            [AffectedRow(suite, active, True, True, SuiteType.CONTRACT)],
            [CopyRow(draft_copy, test_active=True, lock_refresh=True)],
            {active: draft_copy},
            Disposition.DISMISSED,
        )

        assert result.contract_drafts == ()
        assert _td_updates(session) == []

    def test_a_frozen_only_contracts_result_already_in_the_coupled_state_opens_no_draft_and_is_not_reported(self):
        suite, active = uuid4(), uuid4()
        result, _, _ = self._set(
            [AffectedRow(suite, active, True, True, SuiteType.CONTRACT)], [], {}, Disposition.DISMISSED,
            frozen=True,
        )

        assert result.contract_drafts == ()


@pytest.mark.parametrize(("change", "counted", "notice"), [
    (
        ContractDraftChange("Orders", 4, 1, muted=True), True,
        "The test is muted in draft v4 of the contract Orders. The active version keeps running it until the draft "
        "is frozen.",
    ),
    (
        ContractDraftChange("Orders", 4, 3, muted=False), True,
        "The 3 tests are unmuted in draft v4 of the contract Orders. The active version keeps running them until "
        "the draft is frozen.",
    ),
    (
        ContractDraftChange("Orders", 4, 1, muted=True), False,
        "The tests are muted in draft v4 of the contract Orders. The active version keeps running them until the "
        "draft is frozen.",
    ),
])
def test_a_draft_change_reads_as_the_draft_it_landed_on(change, counted, notice):
    assert change.notice(counted=counted) == notice
