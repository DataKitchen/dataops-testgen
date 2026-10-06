"""Every read of test definitions carries the version predicate.

The candidate set is derived from the class rather than listed, so a read method added later
is either exercised here or named in ``EXEMPT_METHODS`` with a reason.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.test_definition import TestDefinition
from tests.unit.sql_assertions import emitted_statements, scopes_to_a_version

pytestmark = pytest.mark.unit

READ_METHOD_ARGS = {
    "get": (uuid4(),),
    "get_for_project": (uuid4(),),
    "select_where": (),
    "select_minimal_where": (),
    "list_for_suite": (uuid4(),),
    "list_for_ids": ([uuid4()],),
    "select_page": (),
    "get_singleton_monitor": (uuid4(), "a_table", "Volume_Trend"),
    "list_monitor_configs_for_table": (uuid4(), "a_table"),
    "get_source_data_context": (uuid4(),),
}

EXEMPT_METHODS = {
    "copy_to_version": (
        "reads the version its caller names rather than the one the suite resolves to; that "
        "predicate is asserted in test_test_definition_version_stamping.py"
    ),
    "resolve_write_target": (
        "a write — opens the draft a write lands on; it reads suite_versions, and the term "
        "copy it performs is exercised as copy_to_version"
    ),
    "assert_version_writable": "a guard — its own predicate is covered by test_contract_write_guard.py",
    "copy": "a write — version stamping is covered by test_test_definition_version_stamping.py",
    "move": "a write — version stamping is covered by test_test_definition_version_stamping.py",
    "save": "a write — version stamping is covered by test_test_definition_version_stamping.py",
    "set_status_attribute": "a write — its version predicate is covered by test_raw_sql_version_scoping.py",
    "editable_fields": "derives a field list from the test type; issues no statement",
    "validate": "checks fields already in memory; issues no statement",
    "version_clause": "builds the predicate the reads apply; issues no statement itself",
    "mint_term_id": (
        "takes no suite and reads no terms — its taken-check narrows by an explicit version_id, "
        "which is stricter than the resolved-version predicate rather than a bypass of it"
    ),
    "assign_missing_term_ids": (
        "narrows by an explicit version_id and refuses one no suite owns, so it never reaches "
        "past a single contract version"
    ),
}

# get_source_data_context is raw SQL. It guards on a scoped get() and then reads by primary key,
# so its own statement carries no version predicate.
UNSCOPED_STATEMENTS_ALLOWED = {"get_source_data_context"}


def _own_public_methods() -> set[str]:
    return {
        name
        for name, value in vars(TestDefinition).items()
        if not name.startswith("_") and callable(getattr(value, "__func__", value))
    }


def _session_mock() -> MagicMock:
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = None
    session.execute.return_value.mappings.return_value.all.return_value = []
    session.execute.return_value.scalars.return_value.first.return_value = None
    session.execute.return_value.scalar.return_value = 0
    session.execute.return_value.first.return_value = None
    return session


def _reads_test_definitions(statement) -> bool:
    rendered = str(statement).lower()
    return "test_definitions" in rendered and rendered.lstrip().startswith("select")


def test_every_read_method_is_exercised_or_exempt():
    undecided = sorted(_own_public_methods() - set(READ_METHOD_ARGS) - set(EXEMPT_METHODS))

    assert undecided == [], (
        "a method on TestDefinition is neither exercised by this module nor exempt. Add it to "
        "READ_METHOD_ARGS if it reads, or to EXEMPT_METHODS with a reason. Undecided: "
        + ", ".join(undecided)
    )


def test_no_stale_entries():
    own = _own_public_methods()
    stale = sorted((set(READ_METHOD_ARGS) | set(EXEMPT_METHODS)) - own)

    assert stale == [], "named here but no longer on TestDefinition: " + ", ".join(stale)


@pytest.mark.parametrize("method_name", sorted(READ_METHOD_ARGS))
def test_every_read_methodscopes_to_a_version(method_name):
    session = _session_mock()

    with (
        patch("testgen.common.models.entity.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
    ):
        getattr(TestDefinition, method_name)(*READ_METHOD_ARGS[method_name])

    statements = emitted_statements(session)

    assert any(scopes_to_a_version(statement) for statement in statements), (
        f"{method_name} issues no statement that ANDs the version column against a resolution"
    )

    if method_name not in UNSCOPED_STATEMENTS_ALLOWED:
        unscoped = [
            statement
            for statement in statements
            if _reads_test_definitions(statement) and not scopes_to_a_version(statement)
        ]
        assert unscoped == [], f"{method_name} also reads test definitions without the version"


def test_the_scoping_predicate_resolves_rather_than_naming_the_placeholder():
    session = _session_mock()

    with (
        patch("testgen.common.models.entity.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
    ):
        TestDefinition.select_where()

    rendered = " ".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in emitted_statements(session)
    )
    assert "00000000-0000-0000-0000-000000000000" not in rendered
