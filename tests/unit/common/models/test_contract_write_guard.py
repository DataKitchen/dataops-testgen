from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression

from testgen.common.models import test_definition as test_definition_module
from testgen.common.models.suite_version import FrozenVersionError, SuiteVersion
from testgen.common.models.test_definition import MissingTestDefinitionError, TestDefinition
from tests.unit.sql_assertions import conjuncts, is_not_null_conjunct, scopes_to_a_version

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


def _session_resolving_versions(version_ids, *, frozen_check_results):
    """A session whose batch resolution yields `version_ids`, then answers the per-version
    frozen-and-suite-owned check with `frozen_check_results`, in order.
    """
    session = MagicMock()
    session.scalars.return_value.all.return_value = version_ids
    session.scalar.side_effect = frozen_check_results
    return session


def test_set_status_attribute_refuses_a_frozen_suite_owned_version():
    frozen_version_id = uuid4()
    session = _session_resolving_versions([frozen_version_id], frozen_check_results=[frozen_version_id])
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        with pytest.raises(FrozenVersionError):
            TestDefinition.set_status_attribute("flagged", [str(uuid4())], True)

    session.execute.assert_not_called()


def test_set_status_attribute_allows_a_placeholder_scoped_version():
    session = _session_resolving_versions([NIL_UUID], frozen_check_results=[None])
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.set_status_attribute("flagged", [str(uuid4())], True)

    session.execute.assert_called_once()


def test_set_status_attribute_refuses_when_any_version_in_the_batch_is_frozen_and_suite_owned():
    unfrozen_version_id = uuid4()
    frozen_version_id = uuid4()
    session = _session_resolving_versions(
        [unfrozen_version_id, frozen_version_id], frozen_check_results=[None, frozen_version_id]
    )
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        with pytest.raises(FrozenVersionError):
            TestDefinition.set_status_attribute("flagged", [str(uuid4()), str(uuid4())], True)

    session.execute.assert_not_called()


def test_save_of_a_term_the_draft_did_not_copy_is_refused():
    """A draft carries a copy of every term the version in force held, so a row on a frozen
    version that the draft has no copy of is one the draft already superseded. Rewriting it
    would resurrect a term the contract dropped.
    """
    frozen_version_id = uuid4()
    term = TestDefinition(id=uuid4(), version_id=frozen_version_id)
    with (
        patch(
            "testgen.common.models.test_definition.get_current_session",
            return_value=_session_returning(frozen_version_id),
        ),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=frozen_version_id)),
        patch.object(
            TestDefinition, "resolve_write_target",
            return_value=(uuid4(), {}),
        ),
    ):
        with pytest.raises(FrozenVersionError):
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
    with (
        patch(
            "testgen.common.models.test_definition.get_current_session",
            return_value=_session_returning(frozen_version_id),
        ),
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
    with (
        patch(
            "testgen.common.models.test_definition.get_current_session",
            return_value=_session_returning(frozen_version_id),
        ),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=frozen_version_id)),
        patch.object(
            TestDefinition, "resolve_write_target",
            return_value=(draft_version_id, {definition_id: copied_id}),
        ),
    ):
        definition.save()

    assert definition.version_id == draft_version_id
    assert definition.id == copied_id


def _session_routing_version_lookups(*, persisted_version, frozen_versions=()):
    """A session answering the persisted-row lookup and the frozen check by what each asks.

    Answering both from one queue lets a guard that never issued the persisted-row lookup
    read as guarded anyway, because the frozen check would consume the row's version.
    """
    def scalar(statement):
        froms = statement.get_final_froms()
        if getattr(froms[0], "name", None) == "test_definitions":
            return persisted_version
        for term in conjuncts(statement.whereclause):
            if not isinstance(term, BinaryExpression) or term.operator is not operators.eq:
                continue
            left = term.left
            if getattr(left, "key", None) == "id" and getattr(left.table, "name", None) == "suite_versions":
                value = getattr(term.right, "value", None)
                return value if value in frozen_versions else None
        return None

    session = MagicMock()
    session.scalar.side_effect = scalar
    return session


def test_an_update_whose_instance_carries_no_version_is_guarded_by_the_persisted_row():
    """The product's edit dialog rebuilds a definition from a summary payload, which carries
    no ``version_id``, so the instance holding one is not something the guard can assume. A
    guard that reads the instance passes every such edit, frozen term or not.
    """
    frozen_version_id = uuid4()
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = None

    session = _session_routing_version_lookups(
        persisted_version=frozen_version_id, frozen_versions=(frozen_version_id,)
    )
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=frozen_version_id)),
        patch.object(TestDefinition, "resolve_write_target", return_value=(uuid4(), {})),
    ):
        with pytest.raises(FrozenVersionError):
            definition.save()


def test_an_update_whose_persisted_row_is_on_a_draft_proceeds():
    draft_version_id = uuid4()
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = None

    session = _session_routing_version_lookups(persisted_version=draft_version_id)
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        definition.save()

    session.execute.assert_called_once()


def test_an_update_of_a_row_that_no_longer_exists_is_refused():
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = None

    session = _session_routing_version_lookups(persisted_version=None)
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        with pytest.raises(MissingTestDefinitionError):
            definition.save()

    session.execute.assert_not_called()


def test_the_update_narrows_by_the_rows_resolved_version():
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = uuid4()

    session = MagicMock()
    session.scalar.return_value = None
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        definition.save()

    statement = session.execute.call_args.args[0]
    assert scopes_to_a_version(statement)


def test_the_batch_guard_reads_the_rows_own_versions_not_the_suites():
    """The suite's resolved version is where its next write would land, which for a contract
    with an open draft is the draft — writable — no matter which version the ids belong to.
    Checking that instead of the rows' own version passes a batch aimed at frozen terms, and
    the UPDATE beneath it then matches nothing and reports success.
    """
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.set_status_attribute("flagged", [str(uuid4())], True)

    statement = session.scalars.call_args.args[0]
    selected = statement.selected_columns[0]
    assert selected.name == "version_id"
    assert selected.table.name == "test_definitions"


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
        persisted_version=superseded_version_id, frozen_versions=(superseded_version_id,)
    )
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=MagicMock(id=uuid4())),
        patch.object(TestDefinition, "resolve_write_target") as resolve,
    ):
        with pytest.raises(FrozenVersionError):
            definition.save()

    resolve.assert_not_called()
    session.execute.assert_not_called()


def test_a_contract_with_no_version_in_force_refuses_a_frozen_row_outright():
    frozen_version_id = uuid4()
    definition = TestDefinition()
    definition.id = uuid4()
    definition.test_suite_id = uuid4()
    definition.version_id = frozen_version_id

    session = _session_routing_version_lookups(
        persisted_version=frozen_version_id, frozen_versions=(frozen_version_id,)
    )
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(SuiteVersion, "in_force_for", return_value=None),
        patch.object(TestDefinition, "resolve_write_target") as resolve,
    ):
        with pytest.raises(FrozenVersionError):
            definition.save()

    resolve.assert_not_called()
