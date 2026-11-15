from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.table_group import TableGroup

pytestmark = pytest.mark.unit

MODULE = "testgen.common.models.table_group"


def _volume_row(result_id, result_signal, result_code):
    return {
        "test_type": "Volume_Trend", "test_definition_id": uuid4(), "result_id": result_id,
        "result_signal": result_signal, "result_code": result_code, "result_status": None,
        "result_message": None, "test_time": datetime(2026, 10, 20, tzinfo=UTC), "input_parameters": None,
        "column_names": None,
    }


def test_a_run_without_a_volume_result_has_no_record_count():
    rows = [_volume_row(uuid4(), "283", 1), _volume_row(None, None, None)]
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = rows

    with (
        patch(f"{MODULE}.build_series_sql", return_value=("SELECT 1", {})),
        patch(f"{MODULE}.get_current_session", return_value=session),
    ):
        series = TableGroup.get_table_monitor_series(str(uuid4()), "orders")

    assert [(e["record_count"], e["is_pending"]) for e in series["volume_events"]] == [(283, False), (None, True)]
