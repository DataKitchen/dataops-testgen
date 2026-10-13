import re
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.table_group import TableGroup

pytestmark = pytest.mark.unit

MODULE = "testgen.common.models.table_group"


def _executed_sql(call_listing) -> list[str]:
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 1
    session.execute.return_value.mappings.return_value.all.return_value = []
    with patch(f"{MODULE}.get_current_session", return_value=session):
        call_listing()
    return [str(executed.args[0]) for executed in session.execute.call_args_list]


@pytest.mark.parametrize("call_listing", [
    lambda: TableGroup.select_stats("DEFAULT"),
    lambda: TableGroup.select_summary("DEFAULT", str(uuid4())),
    lambda: TableGroup.list_for_project("DEFAULT"),
], ids=["select_stats", "select_summary", "list_for_project"])
def test_catalog_counts_leave_out_dropped_tables(call_listing):
    """A table marked dropped stays in the catalog, but it is no longer one of the group's tables."""
    reads = [
        match.group(0)
        for sql in _executed_sql(call_listing)
        for match in re.finditer(r"FROM data_table_chars\b.*?GROUP BY", sql, re.S)
    ]

    assert reads
    assert all("drop_date IS NULL" in read for read in reads)
