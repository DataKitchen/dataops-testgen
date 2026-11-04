"""Per-run overrides of what a test run reads: schema, table names, and custom query variables.

The REST request model and the MCP tool share the field text and the validation here so the two
surfaces describe and accept the same thing.
"""

import re
from collections.abc import Mapping

# A table reference and an app-database lookup both take these names as text, so they are held to
# the shape a schema name is: anything a quoted identifier can hold, minus what would end the quote.
# ``;`` and ``=`` are excluded on top of that: a referential test's second table is reported among
# a result's input parameters, serialised as ``name=value`` pairs joined by ``;``, and a name
# holding either reads back as a different table rather than failing.
TABLE_NAME_PATTERN = r"^[^\\\"'`;=\x00-\x1f\x7f]+$"
TABLE_NAME_MAX_LENGTH = 100

TABLE_NAME_PATTERN_TEXT = (
    "A key is an exact table name or a pattern with one `*`, which matches any run of characters; "
    "a `*` in the value is replaced by what the key's `*` matched. An exact name takes precedence "
    "over patterns, and patterns apply in the order given. A table no key matches keeps its name. "
    "Names match exactly, including case."
)

SCHEMA_NAME = (
    "Database connections only, other than Salesforce Data 360. Schema to read the table group's "
    "tables from, for this run only. "
    "The stored test definitions are not changed, the data catalog keeps the table group's own "
    "tables, and the run deactivates no tests. To change the schema for every run, change the "
    "table group's schema instead."
)

MATCH_SCHEMA_NAME = (
    "Database connections only, other than Salesforce Data 360. Schema to read the second table of "
    "each referential test from, for this run only. Tests without a second table are unaffected, "
    "the stored test definitions are not changed, and the run deactivates no tests."
)

TABLE_NAMES = (
    "Tables to read in place of the tests' own, for this run only, as a map from a test's table "
    'name to the table to read, e.g. `{"orders": "build_orders", "*": "build_*"}`. A referential '
    f"test's second table is unaffected. {TABLE_NAME_PATTERN_TEXT}"
)

MATCH_TABLE_NAMES = (
    "Tables to read in place of referential tests' second tables, for this run only, as a map from "
    'a second table\'s name to the table to read, e.g. `{"*": "prod_*"}`. Tests without a second '
    f"table are unaffected. {TABLE_NAME_PATTERN_TEXT}"
)


OVERRIDE_LABELS = {
    "schema_name": "Schema",
    "table_names": "Tables",
    "match_schema_name": "Match schema",
    "match_table_names": "Match tables",
    "variables": "Variables",
}

SCHEMA_OVERRIDE_UNSUPPORTED = (
    "`schema_name` does not apply to file connections or Salesforce Data 360, whose tables are not "
    "qualified by schema."
)

MATCH_SCHEMA_OVERRIDE_UNSUPPORTED = (
    "`match_schema_name` does not apply to file connections or Salesforce Data 360, whose tables "
    "are not qualified by schema."
)


def overrides_from_kwargs(kwargs: Mapping[str, object] | None) -> dict[str, object]:
    """Return the overrides a job's kwargs carry, keyed by field name.

    Args:
        kwargs: A job execution's dispatch payload.

    Returns:
        Field name to value, holding only the overrides the run was submitted with.
    """
    return {key: kwargs[key] for key in OVERRIDE_LABELS if kwargs and kwargs.get(key)}


def labelled_overrides(**values: object) -> dict[str, object]:
    """Return the overrides a run applied, keyed by display label, in a fixed order.

    Args:
        values: Override field names to the value the run used, or a falsy value for the ones
            it did not override.

    Returns:
        Display label to value, holding only the overrides the run applied.
    """
    return {label: values[key] for key, label in OVERRIDE_LABELS.items() if values.get(key)}


def validate_table_name_map(mapping: Mapping[str, str] | None) -> str | None:
    """Return an error message if a key or a value cannot be used as a table name, else ``None``.

    Args:
        mapping: Exact names or single-``*`` patterns to the table to read.

    Returns:
        The first problem found, or ``None``.
    """
    for key, value in (mapping or {}).items():
        if key.count("*") > 1:
            return f"Table name pattern `{key}` can contain at most one `*`."
        if "*" in value and "*" not in key:
            return f"Table name `{value}` can only contain `*` when its key `{key}` does."
        # The value reaches a table reference and an app-database lookup as text, the same way a
        # schema override does, so it is held to the same shape.
        if error := validate_table_name(value):
            return f"Table name `{value}` {error}."
    return None


def validate_table_name(value: str) -> str | None:
    """Return why ``value`` cannot be used as a table name, else ``None``."""
    if not value or not value.strip():
        return "cannot be empty"
    if len(value) > TABLE_NAME_MAX_LENGTH:
        return f"cannot be longer than {TABLE_NAME_MAX_LENGTH} characters"
    if not re.fullmatch(TABLE_NAME_PATTERN, value):
        return "cannot contain quotes, backslashes, semicolons, equals signs, or control characters"
    return None


def resolve_table_name(name: str, mapping: Mapping[str, str] | None) -> str:
    """Return the table to read in place of ``name``.

    Args:
        name: The table name a test definition carries.
        mapping: Exact names or single-``*`` patterns to the table to read.

    Returns:
        The mapped name, or ``name`` when no key matches.

    Raises:
        ValueError: A key matches ``name`` but expands to an empty name.
    """
    # A CUSTOM test carries no table name; its table is only an output label.
    if not mapping or not name:
        return name

    if name in mapping:
        return mapping[name]

    for key, value in mapping.items():
        if "*" not in key:
            continue
        prefix, suffix = key.split("*", 1)
        if len(name) >= len(prefix) + len(suffix) and name.startswith(prefix) and name.endswith(suffix):
            matched = name[len(prefix) : len(name) - len(suffix)]
            resolved = value.replace("*", matched)
            if not resolved:
                raise ValueError(
                    f"Table name pattern `{key}` maps `{name}` to an empty name. "
                    f"`{name}` matches `{key}` with nothing in place of `*`."
                )
            return resolved

    return name
