from collections import namedtuple
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression
from sqlalchemy.sql.expression import Update

from testgen.common.models import test_definition as test_definition_module
from testgen.common.models.suite_version import (
    FrozenVersionError,
    RemovedInDraftError,
    SuiteVersion,
    UnmatchedInDraftError,
)
from testgen.common.models.test_definition import MissingTestDefinitionError, TestDefinition
from tests.unit.sql_assertions import conjuncts, equality_conjunct, is_not_null_conjunct, scopes_to_a_version

pytestmark = pytest.mark.unit

NIL_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _one_session_for_both_modules():
    """Point ``suite_version``'s session at whatever this module's tests patched.

    The frozen-version predicate lives on ``SuiteVersion`` so there is one copy of it, and it
    reads its own module's session while these tests patch ``test_definition``'s.
    """
    with patch(
        "testgen.common.models.suite_version.get_current_session",
        side_effect=lambda: test_definition_module.get_current_session(),
    ):
        yield



def _session_returning(value):
    session = MagicMock()
    session.scalar.return_value = value
    return session


def _checks_frozen_and_suite_owned(statement) -> bool:
    """Whether the statement ANDs a suite-owned check with a frozen check, as separate terms.

    An OR-ed predicate, or one missing either half, does not qualify — each half must appear as
    its own conjunct so neither can be satisfied by the other.
    """
    terms = conjuncts(statement.whereclause)
    return any(is_not_null_conjunct(term, "test_suite_id", "suite_versions") for term in terms) and any(
        is_not_null_conjunct(term, "frozen_at", "suite_versions") for term in terms
    )


def test_writing_a_suite_owned_frozen_version_is_refused():
    frozen_version_id = uuid4()
    with patch(
        "testgen.common.models.test_definition.get_current_session",
        return_value=_session_returning(frozen_version_id),
    ):
        with pytest.raises(FrozenVersionError):
            TestDefinition.assert_version_writable(frozen_version_id)


def test_writing_the_placeholder_is_allowed():
    # The placeholder is seeded frozen so it sits outside the one-draft index. A guard that
    # looked only at the freeze time would block every regular suite's writes.
    with patch(
        "testgen.common.models.test_definition.get_current_session",
        return_value=_session_returning(None),
    ):
        TestDefinition.assert_version_writable(NIL_UUID)


def test_writing_a_draft_is_allowed():
    with patch(
        "testgen.common.models.test_definition.get_current_session",
        return_value=_session_returning(None),
    ):
        TestDefinition.assert_version_writable(uuid4())


def test_the_guard_looks_for_a_version_that_is_frozen_and_suite_owned():
    session = _session_returning(None)
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.assert_version_writable(uuid4())

    statement = session.scalar.call_args.args[0]
    assert _checks_frozen_and_suite_owned(statement)


def _routed_session(*pairs):
    """A session whose lookup of each named row's suite answers ``pairs`` of (row id, suite id)."""
    session = MagicMock()
    session.execute.return_value.all.return_value = list(pairs)
    session.execute.return_value.scalars.return_value.all.return_value = [row_id for row_id, _ in pairs]
    return session


def _bulk_params(session) -> dict:
    return session.execute.call_args.args[1]


def test_set_status_attribute_on_a_frozen_only_contract_lands_on_the_newly_opened_draft():
    frozen_row, draft_row, suite_id = uuid4(), uuid4(), uuid4()
    session = _routed_session((frozen_row, suite_id))
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {frozen_row: draft_row})) as resolve,
    ):
        TestDefinition.set_status_attribute("flagged", [str(frozen_row)], True)

    resolve.assert_called_once_with(suite_id, [frozen_row])
    assert _bulk_params(session)["test_definition_ids"] == [str(draft_row)]
    assert str(frozen_row) not in _bulk_params(session)["test_definition_ids"]


def test_set_status_attribute_on_a_regular_suite_writes_the_named_rows_unchanged():
    row, suite_id = uuid4(), uuid4()
    session = _routed_session((row, suite_id))
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(TestDefinition, "resolve_writable", return_value=(NIL_UUID, {row: row})),
    ):
        TestDefinition.set_status_attribute("flagged", [str(row)], True)

    assert _bulk_params(session)["test_definition_ids"] == [str(row)]


def test_set_status_attribute_routes_each_suite_of_a_mixed_batch_separately():
    regular_row, frozen_row, draft_row = uuid4(), uuid4(), uuid4()
    regular_suite, contract_suite = uuid4(), uuid4()
    session = _routed_session((regular_row, regular_suite), (frozen_row, contract_suite))
    answers = {regular_suite: {regular_row: regular_row}, contract_suite: {frozen_row: draft_row}}
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(
            TestDefinition, "resolve_writable", side_effect=lambda suite, _ids: (uuid4(), answers[suite])
        ),
    ):
        TestDefinition.set_status_attribute("flagged", [str(regular_row), str(frozen_row)], True)

    assert _bulk_params(session)["test_definition_ids"] == [str(regular_row), str(draft_row)]


def test_set_status_attribute_with_no_rows_issues_no_statement_beyond_the_lookup():
    session = _routed_session()
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.set_status_attribute("flagged", [], True)

    session.execute.assert_not_called()


def test_delete_where_on_a_frozen_only_contract_deletes_the_drafts_copy_not_the_frozen_row():
    frozen_row, draft_row, suite_id = uuid4(), uuid4(), uuid4()
    session = _routed_session((frozen_row, suite_id))
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.get_current_session", return_value=session),
        patch.object(TestDefinition, "_assert_no_managed_definitions"),
        patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {frozen_row: draft_row})),
    ):
        TestDefinition.delete_where(TestDefinition.id.in_([frozen_row]))

    statement = session.execute.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert str(draft_row) in compiled
    assert str(frozen_row) not in compiled
    assert scopes_to_a_version(statement)


def test_delete_where_on_a_regular_suite_deletes_the_selected_rows():
    row, suite_id = uuid4(), uuid4()
    session = _routed_session((row, suite_id))
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.get_current_session", return_value=session),
        patch.object(TestDefinition, "_assert_no_managed_definitions"),
        patch.object(TestDefinition, "resolve_writable", return_value=(NIL_UUID, {row: row})),
    ):
        TestDefinition.delete_where(TestDefinition.id.in_([row]))

    compiled = str(
        session.execute.call_args.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert str(row) in compiled


def _move(session, frozen_row, draft_row):
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(TestDefinition, "_assert_no_managed_definitions"),
        patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {frozen_row: draft_row})) as resolve,
        patch.object(TestDefinition, "assign_missing_term_ids") as assign,
    ):
        TestDefinition.move([str(frozen_row)], uuid4(), uuid4(), target_schema="public", qualifies_table_refs=True)
    return resolve, assign


def test_move_out_of_a_frozen_only_contract_moves_the_drafts_copy_and_clears_its_term_identity():
    frozen_row, draft_row, suite_id = uuid4(), uuid4(), uuid4()
    session = _routed_session((frozen_row, suite_id))
    session.scalar.side_effect = [NIL_UUID, None]
    session.scalars.return_value.all.return_value = [draft_row]
    _, assign = _move(session, frozen_row, draft_row)

    update = _updates(session)[0]
    compiled = str(update.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert str(draft_row) in compiled
    assert str(frozen_row) not in compiled
    assert update.compile().params["contract_term_id"] is None
    assign.assert_called_once_with(NIL_UUID)


def test_move_routes_the_named_rows_through_their_suites():
    frozen_row, draft_row, suite_id = uuid4(), uuid4(), uuid4()
    session = _routed_session((frozen_row, suite_id))
    session.scalar.side_effect = [NIL_UUID, None]
    session.scalars.return_value.all.return_value = [draft_row]
    resolve, _ = _move(session, frozen_row, draft_row)

    resolve.assert_called_once_with(suite_id, [frozen_row])


def test_save_of_an_active_row_with_a_draft_open_lands_on_the_drafts_copy():
    active, draft, copy_id = uuid4(), uuid4(), uuid4()
    active_id = uuid4()
    term = TestDefinition(id=active_id, test_suite_id=uuid4(), version_id=active, test_type="Row_Ct")
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=MagicMock()),
        patch.object(TestDefinition, "resolve_writable", return_value=(draft, {active_id: copy_id})) as route,
    ):
        term.save()
    route.assert_called_once_with(term.test_suite_id, [active_id])
    assert (term.id, term.version_id) == (copy_id, draft)


def _session_reading_the_loaded_row(**stored):
    """A session whose SELECT of the row an edit was loaded from returns ``stored``."""
    session = MagicMock()
    loaded_row = MagicMock(**stored)
    session.execute.side_effect = lambda statement: (
        MagicMock() if isinstance(statement, Update) else MagicMock(one=MagicMock(return_value=loaded_row))
    )
    return session


def _update_values(session) -> dict:
    (update,) = (call.args[0] for call in session.execute.call_args_list if isinstance(call.args[0], Update))
    return {column.key: value for column, value in update._values.items()}


def test_save_routed_onto_the_drafts_copy_writes_only_what_the_edit_changed():
    active, draft, copy_id, active_id = uuid4(), uuid4(), uuid4(), uuid4()
    suite_id = uuid4()
    stored = {
        column.key: None for column in TestDefinition.__table__.columns
    } | {"id": active_id, "test_suite_id": suite_id, "version_id": active, "test_type": "Row_Ct",
         "severity": "Fail", "threshold_value": "5"}
    term = TestDefinition(**{**stored, "severity": "Warning"})
    session = _session_reading_the_loaded_row(**stored)
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(TestDefinition, "resolve_writable", return_value=(draft, {active_id: copy_id})),
        patch.object(SuiteVersion, "is_suite_owned", return_value=False),
    ):
        term.save()

    written = _update_values(session)
    assert "severity" in written
    assert "threshold_value" not in written, "the edit reverts a value the draft's copy may have changed"


def test_save_of_a_row_that_stays_put_reads_nothing_back():
    row_id = uuid4()
    term = TestDefinition(id=row_id, test_suite_id=uuid4(), version_id=uuid4(), test_type="Row_Ct", severity="Fail")
    session = _session_reading_the_loaded_row()
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(TestDefinition, "resolve_writable", return_value=(term.version_id, {row_id: row_id})),
        patch.object(SuiteVersion, "is_suite_owned", return_value=False),
    ):
        term.save()

    assert [call for call in session.execute.call_args_list if not isinstance(call.args[0], Update)] == []
    assert "threshold_value" in _update_values(session)


def test_save_of_a_row_that_no_longer_exists_is_refused():
    term = TestDefinition(id=uuid4(), test_suite_id=uuid4(), version_id=uuid4(), test_type="Row_Ct")
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=MagicMock()),
        patch.object(TestDefinition, "resolve_writable", return_value=(uuid4(), {})),
        pytest.raises(ValueError, match="no longer exists"),
    ):
        term.save()


def test_a_new_term_on_a_frozen_only_contract_is_inserted_into_the_draft():
    frozen_version_id = uuid4()
    draft_version_id = uuid4()
    term = TestDefinition(
        test_suite_id=uuid4(), test_type="Row_Ct", schema_name="public",
        table_name="orders", column_name="order_id",
    )
    session = MagicMock()
    # The version a new definition resolves to, then the routing check, which finds it frozen,
    # then the draft's suite-owned check, then the term-identity taken-check.
    session.scalar.side_effect = [frozen_version_id, frozen_version_id, draft_version_id, None]
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.entity.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=frozen_version_id)),
        patch.object(
            TestDefinition, "resolve_write_target",
            return_value=(draft_version_id, {}),
        ),
    ):
        term.save()

    assert term.version_id == draft_version_id


def test_move_refuses_a_frozen_suite_owned_target_version():
    frozen_version_id = uuid4()
    # First scalar call resolves the target version; the second is the guard's own
    # frozen-and-suite-owned check, which finds the same row and must raise.
    session = MagicMock()
    session.scalar.side_effect = [frozen_version_id, frozen_version_id]
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        with pytest.raises(FrozenVersionError):
            TestDefinition.move([str(uuid4())], uuid4(), uuid4(), target_schema="public", qualifies_table_refs=True)

    session.execute.assert_not_called()


def test_copy_refuses_a_frozen_suite_owned_target_version():
    frozen_version_id = uuid4()
    session = MagicMock()
    session.scalar.side_effect = [frozen_version_id, frozen_version_id]
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        with pytest.raises(FrozenVersionError):
            TestDefinition.copy([str(uuid4())], uuid4(), uuid4(), target_schema="public", qualifies_table_refs=True)

    session.execute.assert_not_called()


Row = namedtuple("Row", "id version_id contract_term_id")


def _with_rows(session, *rows):
    """Answer the row lookup a write routes through with ``rows``."""
    session.execute.return_value.all.return_value = list(rows)
    return session


def _updates(session) -> list:
    return [call.args[0] for call in session.execute.call_args_list if isinstance(call.args[0], Update)]


def test_editing_a_term_on_a_frozen_only_contract_lands_in_a_draft():
    """Where no draft exists, one comes into being to receive the edit, carrying a copy of
    the agreement in force. Nobody is asked to make a version first, so editing a term on a
    contract whose only version is frozen must land in a new draft rather than be refused.
    """
    frozen_version_id = uuid4()
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = frozen_version_id

    draft_version_id = uuid4()
    copied_id = uuid4()
    session = _with_rows(_session_returning(frozen_version_id), Row(definition.id, frozen_version_id, "t"))
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=frozen_version_id)),
        patch.object(
            TestDefinition, "resolve_write_target",
            return_value=(draft_version_id, {definition.id: copied_id}),
        ),
    ):
        definition.save()

    assert definition.version_id == draft_version_id
    assert definition.id == copied_id


def test_a_payload_carrying_string_ids_routes_onto_the_draft_like_any_other():
    """An edit dialog rebuilds a definition from a JSON payload, where every id is a string.

    Both comparisons the router makes are against ids the ORM hands back as ``UUID`` -- the
    version in force, and the keys of the copy map. A string loses each of them, so a row the
    draft does hold is refused, and refused after the draft exists, which is the one outcome
    the refusal path is built to avoid.
    """
    frozen_version_id = uuid4()
    definition_id = uuid4()
    definition = TestDefinition()
    definition.id = str(definition_id)
    definition.test_suite_id = str(uuid4())
    definition.version_id = str(frozen_version_id)

    draft_version_id = uuid4()
    copied_id = uuid4()
    session = _with_rows(_session_returning(frozen_version_id), Row(definition_id, frozen_version_id, "t"))
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=frozen_version_id)),
        patch.object(
            TestDefinition, "resolve_write_target",
            return_value=(draft_version_id, {definition_id: copied_id}),
        ),
    ):
        definition.save()

    assert definition.version_id == draft_version_id
    assert definition.id == copied_id


def _session_routing_version_lookups(row_id, *, persisted_version, frozen_versions=(), resolved=None):
    """A session answering the persisted-row lookup, the frozen check and the resolved-version
    lookup by what each asks.

    The row lookup returns the persisted row, or nothing when ``persisted_version`` is None. The
    frozen check answers by the version id it names; the resolved-version lookup, which names
    none, answers ``resolved`` (the persisted version when not given).
    """
    def scalar(statement):
        for term in conjuncts(statement.whereclause):
            if not isinstance(term, BinaryExpression) or term.operator is not operators.eq:
                continue
            left = term.left
            if getattr(left, "key", None) == "id" and getattr(left.table, "name", None) == "suite_versions":
                value = getattr(term.right, "value", None)
                return value if value in frozen_versions else None
        return resolved or persisted_version

    session = MagicMock()
    session.scalar.side_effect = scalar
    rows = [Row(row_id, persisted_version, "term")] if persisted_version else []
    return _with_rows(session, *rows)


def test_an_update_whose_instance_carries_no_version_is_guarded_by_the_persisted_row():
    """The product's edit dialog rebuilds a definition from a summary payload, which carries
    no ``version_id``, so the instance holding one is not something the guard can assume. A
    guard that reads the instance passes every such edit straight onto the frozen term.
    """
    frozen_version_id = uuid4()
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = None

    draft_version_id, copied_id = uuid4(), uuid4()
    session = _session_routing_version_lookups(
        definition.id, persisted_version=frozen_version_id, frozen_versions=(frozen_version_id,)
    )
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=frozen_version_id)),
        patch.object(
            TestDefinition, "resolve_write_target", return_value=(draft_version_id, {definition.id: copied_id})
        ),
    ):
        definition.save()

    assert (definition.id, definition.version_id) == (copied_id, draft_version_id)


def test_an_update_whose_persisted_row_is_on_a_draft_proceeds():
    draft_version_id = uuid4()
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = None

    session = _session_routing_version_lookups(definition.id, persisted_version=draft_version_id)
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        definition.save()

    assert len(_updates(session)) == 1


def test_an_update_of_a_row_that_no_longer_exists_is_refused():
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = None

    session = _session_routing_version_lookups(definition.id, persisted_version=None, resolved=uuid4())
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        with pytest.raises(MissingTestDefinitionError):
            definition.save()

    assert _updates(session) == []


def test_the_update_narrows_by_the_rows_resolved_version():
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = uuid4()

    session = _with_rows(_session_returning(None), Row(definition.id, definition.version_id, None))
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        definition.save()

    statement = session.execute.call_args.args[0]
    assert scopes_to_a_version(statement)


def test_refusing_a_superseded_version_write_opens_no_draft_and_copies_nothing():
    """The refusal has to be decided before the write target is resolved. Resolving it first
    opens a draft and copies the whole agreement into it, and the exception that follows is
    caught nowhere -- the router's blanket handler commits in its finally, so the phantom
    draft is durable and every later read of the contract resolves to it.
    """
    superseded_version_id = uuid4()
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = superseded_version_id

    session = _session_routing_version_lookups(
        definition.id, persisted_version=superseded_version_id, frozen_versions=(superseded_version_id,)
    )
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=uuid4())),
        patch.object(TestDefinition, "resolve_write_target") as resolve,
    ):
        with pytest.raises(FrozenVersionError):
            definition.save()

    resolve.assert_not_called()
    assert _updates(session) == []


def test_a_contract_with_no_version_in_force_refuses_a_frozen_row_outright():
    frozen_version_id = uuid4()
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = frozen_version_id

    session = _session_routing_version_lookups(
        definition.id, persisted_version=frozen_version_id, frozen_versions=(frozen_version_id,)
    )
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=None),
        patch.object(TestDefinition, "resolve_write_target") as resolve,
    ):
        with pytest.raises(FrozenVersionError):
            definition.save()

    resolve.assert_not_called()


def _session_for_rows(rows, *, resolved, draft_rows=()):
    """A session whose row lookup returns ``rows``, whose resolved-version lookup returns
    ``resolved``, and whose draft lookup by term identity returns ``draft_rows``."""
    session = MagicMock()
    session.execute.return_value.all.side_effect = [list(rows), list(draft_rows)]
    session.scalar.return_value = resolved
    return session


def _routing(session, *, frozen=(), in_force=None, write_target=None):
    return (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "is_frozen_agreement", side_effect=lambda v: v in frozen),
        patch.object(SuiteVersion, "in_force_for", return_value=in_force),
        patch.object(TestDefinition, "resolve_write_target", return_value=write_target),
    )


def test_rows_of_a_writable_version_map_to_themselves_and_open_nothing():
    placeholder = uuid4()
    row = Row(uuid4(), placeholder, None)
    session = _session_for_rows([row], resolved=placeholder)
    p_session, p_frozen, p_force, p_target = _routing(session)
    with p_session, p_frozen, p_force, p_target as resolve:
        version, mapping = TestDefinition.resolve_writable(uuid4(), [row.id])
    assert (version, mapping) == (placeholder, {row.id: row.id})
    resolve.assert_not_called()


def test_an_active_row_with_no_draft_maps_to_its_copy_in_the_new_draft():
    active, draft = uuid4(), uuid4()
    row, copy_id = Row(uuid4(), active, "orders-row-count"), uuid4()
    session = _session_for_rows([row], resolved=active)
    p = _routing(session, frozen={active}, in_force=MagicMock(id=active), write_target=(draft, {row.id: copy_id}))
    with p[0], p[1], p[2], p[3]:
        assert TestDefinition.resolve_writable(uuid4(), [row.id]) == (draft, {row.id: copy_id})


def test_an_active_row_with_a_draft_open_maps_to_the_drafts_copy_by_term_identity():
    active, draft = uuid4(), uuid4()
    row, copy_id = Row(uuid4(), active, "orders-row-count"), uuid4()
    session = _session_for_rows(
        [row], resolved=draft, draft_rows=[Row(copy_id, draft, "orders-row-count")]
    )
    p = _routing(session, frozen={active}, in_force=MagicMock(id=active), write_target=(draft, {}))
    with p[0], p[1], p[2], p[3]:
        assert TestDefinition.resolve_writable(uuid4(), [row.id]) == (draft, {row.id: copy_id})

    lookup = session.execute.call_args_list[1].args[0]
    terms = conjuncts(lookup.whereclause)
    assert any(equality_conjunct(t, "version_id", "test_definitions", draft) for t in terms)
    assert "contract_term_id IN" in str(lookup.compile(dialect=postgresql.dialect()))


def test_an_active_row_the_draft_removed_is_refused_by_name():
    active, draft = uuid4(), uuid4()
    kept, removed = Row(uuid4(), active, "kept"), Row(uuid4(), active, "removed")
    session = _session_for_rows([kept, removed], resolved=draft, draft_rows=[Row(uuid4(), draft, "kept")])
    p = _routing(session, frozen={active}, in_force=MagicMock(id=active), write_target=(draft, {}))
    with p[0], p[1], p[2], p[3], pytest.raises(RemovedInDraftError) as raised:
        TestDefinition.resolve_writable(uuid4(), [kept.id, removed.id])
    assert raised.value.row_ids == [removed.id]
    assert raised.value.version_id == draft


def test_a_superseded_row_is_refused_before_a_draft_is_opened():
    superseded, active = uuid4(), uuid4()
    row = Row(uuid4(), superseded, "old")
    session = _session_for_rows([row], resolved=active)
    p = _routing(session, frozen={superseded, active}, in_force=MagicMock(id=active))
    with p[0], p[1], p[2], p[3] as resolve, pytest.raises(FrozenVersionError):
        TestDefinition.resolve_writable(uuid4(), [row.id])
    resolve.assert_not_called()


def test_no_rows_named_on_a_frozen_only_contract_opens_a_draft():
    active, draft = uuid4(), uuid4()
    session = _session_for_rows([], resolved=active)
    p = _routing(session, frozen={active}, in_force=MagicMock(id=active), write_target=(draft, {}))
    with p[0], p[1], p[2], p[3]:
        assert TestDefinition.resolve_writable(uuid4()) == (draft, {})


def test_no_rows_named_on_a_writable_version_opens_nothing():
    placeholder = uuid4()
    session = _session_for_rows([], resolved=placeholder)
    p = _routing(session)
    with p[0], p[1], p[2], p[3] as resolve:
        assert TestDefinition.resolve_writable(uuid4()) == (placeholder, {})
    resolve.assert_not_called()


def test_the_frozen_check_runs_once_per_distinct_version():
    placeholder = uuid4()
    rows = [Row(uuid4(), placeholder, None) for _ in range(3)]
    session = _session_for_rows(rows, resolved=placeholder)
    p = _routing(session)
    with p[0], p[1] as frozen_check, p[2], p[3]:
        TestDefinition.resolve_writable(uuid4(), [row.id for row in rows])
    assert [call.args[0] for call in frozen_check.call_args_list] == [placeholder]


def test_an_active_row_with_no_contract_identity_is_refused_as_unmatched_while_a_draft_is_open():
    active, draft = uuid4(), uuid4()
    matched, unmatched = Row(uuid4(), active, "kept"), Row(uuid4(), active, None)
    session = _session_for_rows([matched, unmatched], resolved=draft)
    p = _routing(session, frozen={active}, in_force=MagicMock(id=active), write_target=(draft, {}))
    with p[0], p[1], p[2], p[3], pytest.raises(UnmatchedInDraftError) as raised:
        TestDefinition.resolve_writable(uuid4(), [matched.id, unmatched.id])
    assert isinstance(raised.value, FrozenVersionError), "every caller that refuses a frozen write still refuses it"
    assert raised.value.version_id == active
    assert raised.value.draft_id == draft
    assert raised.value.row_ids == [unmatched.id]


def test_the_superseded_version_refused_is_the_first_named_rows():
    first, second, active = uuid4(), uuid4(), uuid4()
    named = [Row(uuid4(), first, "a"), Row(uuid4(), second, "b")]
    session = _session_for_rows(list(reversed(named)), resolved=active)
    p = _routing(session, frozen={first, second, active}, in_force=MagicMock(id=active))
    with p[0], p[1], p[2], p[3], pytest.raises(FrozenVersionError) as raised:
        TestDefinition.resolve_writable(uuid4(), [row.id for row in named])
    assert raised.value.version_id == first


def _recording_session(events: list) -> MagicMock:
    session = MagicMock()
    session.expunge.side_effect = lambda _obj: events.append("expunge")
    session.no_autoflush.__enter__.side_effect = lambda *_: events.append("autoflush off")
    session.no_autoflush.__exit__.side_effect = lambda *_: events.append("autoflush on")
    return session


def _routing_recorded(events: list, term: TestDefinition, *, moved_to=None):
    def route(_suite_id, row_ids):
        events.append("route")
        return term.version_id, {row_ids[0]: moved_to or row_ids[0]}

    return patch.object(TestDefinition, "resolve_writable", side_effect=route)


def test_saving_a_persistent_row_that_stays_put_keeps_it_attached_and_routes_with_autoflush_off():
    """A loaded row may carry pending changes to columns the UPDATE does not write, which only
    the session's own flush persists, so a row whose edit lands on itself stays attached."""
    events: list = []
    session = _recording_session(events)
    term = TestDefinition(id=uuid4(), test_suite_id=uuid4(), version_id=uuid4(), test_type="Row_Ct")
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.inspect", return_value=MagicMock(persistent=True)),
        patch.object(SuiteVersion, "is_frozen_agreement", return_value=False),
        _routing_recorded(events, term),
    ):
        term.save()
    assert events == ["autoflush off", "route", "autoflush on"]
    session.expunge.assert_not_called()


def test_saving_a_persistent_row_of_a_frozen_version_detaches_it_before_it_moves():
    """A loaded row of a frozen version is dirty with an edit meant for the draft's copy. Any
    flush while it is attached, including the explicit ones opening a draft, writes the edit
    onto the frozen row, and moving its id onto the copy reads as a primary-key change."""
    events: list = []
    session = _recording_session(events)
    original_id, copy_id = uuid4(), uuid4()
    term = TestDefinition(id=original_id, test_suite_id=uuid4(), version_id=uuid4(), test_type="Row_Ct")
    session.expunge.side_effect = lambda obj: events.append(("expunge", obj.id))
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.inspect", return_value=MagicMock(persistent=True)),
        patch.object(SuiteVersion, "is_frozen_agreement", return_value=True),
        _routing_recorded(events, term, moved_to=copy_id),
    ):
        term.save()
    assert events == ["autoflush off", ("expunge", original_id), "route", "autoflush on"]
    assert term.id == copy_id


def test_saving_a_transient_row_detaches_nothing():
    events: list = []
    session = _recording_session(events)
    term = TestDefinition(id=uuid4(), test_suite_id=uuid4(), version_id=uuid4(), test_type="Row_Ct")
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        _routing_recorded(events, term),
    ):
        term.save()
    session.expunge.assert_not_called()
    assert "route" in events


def test_skipping_unwritable_rows_leaves_a_superseded_row_out_and_routes_the_rest():
    superseded, active, draft = uuid4(), uuid4(), uuid4()
    old, current, copy_id = Row(uuid4(), superseded, "old"), Row(uuid4(), active, "current"), uuid4()
    session = _session_for_rows([old, current], resolved=active)
    p = _routing(
        session, frozen={superseded, active}, in_force=MagicMock(id=active), write_target=(draft, {current.id: copy_id})
    )
    with p[0], p[1], p[2], p[3]:
        mapping = TestDefinition.resolve_writable(uuid4(), [old.id, current.id], skip_unwritable=True)
    assert mapping == (draft, {current.id: copy_id})


def test_skipping_unwritable_rows_opens_no_draft_when_every_row_is_superseded():
    superseded, active = uuid4(), uuid4()
    row = Row(uuid4(), superseded, "old")
    session = _session_for_rows([row], resolved=active)
    p = _routing(session, frozen={superseded, active}, in_force=MagicMock(id=active))
    with p[0], p[1], p[2], p[3] as resolve:
        assert TestDefinition.resolve_writable(uuid4(), [row.id], skip_unwritable=True) == (active, {})
    resolve.assert_not_called()


def test_skipping_unwritable_rows_leaves_out_rows_the_draft_cannot_match():
    active, draft = uuid4(), uuid4()
    kept, removed, unmatchable = Row(uuid4(), active, "kept"), Row(uuid4(), active, "removed"), Row(uuid4(), active, None)
    copy_id = uuid4()
    session = _session_for_rows(
        [kept, removed, unmatchable], resolved=draft, draft_rows=[Row(copy_id, draft, "kept")]
    )
    p = _routing(session, frozen={active}, in_force=MagicMock(id=active), write_target=(draft, {}))
    with p[0], p[1], p[2], p[3]:
        mapping = TestDefinition.resolve_writable(
            uuid4(), [kept.id, removed.id, unmatchable.id], skip_unwritable=True
        )
    assert mapping == (draft, {kept.id: copy_id})
