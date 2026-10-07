import csv
import io
import re


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
