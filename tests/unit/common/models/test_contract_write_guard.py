from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.suite_version import FrozenVersionError
from testgen.common.models.test_definition import TestDefinition
from tests.unit.sql_assertions import conjuncts, is_not_null_conjunct

pytestmark = pytest.mark.unit

NIL_UUID = "00000000-0000-0000-0000-000000000000"


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
    term = TestDefinition(test_suite_id=uuid4())
    session = MagicMock()
    # The version a new definition resolves to, then the routing check, which finds it frozen.
    session.scalar.side_effect = [frozen_version_id, frozen_version_id]
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.entity.get_current_session", return_value=session),
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
            TestDefinition.move([str(uuid4())], uuid4(), uuid4())

    session.execute.assert_not_called()


def test_copy_refuses_a_frozen_suite_owned_target_version():
    frozen_version_id = uuid4()
    session = MagicMock()
    session.scalar.side_effect = [frozen_version_id, frozen_version_id]
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        with pytest.raises(FrozenVersionError):
            TestDefinition.copy([str(uuid4())], uuid4(), uuid4())

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
        patch.object(
            TestDefinition, "resolve_write_target",
            return_value=(draft_version_id, {definition.id: copied_id}),
        ),
    ):
        definition.save()

    assert definition.version_id == draft_version_id
    assert definition.id == copied_id
