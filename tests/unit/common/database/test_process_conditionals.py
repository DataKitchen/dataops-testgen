import pytest

from testgen.common.database.database_service import process_conditionals

pytestmark = pytest.mark.unit


def _lines(query: str, params: dict) -> list[str]:
    return [line.strip() for line in process_conditionals(query, params).splitlines() if line.strip()]


def test_single_if_true_keeps_block():
    query = "A\n-- TG-IF flag\nB\n-- TG-ENDIF\nC\n"
    assert _lines(query, {"flag": True}) == ["A", "B", "C"]


def test_single_if_false_drops_block():
    query = "A\n-- TG-IF flag\nB\n-- TG-ENDIF\nC\n"
    assert _lines(query, {"flag": False}) == ["A", "C"]


def test_else_takes_opposite_branch():
    query = "-- TG-IF flag\nB\n-- TG-ELSE\nC\n-- TG-ENDIF\n"
    assert _lines(query, {"flag": True}) == ["B"]
    assert _lines(query, {"flag": False}) == ["C"]


def test_missing_flag_is_falsey():
    query = "-- TG-IF flag\nB\n-- TG-ELSE\nC\n-- TG-ENDIF\n"
    assert _lines(query, {}) == ["C"]


def test_marker_lines_are_dropped_from_the_output():
    query = "-- TG-IF flag\nB\n-- TG-ELSE\nC\n-- TG-ENDIF\n"
    assert "TG-" not in process_conditionals(query, {"flag": True})


def test_blocks_do_not_nest():
    query = "-- TG-IF outer\nB\n-- TG-IF inner\nC\n-- TG-ENDIF\n-- TG-ENDIF\n"
    with pytest.raises(ValueError):
        process_conditionals(query, {"outer": True, "inner": True})


def test_unbalanced_raises():
    with pytest.raises(ValueError):
        process_conditionals("-- TG-IF flag\nB\n", {"flag": True})
    with pytest.raises(ValueError):
        process_conditionals("B\n-- TG-ENDIF\n", {})
    with pytest.raises(ValueError):
        process_conditionals("-- TG-ELSE\nB\n", {})


def test_if_without_a_variable_raises():
    with pytest.raises(ValueError):
        process_conditionals("-- TG-IF\nB\n-- TG-ENDIF\n", {})
