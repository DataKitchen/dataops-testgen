"""``DataTable.list_column_chars`` reads back every catalog field column profiling uses.

A resumed profiling run takes its catalog from this read rather than from the target, so a field
it leaves out reaches profiling as None and changes what the rest of the run measures.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.queries import profiling_query
from testgen.common.models.data_table import DataTable

pytestmark = pytest.mark.unit


def test_the_read_back_catalog_carries_every_field_profiling_reads():
    profiling_reads = set(re.findall(r"column_chars\.(\w+)", Path(profiling_query.__file__).read_text()))
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = []

    with patch("testgen.common.models.data_table.get_current_session", return_value=session):
        DataTable.list_column_chars(uuid4())

    query = session.execute.call_args.args[0]
    selected = {column.name for column in query.selected_columns}
    assert profiling_reads <= selected, f"not read back: {sorted(profiling_reads - selected)}"
