from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.custom_types import NullIfEmptyString
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_run import TestRun
from testgen.utils import is_uuid4
from tests.unit.sql_assertions import conjuncts, is_not_null_conjunct, is_null_conjunct

pytestmark = pytest.mark.unit

NIL_UUID = "00000000-0000-0000-0000-000000000000"


def test_maps_to_the_suite_versions_table():
    assert SuiteVersion.__tablename__ == "suite_versions"


def test_the_columns_the_placeholder_leaves_empty_are_nullable():
    for name in (
        "test_suite_id", "metadata_document", "frozen_document",
        "frozen_at", "odcs_api_version", "label", "created_by",
    ):
        assert SuiteVersion.__table__.c[name].nullable is True, name


def test_the_columns_every_row_must_carry_are_not_null():
    for name in ("id", "version", "created_at", "updated_at"):
        assert SuiteVersion.__table__.c[name].nullable is False, name


def test_metadata_document_stores_python_none_as_sql_null():
    # Plain JSONB writes a Python None as JSON `null`, which would make
    # `metadata_document IS NULL` false for the placeholder — the row would read as a
    # contract version holding an empty document, which is the one thing it is not.
    assert SuiteVersion.__table__.c.metadata_document.type.none_as_null is True


def test_label_stores_an_empty_string_as_null():
    assert isinstance(SuiteVersion.__table__.c.label.type, NullIfEmptyString)


def test_deleting_a_suite_cascades_to_its_versions():
    foreign_key, = SuiteVersion.__table__.c.test_suite_id.foreign_keys
    assert foreign_key.ondelete == "CASCADE"


def test_timestamps_are_timezone_aware_and_default_at_the_database():
    for name in ("created_at", "updated_at"):
        column = SuiteVersion.__table__.c[name]
        assert isinstance(column.type, postgresql.TIMESTAMP)
        assert column.type.timezone is True
        assert "NOW()" in str(column.server_default.arg)


def test_test_run_carries_a_nullable_version_id():
    # A soft link, deliberately without a foreign key, so a run's record outlives a
    # discarded version.
    assert TestRun.__table__.c.version_id.nullable is True
    assert not TestRun.__table__.c.version_id.foreign_keys


def test_the_base_guard_would_reject_the_nil_uuid_as_a_string():
    # This is why get() is overridden. If is_uuid4 is ever widened to accept any UUID,
    # this test fails and the override can be deleted.
    assert is_uuid4(NIL_UUID) is False
    assert is_uuid4(UUID(NIL_UUID)) is True


@patch("testgen.common.models.entity.get_current_session")
def test_get_queries_for_the_placeholder_given_its_string_id(mock_session):
    SuiteVersion.get(NIL_UUID)

    # Without the override, Entity.get returns None without ever touching the session.
    mock_session.return_value.scalars.assert_called_once()


@patch("testgen.common.models.entity.get_current_session")
def test_get_treats_the_string_and_uuid_forms_alike(mock_session):
    SuiteVersion.get(NIL_UUID)
    SuiteVersion.get(UUID(NIL_UUID))

    assert mock_session.return_value.scalars.call_count == 2


@patch("testgen.common.models.entity.get_current_session")
def test_get_still_queries_for_an_ordinary_version_4_id(mock_session):
    SuiteVersion.get(uuid4())

    mock_session.return_value.scalars.assert_called_once()


@patch("testgen.common.models.entity.get_current_session")
def test_get_returns_none_without_querying_for_a_non_uuid(mock_session):
    assert SuiteVersion.get("not-a-uuid") is None

    mock_session.assert_not_called()


def _compiled(expression) -> str:
    return " ".join(
        str(expression.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split()
    )


def test_resolved_for_prefers_the_draft_then_the_highest_frozen_then_the_placeholder():
    sql = _compiled(SuiteVersion.resolved_for(TestDefinition.test_suite_id))

    assert sql.count("FROM suite_versions") == 3
    assert "frozen_at IS NULL" in sql
    assert "ORDER BY suite_versions.version DESC" in sql
    assert "suite_versions.test_suite_id IS NULL" in sql
    assert sql.index("frozen_at IS NULL") < sql.index("ORDER BY suite_versions.version DESC")


def test_resolved_for_finds_the_placeholder_by_shape_not_by_id():
    sql = _compiled(SuiteVersion.resolved_for(TestDefinition.test_suite_id))

    assert NIL_UUID not in sql


def test_resolved_for_correlates_on_the_given_suite_expression():
    sql = _compiled(SuiteVersion.resolved_for(TestDefinition.test_suite_id))

    assert "test_definitions.test_suite_id" in sql


def test_resolved_for_accepts_a_literal_suite_id():
    suite_id = uuid4()

    sql = _compiled(SuiteVersion.resolved_for(suite_id))

    assert str(suite_id) in sql


def test_the_working_copy_resolver_prefers_the_draft():
    sql = _compiled(SuiteVersion.resolved_for(uuid4()))
    assert sql.count("SELECT") == 3
    assert "frozen_at IS NULL" in sql


def test_the_published_resolver_ignores_the_draft():
    sql = _compiled(SuiteVersion.active_for(uuid4()))
    assert "frozen_at IS NULL" not in sql
    assert sql.count("SELECT") == 2


def test_both_resolvers_require_the_highest_version_to_be_frozen():
    for expression in (SuiteVersion.resolved_for(uuid4()), SuiteVersion.active_for(uuid4())):
        assert "frozen_at IS NOT NULL" in _compiled(expression)


def test_both_resolvers_fall_back_to_the_placeholder():
    for expression in (SuiteVersion.resolved_for(uuid4()), SuiteVersion.active_for(uuid4())):
        assert "test_suite_id IS NULL" in _compiled(expression)


def test_the_published_sql_form_rejects_an_unqualified_column():
    with pytest.raises(ValueError, match="not a table-qualified column reference"):
        SuiteVersion.resolved_for_sql("test_suite_id")


def test_the_published_sql_form_rejects_its_own_table_as_the_qualifier():
    with pytest.raises(ValueError, match="shadowed"):
        SuiteVersion.resolved_for_sql("suite_versions.test_suite_id")


def test_the_published_sql_form_reads_the_outer_row():
    sql = SuiteVersion.resolved_for_sql("run.test_suite_id")
    assert "run.test_suite_id" in sql


def test_only_a_suite_owned_unfrozen_version_reads_as_a_draft():
    session = MagicMock()
    with patch("testgen.common.models.suite_version.get_current_session", return_value=session):
        session.scalar.return_value = uuid4()
        assert SuiteVersion.is_draft(uuid4()) is True

        session.scalar.return_value = None
        assert SuiteVersion.is_draft(uuid4()) is False


def test_a_run_with_no_version_does_not_read_as_a_draft():
    assert SuiteVersion.is_draft(None) is False


def _checks_suite_owned_and_unfrozen(statement) -> bool:
    """Whether the statement ANDs a suite-owned check with an unfrozen check, as separate terms.

    An OR-ed predicate, or one missing either half, does not qualify — each half must appear as
    its own conjunct so neither can be satisfied by the other.
    """
    terms = conjuncts(statement.whereclause)
    return any(is_not_null_conjunct(term, "test_suite_id", "suite_versions") for term in terms) and any(
        is_null_conjunct(term, "frozen_at", "suite_versions") for term in terms
    )


def test_the_draft_check_requires_both_halves_of_the_predicate():
    session = MagicMock()
    session.scalar.return_value = None
    with patch("testgen.common.models.suite_version.get_current_session", return_value=session):
        SuiteVersion.is_draft(uuid4())

    statement = session.scalar.call_args.args[0]
    assert _checks_suite_owned_and_unfrozen(statement)


def _lacks_draft_branch(statement) -> bool:
    """Whether the coalesce's branches include none selecting an unfrozen (draft) version.

    ``resolved_for`` has one such branch; ``active_for`` must not. A mocked session's return
    value can't tell the two resolvers apart, since both compile to a scalar subquery and
    either one can be told to return whatever id the test wants -- only the statement's own
    shape says which resolver built it.
    """
    coalesce_fn = statement.selected_columns[0]
    for branch in coalesce_fn.clauses:
        inner_where = branch.element.whereclause
        if any(is_null_conjunct(term, "frozen_at", "suite_versions") for term in conjuncts(inner_where)):
            return False
    return True


def test_is_active_compares_the_id_to_the_suite_agreement_in_force():
    session = MagicMock()
    suite_id = uuid4()
    version_id = uuid4()
    with patch("testgen.common.models.suite_version.get_current_session", return_value=session):
        session.scalar.return_value = version_id
        assert SuiteVersion.is_active(version_id, suite_id) is True

        session.scalar.return_value = uuid4()
        assert SuiteVersion.is_active(version_id, suite_id) is False

    statement = session.scalar.call_args.args[0]
    assert _lacks_draft_branch(statement)


def test_in_force_for_excludes_the_placeholder():
    placeholder = SuiteVersion(
        id=uuid4(), test_suite_id=None, version=1, frozen_at=datetime.now(UTC)
    )
    session = MagicMock()
    session.scalar.return_value = placeholder.id
    with (
        patch.object(SuiteVersion, "get", return_value=placeholder),
        patch("testgen.common.models.suite_version.get_current_session", return_value=session),
    ):
        assert SuiteVersion.in_force_for(uuid4()) is None


def test_open_draft_copies_the_document_forward_without_sharing_it():
    suite_id = uuid4()
    document = {"schema": [{"name": "orders"}]}
    frozen = SuiteVersion(
        id=uuid4(), test_suite_id=suite_id, version=1,
        frozen_at=datetime.now(UTC), metadata_document=document, odcs_api_version="v3.0.0",
    )
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "in_force_for", return_value=frozen),
        patch.object(SuiteVersion, "next_version_for", return_value=2),
        patch("testgen.common.models.suite_version.get_current_session", return_value=session),
    ):
        draft, source = SuiteVersion.open_draft(suite_id)

    assert source is frozen
    assert draft.metadata_document == document
    assert draft.metadata_document is not document
    assert draft.odcs_api_version == "v3.0.0"
    assert draft.frozen_at is None
    assert session.add.call_args.args[0] is draft


def test_open_draft_restates_the_carried_document_version_as_the_new_ones():
    # The document's own `version` is what a reader of the exported contract sees. Deep-copying
    # it forward unchanged would leave every version of the contract claiming to be the first.
    suite_id = uuid4()
    frozen = SuiteVersion(
        id=uuid4(), test_suite_id=suite_id, version=1,
        frozen_at=datetime.now(UTC), metadata_document={"version": "1.0.0", "schema": []},
    )
    with (
        patch.object(SuiteVersion, "in_force_for", return_value=frozen),
        patch.object(SuiteVersion, "next_version_for", return_value=2),
        patch("testgen.common.models.suite_version.get_current_session", return_value=MagicMock()),
    ):
        draft, _ = SuiteVersion.open_draft(suite_id)

    assert draft.metadata_document["version"] == "2.0.0"
    assert frozen.metadata_document["version"] == "1.0.0"


def test_open_draft_does_not_invent_a_version_field_in_a_document_that_has_none():
    suite_id = uuid4()
    frozen = SuiteVersion(
        id=uuid4(), test_suite_id=suite_id, version=1,
        frozen_at=datetime.now(UTC), metadata_document={"schema": []},
    )
    with (
        patch.object(SuiteVersion, "in_force_for", return_value=frozen),
        patch.object(SuiteVersion, "next_version_for", return_value=2),
        patch("testgen.common.models.suite_version.get_current_session", return_value=MagicMock()),
    ):
        draft, _ = SuiteVersion.open_draft(suite_id)

    assert "version" not in draft.metadata_document
