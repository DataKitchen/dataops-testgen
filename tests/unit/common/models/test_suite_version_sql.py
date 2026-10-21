"""The SQL rendering of the version-resolution rule.

Raw SQL cannot use the ORM expression, so it interpolates this rendering. The rule must stay
defined once: what this renders has to be what the ORM applies.
"""

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import literal_column, select
from sqlalchemy.dialects import postgresql

from testgen.common.enums import JobStatus
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.suite_version import SuiteVersion, SuiteVersionListItem, VersionState
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_run import RunVersion, TestRun

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


@pytest.fixture
def session_mock():
    with (
        patch("testgen.common.models.suite_version.get_current_session") as suite_version_session,
        patch("testgen.common.models.test_run.get_current_session", new=suite_version_session),
    ):
        yield suite_version_session.return_value


def test_list_for_suite_orders_newest_first_and_counts_per_version():
    with patch.object(SuiteVersion, "_paginate", return_value=([], 0)) as paginate:
        SuiteVersion.list_for_suite(uuid4(), page=1, limit=20)
    sql = _compile(paginate.call_args.args[0])
    assert "ORDER BY suite_versions.version DESC" in sql
    assert "test_definitions.version_id = suite_versions.id" in sql
    assert "test_runs.version_id = suite_versions.id" in sql


def test_list_for_suite_names_who_froze_each_version():
    with patch.object(SuiteVersion, "_paginate", return_value=([], 0)) as paginate:
        SuiteVersion.list_for_suite(uuid4(), page=1, limit=20)
    assert "suite_versions.frozen_by" in _compile(paginate.call_args.args[0])
    assert "frozen_by" in SuiteVersionListItem.__dataclass_fields__


def test_list_for_suite_term_count_leaves_out_the_managed_test_types():
    with patch.object(SuiteVersion, "_paginate", return_value=([], 0)) as paginate:
        SuiteVersion.list_for_suite(uuid4(), page=1, limit=20)
    sql = _compile(paginate.call_args.args[0])
    assert "test_definitions.test_type NOT IN ('Schema_Conformance')" in sql


def test_list_for_suite_narrows_both_run_subqueries_to_the_suite():
    suite_id = uuid4()
    with patch.object(SuiteVersion, "_paginate", return_value=([], 0)) as paginate:
        SuiteVersion.list_for_suite(suite_id, page=1, limit=20)
    sql = _compile(paginate.call_args.args[0])
    assert sql.count(f"test_runs.test_suite_id = '{suite_id}'") == 2


def test_list_for_suite_latest_run_is_the_most_recent_of_that_version():
    with patch.object(SuiteVersion, "_paginate", return_value=([], 0)) as paginate:
        SuiteVersion.list_for_suite(uuid4(), page=1, limit=20)
    sql = _compile(paginate.call_args.args[0])
    assert "ORDER BY test_runs.test_starttime DESC" in sql
    assert "LIMIT 1" in sql


def test_states_for_reads_every_suite_in_one_query(session_mock):
    session_mock.scalars.return_value.all.return_value = []
    assert SuiteVersion.states_for([uuid4()]) == {}
    assert session_mock.scalars.call_count == 1
    sql = _compile(session_mock.scalars.call_args.args[0])
    assert "suite_versions.test_suite_id IN" in sql


def test_states_for_picks_the_draft_and_the_highest_frozen_version(session_mock):
    suite_id = uuid4()
    v2 = SuiteVersion(id=uuid4(), test_suite_id=suite_id, version=2, frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
    v3 = SuiteVersion(id=uuid4(), test_suite_id=suite_id, version=3, frozen_at=datetime(2026, 2, 1, tzinfo=UTC))
    v4 = SuiteVersion(id=uuid4(), test_suite_id=suite_id, version=4)
    session_mock.scalars.return_value.all.return_value = [v2, v3, v4]
    state = SuiteVersion.states_for([suite_id])[suite_id]
    assert state.active is v3
    assert state.draft is v4


def test_latest_verification_excludes_runs_started_before_the_freeze(session_mock):
    version = SuiteVersion(id=uuid4(), version=3, frozen_at=datetime(2026, 9, 12, tzinfo=UTC))
    TestRun.latest_verification(version)
    sql = _compile(session_mock.scalars.call_args.args[0])
    assert "test_runs.test_starttime >= '2026-09-12" in sql
    assert f"test_runs.version_id = '{version.id}'" in sql
    assert "ORDER BY test_runs.test_starttime DESC" in sql


def test_latest_verification_narrows_to_the_versions_suite(session_mock):
    version = SuiteVersion(
        id=uuid4(), test_suite_id=uuid4(), version=3, frozen_at=datetime(2026, 9, 12, tzinfo=UTC)
    )
    TestRun.latest_verification(version)
    sql = _compile(session_mock.scalars.call_args.args[0])
    assert f"test_runs.test_suite_id = '{version.test_suite_id}'" in sql


def test_latest_verification_narrows_by_the_clauses_given(session_mock):
    version = SuiteVersion(
        id=uuid4(), test_suite_id=uuid4(), version=3, frozen_at=datetime(2026, 9, 12, tzinfo=UTC)
    )
    TestRun.latest_verification(version, JobExecution.status == JobStatus.COMPLETED)
    sql = _compile(session_mock.scalars.call_args.args[0])
    assert "JOIN job_executions ON test_runs.id = job_executions.id" in sql
    assert "job_executions.status = 'completed'" in sql


def test_latest_verification_of_a_draft_is_none_without_a_query(session_mock):
    assert TestRun.latest_verification(SuiteVersion(id=uuid4(), version=4)) is None
    session_mock.scalars.assert_not_called()


@pytest.mark.parametrize(
    ("frozen_at", "active_number", "started", "in_force", "state", "preview", "counts"),
    [
        (datetime(2026, 9, 12, tzinfo=UTC), 3, datetime(2026, 9, 13), 3, VersionState.ACTIVE, False, True),
        (datetime(2026, 9, 12, tzinfo=UTC), 4, datetime(2026, 9, 13), 3, VersionState.SUPERSEDED, False, True),
        (datetime(2026, 9, 12, tzinfo=UTC), 4, datetime(2026, 9, 20), 4, VersionState.SUPERSEDED, False, False),
        (datetime(2026, 9, 12, tzinfo=UTC), 3, datetime(2026, 9, 11), 2, VersionState.ACTIVE, True, False),
        (None, 2, datetime(2026, 9, 13), 2, VersionState.DRAFT, True, False),
    ],
    ids=["verification", "verification-since-superseded", "check-of-a-superseded-version", "preview-frozen-since",
         "draft"],
)
def test_a_completed_run_counts_when_it_verified_the_version_in_force_as_it_started(
    frozen_at, active_number, started, in_force, state, preview, counts
):
    run_version = RunVersion(3, frozen_at, active_number, started, in_force, JobStatus.COMPLETED)
    assert (run_version.state, run_version.is_preview, run_version.counts_as_status) == (state, preview, counts)


@pytest.mark.parametrize(
    "status", [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.CANCELED, JobStatus.ERROR, None]
)
def test_a_run_that_has_not_completed_does_not_count(status):
    run_version = RunVersion(3, datetime(2026, 9, 12, tzinfo=UTC), 3, datetime(2026, 9, 13), 3, status)
    assert run_version.checked_version_in_force is True
    assert run_version.counts_as_status is False
