import csv
import io
import re
from decimal import Decimal, InvalidOperation


def CleanSQL(strInput: str) -> str:
    # Use regular expression to remove comment text fenced by /*...*/
    strInput = re.sub(r"/\*.*?\*/", "", strInput, flags=re.DOTALL)
    # Use regular expression to remove comment text starting with --
    strInput = re.sub(r"--.*$", "", strInput, flags=re.MULTILINE)
    # Use regular expression to replace any tab with one space
    strInput = re.sub(r"\t", " ", strInput)
    # Use regular expression to remove spaces outside quotes
    parts = re.split(r"""("[^"]*"|'[^']*')""", strInput)
    parts[::2] = (" ".join(s.split()) for s in parts[::2])  # outside quotes
    return " ".join(parts)


def null_if_empty(value: object) -> object:
    """Return the literal ``"NULL"`` when ``value`` is empty (``None`` or ``""``), else ``value``.

    For numeric test parameters substituted into SQL templates (baseline counts,
    averages, standard deviations, tolerances). An empty substitution produces invalid SQL
    such as ``CAST( AS FLOAT)``; ``"NULL"`` makes the surrounding expression evaluate to NULL
    instead. A real ``0`` is preserved (``0 in (None, "")`` is ``False``). Not suitable for
    params used as quoted literals or IN-lists (e.g. ``BASELINE_VALUE``, ``BASELINE_SUM`` for
    Freshness_Trend), where ``"NULL"`` would not be valid SQL.
    """
    return "NULL" if value in (None, "") else value


def strip_trailing_semicolons(sql: str | None) -> str | None:
    """Remove trailing semicolons and whitespace, so a complete statement can be nested as a subquery."""
    return re.sub(r"[\s;]+$", "", sql) if sql else sql


def parse_value_list(value: str | None) -> list[str]:
    """Split a list parameter stored as CSV into its values.

    Follows Python ``csv`` quoting: ``""`` is the empty string and ``"a,b"`` is one value holding a
    comma. Whitespace after a delimiter is dropped; quote a value to keep leading whitespace.
    """
    if not value:
        return []
    return [item for row in csv.reader(io.StringIO(value), skipinitialspace=True) for item in row]


class NonNumericValueError(ValueError):
    """A value in a list for a numeric column that does not parse as a number."""

    def __init__(self, value: str):
        super().__init__(f"List of Expected Values contains a value that is not a number: {value}.")
        self.value = value


def parse_numeric_values(values: list[str]) -> list[Decimal]:
    """Parse each value as a finite number, dropping values equal as numbers to an earlier one.

    Surrounding whitespace is ignored. Raises ``NonNumericValueError`` on the first value that is not a
    finite number.
    """
    numbers: dict[Decimal, None] = {}
    for value in values:
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            raise NonNumericValueError(value) from None
        if not number.is_finite():
            raise NonNumericValueError(value)
        numbers.setdefault(number)
    return list(numbers)


def concat_columns(columns: str, null_value: str):
    # Prepares SQL expression to concatenate comma-separated column list
    expression = ""
    if columns:
        if "," in columns:
            column_list = [f"COALESCE({col.strip()}, '{null_value}')" for col in columns.split(",")]
            expression = f"CONCAT({', '.join(column_list)})"
        else:
            expression = columns
    return expression
