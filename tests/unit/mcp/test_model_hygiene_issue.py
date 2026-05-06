from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.hygiene_issue import (
    HygieneIssue,
    HygieneIssueDetail,
    HygieneIssueListRow,
    HygieneIssueSearchRow,
    HygieneIssueType,
)


@pytest.fixture
def session_mock():
    with (
        patch("testgen.common.models.hygiene_issue.get_current_session") as hi_mock,
        patch("testgen.common.models.entity.get_current_session") as entity_mock,
    ):
        entity_mock.return_value = hi_mock.return_value
        yield hi_mock.return_value


def _compiled_sql(captured_query, literal_binds: bool = False) -> str:
    compile_kwargs = {"literal_binds": True} if literal_binds else {}
    return str(captured_query.compile(dialect=postgresql.dialect(), compile_kwargs=compile_kwargs))


def _all_compiled_sql(session_mock) -> str:
    """Concatenate all queries seen by session.scalar + session.execute. ``_paginate`` issues
    both a count and a fetch; the WHERE/JOIN clauses live in both."""
    queries = [call[0][0] for call in session_mock.scalar.call_args_list]
    queries += [call[0][0] for call in session_mock.execute.call_args_list]
    return "\n".join(_compiled_sql(q) for q in queries)


def _list_row_mapping(**overrides):
    base = {
        "id": uuid4(),
        "project_code": "demo",
        "issue_type_name": "Non-Standard Blank Values",
        "schema_name": "demo",
        "table_name": "orders",
        "column_name": "frame_size",
        "impact_dimension": "Usability",
        "dq_dimension": "Completeness",
        "disposition": "Confirmed",
        "priority": "Definite",
        "detail": "…",
        "detail_redactable": False,
        "pii_flag": None,
    }
    base.update(overrides)
    return base


def _search_row_mapping(**overrides):
    base = _list_row_mapping()
    base.update({
        "table_groups_name": "default",
        "job_execution_id": uuid4(),
        "started_at": datetime(2026, 5, 1),
    })
    base.update(overrides)
    return base


def _detail_row_mapping(**overrides):
    base = _list_row_mapping()
    base.update({
        "type_description": "type description",
        "suggested_action": "suggested action",
        "job_execution_id": uuid4(),
        "started_at": datetime(2026, 5, 1),
        "column_general_type": "A",
        "column_db_data_type": "varchar(50)",
        "column_record_ct": 100,
        "column_null_value_ct": 5,
        "column_distinct_value_ct": 50,
    })
    base.update(overrides)
    return base


def _stub_paginate(session_mock, *, total=0, rows=()):
    session_mock.scalar.return_value = total
    session_mock.execute.return_value.mappings.return_value.all.return_value = list(rows)


# ---------------------------------------------------------------------------
# HygieneIssue.list_for_run
# ---------------------------------------------------------------------------


def test_list_for_run_filters_by_je_id_not_run_pk(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.list_for_run(uuid4())

    sql = _all_compiled_sql(session_mock)
    assert "profiling_runs.job_execution_id =" in sql
    # The legacy run PK must NOT be the filter:
    assert "profile_anomaly_results.profile_run_id =" not in sql


def test_list_for_run_joins_profile_anomaly_types_inner(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.list_for_run(uuid4())

    sql = _all_compiled_sql(session_mock)
    assert "JOIN profile_anomaly_types" in sql


def test_list_for_run_joins_profile_results_outer(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.list_for_run(uuid4())

    sql = _all_compiled_sql(session_mock)
    assert "LEFT OUTER JOIN profile_results" in sql
    # Composite join condition guards against profile-result drift:
    assert "profile_results.schema_name = profile_anomaly_results.schema_name" in sql
    assert "profile_results.table_name = profile_anomaly_results.table_name" in sql
    assert "profile_results.column_name = profile_anomaly_results.column_name" in sql


def test_list_for_run_orders_by_priority_then_table_then_column_then_id(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.list_for_run(uuid4())

    sql = _all_compiled_sql(session_mock)
    # Priority CASE comes first; cls.id last for stable pagination.
    assert "CASE" in sql
    assert "ORDER BY" in sql
    assert "profile_anomaly_results.table_name" in sql
    assert "profile_anomaly_results.column_name" in sql
    assert "profile_anomaly_results.id" in sql


def test_list_for_run_caller_clauses_appended_to_where(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.list_for_run(
        uuid4(),
        HygieneIssue.table_name == "orders",
        HygieneIssue.project_code.in_(["demo"]),
    )

    sql = _all_compiled_sql(session_mock)
    assert "profile_anomaly_results.table_name =" in sql
    assert "profile_anomaly_results.project_code IN" in sql


def test_list_for_run_coalesces_disposition(session_mock):
    """The SELECT list coalesces disposition so NULL rows render as the default."""
    _stub_paginate(session_mock)

    HygieneIssue.list_for_run(uuid4())

    sql = _all_compiled_sql(session_mock)
    assert "coalesce(profile_anomaly_results.disposition" in sql


def test_list_for_run_returns_paginated_tuple(session_mock):
    rows = [_list_row_mapping(), _list_row_mapping()]
    _stub_paginate(session_mock, total=42, rows=rows)

    result_rows, total = HygieneIssue.list_for_run(uuid4())

    assert total == 42
    assert len(result_rows) == 2
    assert all(isinstance(r, HygieneIssueListRow) for r in result_rows)


# ---------------------------------------------------------------------------
# HygieneIssue.search
# ---------------------------------------------------------------------------


def test_search_joins_table_group_inner(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.search()

    sql = _all_compiled_sql(session_mock)
    assert "JOIN table_groups" in sql


def test_search_joins_job_execution_outer(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.search()

    sql = _all_compiled_sql(session_mock)
    assert "LEFT OUTER JOIN job_executions" in sql


def test_search_joins_profile_results_outer(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.search()

    sql = _all_compiled_sql(session_mock)
    assert "LEFT OUTER JOIN profile_results" in sql


def test_search_orders_by_started_at_desc_then_priority_then_id(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.search()

    sql = _all_compiled_sql(session_mock)
    assert "ORDER BY" in sql
    assert "job_executions.started_at DESC" in sql
    assert "profile_anomaly_results.id" in sql


def test_search_caller_clauses_propagate(session_mock):
    _stub_paginate(session_mock)

    HygieneIssue.search(
        HygieneIssue.project_code.in_(["demo"]),
        HygieneIssue.table_name == "orders",
    )

    sql = _all_compiled_sql(session_mock)
    assert "profile_anomaly_results.project_code IN" in sql
    assert "profile_anomaly_results.table_name =" in sql


def test_search_returns_paginated_tuple(session_mock):
    rows = [_search_row_mapping()]
    _stub_paginate(session_mock, total=7, rows=rows)

    result_rows, total = HygieneIssue.search()

    assert total == 7
    assert len(result_rows) == 1
    assert isinstance(result_rows[0], HygieneIssueSearchRow)


# ---------------------------------------------------------------------------
# HygieneIssue.get_with_context
# ---------------------------------------------------------------------------


def test_get_with_context_filters_by_id_and_extra_clauses(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = None

    HygieneIssue.get_with_context(uuid4(), HygieneIssue.project_code.in_(["demo"]))

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "profile_anomaly_results.id =" in sql
    assert "profile_anomaly_results.project_code IN" in sql


def test_get_with_context_outer_joins_profile_results(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = None

    HygieneIssue.get_with_context(uuid4())

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "LEFT OUTER JOIN profile_results" in sql


def test_get_with_context_outer_joins_job_execution(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = None

    HygieneIssue.get_with_context(uuid4())

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "LEFT OUTER JOIN job_executions" in sql


def test_get_with_context_returns_none_when_no_row(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = None

    result = HygieneIssue.get_with_context(uuid4())

    assert result is None


def test_get_with_context_returns_dataclass_when_row_present(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = _detail_row_mapping()

    result = HygieneIssue.get_with_context(uuid4())

    assert isinstance(result, HygieneIssueDetail)
    assert result.issue_type_name == "Non-Standard Blank Values"


# ---------------------------------------------------------------------------
# HygieneIssue.update_disposition
# ---------------------------------------------------------------------------


def test_update_disposition_compiles_to_update_with_id_and_clauses(session_mock):
    session_mock.execute.return_value.rowcount = 1

    HygieneIssue.update_disposition(
        uuid4(),
        "Dismissed",
        HygieneIssue.project_code.in_(["demo"]),
    )

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "UPDATE profile_anomaly_results" in sql
    assert "SET disposition" in sql
    assert "profile_anomaly_results.id =" in sql
    # Project-scope clause must be in the WHERE — write-side authorization.
    assert "profile_anomaly_results.project_code IN" in sql


def test_update_disposition_returns_true_when_rowcount_positive(session_mock):
    session_mock.execute.return_value.rowcount = 1

    assert HygieneIssue.update_disposition(uuid4(), "Dismissed") is True


def test_update_disposition_returns_false_when_rowcount_zero(session_mock):
    session_mock.execute.return_value.rowcount = 0

    assert HygieneIssue.update_disposition(uuid4(), "Dismissed") is False


# ---------------------------------------------------------------------------
# HygieneIssueType.select_where
# ---------------------------------------------------------------------------


def test_hygiene_issue_type_select_where_no_clauses_returns_all(session_mock):
    session_mock.scalars.return_value = [MagicMock(), MagicMock()]

    result = HygieneIssueType.select_where()

    assert len(result) == 2
    sql = _compiled_sql(session_mock.scalars.call_args[0][0])
    assert "SELECT" in sql.upper()
    assert "profile_anomaly_types" in sql


def test_hygiene_issue_type_select_where_with_order_by(session_mock):
    session_mock.scalars.return_value = []

    HygieneIssueType.select_where(order_by=(HygieneIssueType.name,))

    sql = _compiled_sql(session_mock.scalars.call_args[0][0])
    assert "ORDER BY profile_anomaly_types.anomaly_name" in sql


def test_hygiene_issue_type_select_where_filter_clause(session_mock):
    session_mock.scalars.return_value = []

    HygieneIssueType.select_where(HygieneIssueType.name == "Some Type")

    sql = _compiled_sql(session_mock.scalars.call_args[0][0])
    assert "profile_anomaly_types.anomaly_name =" in sql
