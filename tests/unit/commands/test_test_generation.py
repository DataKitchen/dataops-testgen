from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from testgen.commands.test_generation import TestGeneration


@patch("testgen.commands.test_generation.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[])
def test_run_appends_override_delete_after_stale_delete(_mock_gen, mock_exec):
    tg = TestGeneration.__new__(TestGeneration)  # bypass __init__ (needs no DB)
    tg.table_group = MagicMock(id="tg-id", table_group_schema="s")
    tg.test_suite = MagicMock(id="suite-id")
    tg.generation_set = "Standard"
    tg.test_types_filter = None
    tg.run_date = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    tg.as_of_date = tg.run_date
    tg.flavor = "postgresql"
    tg.flavor_service = MagicMock(quote_character='"')

    tg.run()

    executed_queries = [query for query, _params in mock_exec.call_args[0][0]]
    override_idx = next(
        i for i, q in enumerate(executed_queries)
        if "tt.overrides = g.test_type" in q
    )
    stale_idx = next(
        i for i, q in enumerate(executed_queries)
        if "last_auto_gen_date < :RUN_DATE" in q
    )
    assert override_idx > stale_idx, "override delete must run after the stale delete"
