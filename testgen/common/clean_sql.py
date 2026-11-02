import re
from decimal import Decimal


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


# One list value and the separator after it: a value in double quotes, or an unquoted value
# trimmed of the whitespace around it
_LIST_ITEM = re.compile(r'[^\S\r\n]*(?:"((?:[^"]|"")*)"[^\S\r\n]*|([^,\r\n]*?)[^\S\r\n]*)(,|\r\n|\r|\n|\Z)')


def parse_value_list(value: str | None) -> list[str]:
    """Split a list parameter stored as CSV into its values.

    ``""`` is the empty string, and a value in double quotes may hold a comma, a line break, or
    ``""`` for one double quote. An unquoted value is trimmed of the whitespace around it; quote a
    value to keep it. A line break separates values as a comma does, and a blank line holds none.
    """
    if not value:
        return []
    values: list[str] = []
    position, line_start = 0, True
    while True:
        match = _LIST_ITEM.match(value, position)
        quoted, unquoted, separator = match.groups()
        if quoted is not None:
            values.append(quoted.replace('""', '"'))
        elif unquoted or separator == "," or not line_start:
            values.append(unquoted)
        if not separator:
            return values
        line_start = separator != ","
        position = match.end()


class NonNumericValueError(ValueError):
    """A value in a list for a numeric column that does not parse as a number."""

    def __init__(self, value: str):
        super().__init__(f"List of Expected Values contains a value that is not a number: {value}.")
        self.value = value


_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _parse_number(value: str) -> Decimal:
    # Decimal also reads digit separators, non-ASCII digits, NaN, and Infinity
    if not _NUMBER.fullmatch(value.strip()):
        raise NonNumericValueError(value)
    return Decimal(value.strip())


def parse_numeric_values(values: list[str]) -> list[Decimal]:
    """Parse each value as a finite number, dropping values equal as numbers to an earlier one.

    Surrounding whitespace is ignored. Raises ``NonNumericValueError`` on the first value that is not a
    finite number.
    """
    return list(dict.fromkeys(_parse_number(value) for value in values))


def format_value_list(values: list[str]) -> str:
    """Join ``values`` into a CSV list that ``parse_value_list`` reads back.

    A value is double-quoted, with ``"`` doubled, only when it is empty, contains a comma, a double
    quote or a line break, or has leading or trailing whitespace.
    """
    def quoted(value: str) -> str:
        if value == "" or value != value.strip() or any(char in value for char in ',"\r\n'):
            return '"' + value.replace('"', '""') + '"'
        return value
    return ",".join(quoted(value) for value in values)


def normalize_value_list(value: str, numeric: bool) -> str:
    """Rewrite a CSV list with each value kept once, quoted as ``format_value_list`` quotes it.

    For a numeric list, values equal as numbers are one value: the first is kept, without surrounding
    whitespace. Otherwise only identical strings are. Raises ``NonNumericValueError`` when a numeric list
    holds a value that is not a finite number.
    """
    values = parse_value_list(value)
    if numeric:
        kept: dict[Decimal, str] = {}
        for item in values:
            kept.setdefault(_parse_number(item), item.strip())
        return format_value_list(list(kept.values()))
    return format_value_list(list(dict.fromkeys(values)))


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
