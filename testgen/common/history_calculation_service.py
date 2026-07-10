"""Wire-format helpers for ``TestDefinition.history_calculation`` expression values.

Historical-mode monitor thresholds can compute bounds from a SQL expression
referencing aggregates like ``{VALUE}`` / ``{MINIMUM}`` / ``{MAXIMUM}`` / ``{SUM}``
/ ``{AVERAGE}`` / ``{STANDARD_DEVIATION}``. The expression is stored wrapped as
``EXPR:[<sql>]`` in ``history_calculation`` / ``history_calculation_upper``.

The execution template ``testgen/template/execution/update_history_calc_thresholds.sql``
detects the wrapper via ``LIKE 'EXPR:[%]'`` and slices off the six-char prefix
and one-char suffix (PostgreSQL ``SUBSTRING`` with a hardcoded offset of 7).
The wrapper must therefore be exactly ``EXPR:[`` + payload + ``]`` — any deviation
would silently break the slicing and null out the tolerance at execution time.

Mirrors ``formatExpressionValue`` / ``parseExpressionValue`` in
``testgen/ui/static/js/components/test_definition_form.js``.
"""

_EXPR_PREFIX = "EXPR:["
_EXPR_SUFFIX = "]"


def format_calculation_expression(expression: str) -> str:
    """Wrap a raw SQL expression as the ``EXPR:[<sql>]`` form stored in
    ``TestDefinition.history_calculation`` / ``.history_calculation_upper``."""
    return f"{_EXPR_PREFIX}{expression}{_EXPR_SUFFIX}"


def parse_calculation_expression(value: str | None) -> tuple[bool, str | None]:
    """Return ``(is_expression, payload_or_None)`` for a stored calculation value.

    ``payload`` is the raw SQL inside the brackets (may be empty). Non-wrapped
    values (calculation tokens like ``Average`` or ``Value``, or ``None``) return
    ``(False, None)``.
    """
    if value and value.startswith(_EXPR_PREFIX) and value.endswith(_EXPR_SUFFIX):
        return True, value[len(_EXPR_PREFIX):-len(_EXPR_SUFFIX)]
    return False, None
