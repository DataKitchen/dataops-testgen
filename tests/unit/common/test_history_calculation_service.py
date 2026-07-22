import pytest

from testgen.common.history_calculation_service import (
    format_calculation_expression,
    parse_calculation_expression,
)


@pytest.mark.parametrize(
    "expression,wrapped",
    [
        ("0.5 * {AVERAGE}", "EXPR:[0.5 * {AVERAGE}]"),
        ("{MAXIMUM} + {STANDARD_DEVIATION}", "EXPR:[{MAXIMUM} + {STANDARD_DEVIATION}]"),
        ("", "EXPR:[]"),
    ],
)
def test_format_wraps_expression_in_expr_brackets(expression, wrapped):
    assert format_calculation_expression(expression) == wrapped


@pytest.mark.parametrize(
    "wrapped,payload",
    [
        ("EXPR:[0.5 * {AVERAGE}]", "0.5 * {AVERAGE}"),
        ("EXPR:[{MAXIMUM} + {STANDARD_DEVIATION}]", "{MAXIMUM} + {STANDARD_DEVIATION}"),
        ("EXPR:[]", ""),
        ("EXPR:[array_length(arr[1:5], 1)]", "array_length(arr[1:5], 1)"),
    ],
)
def test_parse_returns_payload_for_wrapped_values(wrapped, payload):
    is_expr, unwrapped = parse_calculation_expression(wrapped)
    assert (is_expr, unwrapped) == (True, payload)


@pytest.mark.parametrize(
    "value",
    ["Value", "Minimum", "Maximum", "Sum", "Average", "arbitrary text"],
)
def test_parse_returns_none_for_plain_calculation_tokens(value):
    assert parse_calculation_expression(value) == (False, None)


@pytest.mark.parametrize("value", [None, ""])
def test_parse_treats_empty_and_none_as_not_expression(value):
    assert parse_calculation_expression(value) == (False, None)


@pytest.mark.parametrize("value", ["EXPR:[missing_close", "EXPR:noBracket", "prefix EXPR:[x]"])
def test_parse_rejects_malformed_wrapper(value):
    """The SQL execution template's SUBSTRING slicing assumes exactly one leading
    ``EXPR:[`` and one trailing ``]``. Anything else must fail the check so a
    malformed value never round-trips through the Python parser as if it were valid."""
    assert parse_calculation_expression(value) == (False, None)


def test_format_and_parse_round_trip():
    payload = "1.5 * {AVERAGE} + coalesce({MINIMUM}, 0)"
    is_expr, unwrapped = parse_calculation_expression(format_calculation_expression(payload))
    assert (is_expr, unwrapped) == (True, payload)
