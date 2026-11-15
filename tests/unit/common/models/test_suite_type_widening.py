"""The suite-type filter on read methods: STANDARD by default, widened only when asked."""

from collections.abc import Callable
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.enums import SuiteType
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_result import TestResult
from testgen.common.models.test_run import TestRun
from testgen.common.models.test_suite import TestSuite

pytestmark = pytest.mark.unit

BOTH = (SuiteType.STANDARD, SuiteType.CONTRACT)
RUN_IDS = (uuid4(), uuid4())


@pytest.fixture
def session_mock():
    with (
        patch("testgen.common.models.test_definition.get_current_session") as td_mock,
        patch("testgen.common.models.test_result.get_current_session") as tr_mock,
        patch("testgen.common.models.test_suite.get_current_session") as ts_mock,
        patch("testgen.common.models.test_run.get_current_session") as run_mock,
        patch("testgen.common.models.entity.get_current_session") as entity_mock,
    ):
        session = td_mock.return_value
        for other in (tr_mock, ts_mock, run_mock, entity_mock):
            other.return_value = session
        session.scalar.return_value = 0
        yield session


def _compiled(statement) -> str:
    return " ".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split()
    )


def _statements(session) -> list:
    calls = (*session.execute.call_args_list, *session.scalars.call_args_list, *session.scalar.call_args_list)
    return [call.args[0] for call in calls]


ORM_READS: list[Callable] = [
    lambda **kw: TestDefinition.get_for_project(uuid4(), ["demo"], **kw),
    lambda **kw: TestDefinition.list_for_suite(uuid4(), ["demo"], **kw),
    lambda **kw: TestDefinition.list_for_ids([uuid4()], ["demo"], **kw),
    lambda **kw: TestResult.select_results(uuid4(), **kw),
    lambda **kw: TestResult.list_for_run(uuid4(), **kw),
    lambda **kw: TestResult.select_failures(test_run_id=uuid4(), **kw),
    lambda **kw: TestResult.select_history(uuid4(), **kw),
    lambda **kw: TestResult.search_results(**kw),
    lambda **kw: TestResult.failure_trend(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2), **kw),
    lambda **kw: TestSuite.list_for_project("demo", **kw),
]


def _suite_type_sql(session, call, **kwargs) -> str:
    session.reset_mock()
    session.scalar.return_value = 0
    session.execute.return_value.mappings.return_value.first.return_value = None
    session.execute.return_value.mappings.return_value.all.return_value = []
    session.execute.return_value.all.return_value = []
    session.execute.return_value.__iter__.return_value = iter([])
    call(**kwargs)
    return "\n".join(_compiled(statement) for statement in _statements(session))


@pytest.mark.parametrize("call", ORM_READS)
def test_orm_reads_default_to_regular(session_mock, call):
    sql = _suite_type_sql(session_mock, call)
    assert "test_suites.suite_type IN ('standard')" in sql
    assert "'contract'" not in sql


@pytest.mark.parametrize("call", ORM_READS)
def test_orm_reads_widen_on_request(session_mock, call):
    sql = _suite_type_sql(session_mock, call, suite_types=BOTH)
    assert "test_suites.suite_type IN ('standard', 'contract')" in sql


def test_suite_summary_defaults_to_regular(session_mock):
    TestSuite.select_summary("demo")
    assert session_mock.execute.call_args.args[1]["suite_types"] == ("standard",)


def test_suite_summary_widens_on_request_and_selects_the_type(session_mock):
    TestSuite.select_summary("demo", suite_types=BOTH)
    sql = str(session_mock.execute.call_args.args[0])
    assert session_mock.execute.call_args.args[1]["suite_types"] == ("standard", "contract")
    assert "suites.suite_type IN :suite_types" in sql
    assert "suites.suite_type," in sql


def _run_summary_sql(**kwargs) -> str:
    with patch.object(TestRun, "_paginate", return_value=([], 0)) as paginate:
        TestRun.select_summary(**kwargs)
    return _compiled(paginate.call_args.args[0])


def test_run_summary_defaults_to_regular_and_keeps_pending_runs():
    sql = _run_summary_sql(project_code="demo")
    assert "(test_suites.suite_type IN ('standard') OR test_suites.id IS NULL)" in sql


def test_run_summary_widens_on_request():
    sql = _run_summary_sql(project_code="demo", suite_types=BOTH)
    assert "test_suites.suite_type IN ('standard', 'contract')" in sql


def test_run_summary_can_narrow_to_one_version_and_selects_version_columns():
    version_id = uuid4()
    sql = _run_summary_sql(test_suite_id=str(uuid4()), version_id=version_id)
    assert f"test_runs.version_id = '{version_id}'" in sql
    assert "suite_versions_1.version AS version_number" in sql
    assert (
        "LEFT OUTER JOIN suite_versions AS suite_versions_1 ON suite_versions_1.id = test_runs.version_id"
        " AND suite_versions_1.test_suite_id IS NOT NULL"
    ) in sql


@pytest.mark.parametrize(
    ("kwargs", "results_filter"),
    [
        ({"test_run_ids": [RUN_IDS[0], RUN_IDS[1]]}, f"WHERE test_results.test_run_id IN ('{RUN_IDS[0]}', '{RUN_IDS[1]}') GROUP BY"),
        ({"job_execution_id": RUN_IDS[0]}, f"WHERE test_results.test_run_id = '{RUN_IDS[0]}' GROUP BY"),
        ({"project_code": "demo"}, "FROM test_results GROUP BY"),
    ],
    ids=["by-run-ids", "by-job", "unfiltered"],
)
def test_run_summary_counts_only_the_runs_it_reads(kwargs, results_filter):
    assert results_filter in _run_summary_sql(**kwargs)


def test_run_summary_without_a_version_does_not_narrow():
    assert "test_runs.version_id =" not in _run_summary_sql(project_code="demo")


def test_get_for_project_reads_any_version_of_a_contract_only_when_contracts_are_requested(session_mock):
    widened = _suite_type_sql(
        session_mock, lambda **kw: TestDefinition.get_for_project(uuid4(), ["demo"], **kw), suite_types=BOTH
    )
    assert "OR test_suites.suite_type = 'contract'" in widened


def test_list_for_suite_with_a_version_reads_that_version_instead_of_the_resolved_one(session_mock):
    version_id = uuid4()
    with patch.object(TestDefinition, "_paginate", return_value=([], 0)) as paginate:
        TestDefinition.list_for_suite(uuid4(), version_id=version_id, suite_types=BOTH)
    sql = _compiled(paginate.call_args.args[0])
    assert f"test_definitions.version_id = '{version_id}'" in sql
    assert "coalesce" not in sql.lower()


def test_list_for_suite_without_a_version_keeps_the_resolved_version_predicate(session_mock):
    with patch.object(TestDefinition, "_paginate", return_value=([], 0)) as paginate:
        TestDefinition.list_for_suite(uuid4())
    assert "coalesce" in _compiled(paginate.call_args.args[0]).lower()


def test_list_for_ids_reads_any_version_of_a_contract_only_when_contracts_are_requested(session_mock):
    widened = _suite_type_sql(
        session_mock, lambda **kw: TestDefinition.list_for_ids([uuid4()], ["demo"], **kw), suite_types=BOTH
    )
    assert "OR test_suites.suite_type = 'contract'" in widened


def test_any_contract_version_clause_is_none_when_contracts_are_not_requested():
    assert TestDefinition.any_contract_version_clause((SuiteType.STANDARD,)) is None


def test_any_contract_version_clause_reads_a_contract_in_any_version():
    sql = _compiled(TestDefinition.any_contract_version_clause(BOTH))
    assert sql.endswith("OR test_suites.suite_type = 'contract'")
    assert "test_definitions.version_id" in sql
