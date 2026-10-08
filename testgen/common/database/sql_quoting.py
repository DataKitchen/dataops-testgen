"""Quoting for values and names written into SQL text, in the ANSI form DuckDB reads."""


def sql_literal(value: str) -> str:
    """Return ``value`` as a single-quoted string literal."""
    return "'" + value.replace("'", "''") + "'"


def sql_identifier(value: str) -> str:
    """Return ``value`` as a double-quoted identifier."""
    return '"' + value.replace('"', '""') + '"'
