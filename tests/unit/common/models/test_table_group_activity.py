from unittest.mock import MagicMock, patch

import pytest

from testgen.common.models.table_group import TableGroup

pytestmark = pytest.mark.unit


def test_a_table_groups_last_test_counts_its_contracts_runs_but_not_their_previews():
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 1
    session.execute.return_value.mappings.return_value.all.return_value = []
    with patch("testgen.common.models.table_group.get_current_session", return_value=session):
        TableGroup.list_for_project("demo", page=1, limit=10)

    rows_query = " ".join(str(session.execute.call_args_list[-1].args[0]).split())
    assert "WHERE ts.suite_type IN ('regular', 'contract')" in rows_query
    assert "AND (tr.version_id IS NULL OR EXISTS (" in rows_query
    assert "AND (sv.test_suite_id IS NULL OR tr.test_starttime >= sv.frozen_at) )) GROUP BY ts.table_groups_id" in (
        rows_query
    )
