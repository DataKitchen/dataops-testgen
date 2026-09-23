"""The SQL rendering of the version-resolution rule.

Raw SQL cannot use the ORM expression, so it interpolates this rendering. The rule must stay
defined once: what this renders has to be what the ORM applies.
"""

from uuid import uuid4

import pytest
from sqlalchemy import literal_column, select
from sqlalchemy.dialects import postgresql

from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition

pytestmark = pytest.mark.unit


def _compile(element) -> str:
    return " ".join(
        str(element.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split()
    )


def test_the_rendering_is_the_orm_expression():
    column = "td.test_suite_id"

    assert SuiteVersion.resolved_for_sql(column) == _compile(
        SuiteVersion.resolved_for(literal_column(column))
    )


def test_the_rendering_carries_the_whole_rule():
    rendered = SuiteVersion.resolved_for_sql("td.test_suite_id")

    assert rendered.count("SELECT suite_versions.id") == 3, "draft, highest frozen, placeholder"
    assert "frozen_at IS NULL" in rendered
    assert "ORDER BY suite_versions.version DESC LIMIT 1" in rendered
    assert "test_suite_id IS NULL" in rendered


def test_the_rendering_names_no_placeholder_literal():
    assert "00000000-0000-0000-0000-000000000000" not in SuiteVersion.resolved_for_sql("td.test_suite_id")



def test_a_predicate_built_from_the_rendering_matches_the_orm_one():
    ormsql = _compile(select(TestDefinition.id).where(TestDefinition.version_clause()))
    rendered = (
        "SELECT test_definitions.id FROM test_definitions WHERE test_definitions.version_id = "
        + SuiteVersion.resolved_for_sql("test_definitions.test_suite_id")
    )

    assert ormsql == rendered


@pytest.mark.parametrize(
    "supplied",
    ["td.test_suite_id; DROP TABLE test_definitions", "(SELECT 1)", "", "td.suite id", "'x'"],
)
def test_the_rendering_rejects_anything_but_a_column_reference(supplied):
    with pytest.raises(ValueError):
        SuiteVersion.resolved_for_sql(supplied)


@pytest.mark.parametrize("supplied", ["test_suite_id", "suite_id"])
def test_the_rendering_rejects_an_unqualified_column(supplied):
    """Unqualified, the name binds to suite_versions inside the subqueries rather than to the
    outer row, which makes the correlation a tautology and silently resolves every suite to
    whichever draft the database happens to hold."""
    with pytest.raises(ValueError):
        SuiteVersion.resolved_for_sql(supplied)


@pytest.mark.parametrize(
    "supplied", ["suite_versions.test_suite_id", "SUITE_VERSIONS.test_suite_id"]
)
def test_the_rendering_rejects_the_inner_table_as_the_qualifier(supplied):
    """An outer relation aliased suite_versions is shadowed by the subqueries' own, with the same
    silent result as leaving the column unqualified."""
    with pytest.raises(ValueError):
        SuiteVersion.resolved_for_sql(supplied)


@pytest.mark.parametrize(
    "supplied", ["td.test_suite_id", "t_1.test_suite_id", "tg.monitor_test_suite_id"]
)
def test_the_rendering_accepts_a_qualified_column_reference(supplied):
    assert SuiteVersion.resolved_for_sql(supplied).startswith("coalesce(")


def test_the_rendering_correlates_to_the_outer_column():
    """Each of the three subqueries compares suite_versions' own column to the outer one."""
    rendered = SuiteVersion.resolved_for_sql("td.test_suite_id")

    assert rendered.count("suite_versions.test_suite_id = td.test_suite_id") == 2
    assert rendered.count("suite_versions.test_suite_id IS NULL") == 1, "the placeholder branch"


def test_the_rendering_does_not_depend_on_the_column_name():
    first = SuiteVersion.resolved_for_sql("a.test_suite_id")
    second = SuiteVersion.resolved_for_sql("b.test_suite_id")

    assert first != second
    assert first.replace("a.", "").replace(str(uuid4()), "") == second.replace("b.", "").replace(str(uuid4()), "")
