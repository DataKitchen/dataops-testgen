import re

import pytest

from testgen.common.read_file import read_template_sql_file

pytestmark = pytest.mark.unit


def _template() -> str:
    return read_template_sql_file("disable_invalid_test_definitions.sql", "execution")


def test_a_contract_term_that_errors_stays_active():
    assert "ts.suite_type <> 'contract'" in _template()


def test_every_other_suite_kind_is_still_deactivated():
    # Deliberately filtered against contract rather than for regular: monitors are deactivated
    # today, and a suite kind added later should inherit that rather than escape it.
    sql = _template()
    assert "= 'regular'" not in sql
    assert "suite_type IN" not in sql


def test_the_contract_exclusion_is_and_joined_into_the_update_statement():
    # A substring check alone would still pass if the predicate were OR-joined (silently
    # deactivating nothing) or otherwise moved out of the WHERE clause that gates the UPDATE.
    # Anchoring it as the final AND-ed condition, terminating the statement, rules both out.
    sql = _template()
    assert re.search(r"AND\s+ts\.suite_type\s*<>\s*'contract'\s*;\s*$", sql) is not None


def test_only_results_marked_deactivated_are_deactivated():
    # Validation errors in a suite that keeps failing tests active carry no prefix, and must
    # leave the definition active.
    assert "tr.result_message LIKE 'Deactivated.%'" in _template()


def test_the_status_strips_the_prefix_by_pattern_not_position():
    sql = _template()
    assert "SUBSTRING" not in sql
    assert r"REGEXP_REPLACE(tr.result_message, '^Deactivated\.\s*', '')" in sql
