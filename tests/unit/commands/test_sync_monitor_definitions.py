from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from testgen.commands.run_test_execution import _sync_monitor_definitions
from testgen.common.enums import MonitorType

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_test_execution"


def _sql_generator(profiled: bool) -> MagicMock:
    sql_generator = MagicMock()
    sql_generator.test_run.test_suite_id = uuid4()
    sql_generator.table_group.last_complete_profile_run_id = uuid4() if profiled else None
    sql_generator.get_missing_monitors.side_effect = lambda monitor_type: (f"missing {monitor_type.value}", {})
    sql_generator.get_errored_autogen_monitors.return_value = ("errored", {})
    sql_generator.get_active_test_definitions.return_value = ("active", {})
    return sql_generator


def _sync(sql_generator: MagicMock, missing: dict[str, list[str]]) -> MagicMock:
    def fetch(query, _params):
        return [{"table_name": table} for table in missing.get(query.removeprefix("missing "), [])]

    with (
        patch(f"{MODULE}.fetch_dict_from_db", side_effect=fetch),
        patch(f"{MODULE}.run_monitor_generation") as generate,
    ):
        _sync_monitor_definitions(sql_generator, [])
    return generate


def test_every_table_without_a_volume_monitor_gets_one():
    sql_generator = _sql_generator(profiled=False)

    generate = _sync(sql_generator, {"Volume_Trend": ["PDRP", "CSCAN_ROSTER_US"]})

    suite_id = sql_generator.test_run.test_suite_id
    assert generate.call_args_list == [
        call(suite_id, ["Freshness_Trend", "Volume_Trend", "Metric_Trend"], mode="delete"),
        call(suite_id, ["Volume_Trend"], mode="insert", table_names=["PDRP", "CSCAN_ROSTER_US"]),
    ]
    sql_generator.get_missing_monitors.assert_called_once_with(MonitorType.VOLUME)


def test_freshness_monitors_are_added_only_once_the_table_group_is_profiled():
    sql_generator = _sql_generator(profiled=True)

    generate = _sync(sql_generator, {"Freshness_Trend": ["PDRP"]})

    assert generate.call_args_list[1:] == [
        call(sql_generator.test_run.test_suite_id, ["Freshness_Trend"], mode="insert", table_names=["PDRP"]),
    ]


def test_with_every_table_monitored_nothing_is_inserted():
    generate = _sync(_sql_generator(profiled=True), {})

    assert [c.kwargs["mode"] for c in generate.call_args_list] == ["delete"]
