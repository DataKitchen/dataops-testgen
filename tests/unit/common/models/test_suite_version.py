from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.custom_types import NullIfEmptyString
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_run import TestRun
from testgen.utils import is_uuid4

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
    return str(
        expression.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
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
