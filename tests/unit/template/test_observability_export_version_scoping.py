import re

import pytest

from testgen.common.read_file import read_template_sql_file

pytestmark = pytest.mark.unit


def _export_status_case() -> str:
    sql = read_template_sql_file("update_test_results.sql", "execution")
    return sql[sql.index("observability_status = ("):sql.index("result_message = CASE")]


def test_a_contract_run_is_exported_only_when_it_checked_the_version_in_force_when_it_started():
    # The same rule as the score templates: frozen by the run's start, and no later version frozen by then
    case = _export_status_case()

    assert re.search(r"tr\.test_starttime >= sv\.frozen_at", case)
    assert re.search(
        r"NOT EXISTS \(SELECT 1 FROM suite_versions nv\s+WHERE nv\.test_suite_id = sv\.test_suite_id\s+"
        r"AND nv\.version > sv\.version\s+AND tr\.test_starttime >= nv\.frozen_at\)",
        case,
    )
    assert re.search(r"sv\.test_suite_id IS NULL\s+OR", case)
