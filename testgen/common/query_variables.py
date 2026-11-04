"""Variables a custom query declares as ``{NAME:default}``, and the values a run gives them.

A declaration is resolved into the query text before the query reaches the parameter dictionary,
which is what keeps the two apart: ``replace_params`` matches ``{KEY}`` exactly and would never
match a declaration, three execution paths escape ``:`` for SQLAlchemy binds and would break one,
and a value resolved later could be expanded by a substitution that follows it.
"""

import re
from collections.abc import Mapping

# A name TestGen itself substitutes. Written as ``{NAME}`` these are parameters, so a query may
# hold them; written as ``{NAME:default}`` they would shadow a value TestGen fills in, which is
# why declaring one is refused. tests/unit/common/test_reserved_parameter_names.py fails when a
# parameter is added to either dictionary without being named here.
RESERVED_PARAMETER_NAMES: frozenset[str] = frozenset({
    "APP_SCHEMA_NAME", "BASELINE_AVG", "BASELINE_CT", "BASELINE_SD", "BASELINE_SUM",
    "BASELINE_UNIQUE_CT", "BASELINE_VALUE", "BASELINE_VALUE_CT", "BASELINE_VALUE_LIST",
    "BASELINE_VALUE_LITERAL", "CATALOG_TABLE_NAME", "COLUMN_NAME", "COLUMN_NAME_NO_QUOTES",
    "COLUMN_NUM", "COLUMN_TYPE", "COLUMN_VALUE", "CONCAT_COLUMNS", "CONCAT_MATCH_GROUPBY",
    "CUSTOM_QUERY", "DATA_SCHEMA", "DETAIL_EXPRESSION", "EPOCH_SUM_TERM", "EXCLUDED_MINUTES",
    "GROUPBY_NAMES", "HAVING_CONDITION", "INPUT_PARAMETERS", "IS_EXCLUDED_DAY", "KEYED_HASH_TERM",
    "LIMIT", "LIMIT_2", "LIMIT_4", "LOWER_TOLERANCE", "MATCH_COLUMN_NAMES", "MATCH_GROUPBY_NAMES",
    "MATCH_HAVING_CONDITION", "MATCH_SCHEMA_NAME", "MATCH_SUBSET_CONDITION", "MATCH_TABLE_NAME",
    "METADATA", "MULTISET_HASH_TERM", "PROFILE_RUN_DATE", "QUERY", "QUOTE", "RUN_DATE",
    "SCHEMA_NAME", "SKIP_ERRORS", "SQL_FLAVOR", "SUBSET_CONDITION", "TABLE_GROUPS_ID",
    "TABLE_NAME", "TARGET_SCHEMA", "TEST_DATE", "TEST_DEFINITION_ID", "TEST_RUN_ID",
    "TEST_SCHEMAS", "TEST_SUITE_ID", "TEST_TYPE", "THRESHOLD_VALUE", "UPPER_TOLERANCE",
    "VARCHAR_TYPE", "VERSION_ID", "WINDOW_DATE_COLUMN", "WINDOW_DAYS",
})

VARIABLE_NAME_PATTERN = r"[A-Z][A-Z0-9_]*"
# The default runs to the closing brace, so it may hold a colon and cannot hold a `}`. Requiring
# the name to start with a capital leaves other brace syntax alone: a regex quantifier `{2,4}`, an
# ODBC escape `{d '2026-01-01'}`, and a JSON object all fail at the first character.
_DECLARATION = re.compile(rf"\{{(?P<name>{VARIABLE_NAME_PATTERN})(?::(?P<default>[^}}]*))?\}}")

VARIABLES = (
    "Values for the variables declared in custom queries as `{NAME:default}`, for this run only, "
    'as a map from a variable\'s name to its value, e.g. `{"END_DATE": "2026-10-17"}`. A variable '
    "not given here takes its default, and a key no custom query in the run declares is ignored. "
    "Each value is inserted into the query as SQL text, so a string value needs its own quotes in "
    "the query."
)

CUSTOM_QUERY_HELP = (
    "Use {NAME:default} for a value a test run can override, such as {END_DATE:2026-10-10}."
)


def declared_variables(query: str | None) -> dict[str, str]:
    """Return the variables a query declares, each with its default.

    Args:
        query: The custom query text, if the test has one.

    Returns:
        Variable name to default value, in the order the query declares them. A name TestGen
        substitutes is a parameter rather than a variable and is left out.
    """
    return {
        match["name"]: match["default"]
        for match in _DECLARATION.finditer(query or "")
        if match["default"] is not None and match["name"] not in RESERVED_PARAMETER_NAMES
    }


def validate_declarations(query: str | None) -> str | None:
    """Return why a query's variable declarations are unusable, else ``None``.

    Args:
        query: The custom query text, if the test has one.

    Returns:
        The first problem found, as a field-error reason — no trailing period, since the save
        paths render it after the field's label — or ``None``.
    """
    for match in _DECLARATION.finditer(query or ""):
        name, default = match["name"], match["default"]
        if name in RESERVED_PARAMETER_NAMES:
            if default is not None:
                return f"{name} is filled in by TestGen and cannot be used as a variable"
        elif default is None:
            return f"Variable {name} needs a default value, written as {{{name}:value}}"
    return None


def validate_values(values: Mapping[str, str] | None) -> str | None:
    """Return why a run's variable values are unusable, else ``None``.

    Args:
        values: Variable name to the value this run gives it.

    Returns:
        The first problem found, or ``None``.
    """
    for name in values or {}:
        if not re.fullmatch(VARIABLE_NAME_PATTERN, name):
            return (
                f"`{name}` is not a valid variable name. Use capital letters, digits, and "
                "underscores, starting with a letter."
            )
        if name in RESERVED_PARAMETER_NAMES:
            return f"`{name}` is filled in by TestGen and cannot be used as a variable."
    return None


def render(query: str | None, values: Mapping[str, str] | None = None) -> str | None:
    """Return the query with each declared variable replaced by its value.

    Args:
        query: The custom query text, if the test has one.
        values: Variable name to the value this run gives it; a variable left out takes its
            default.

    Returns:
        The query, or ``query`` unchanged when it declares nothing. A name TestGen substitutes is
        left in place for the parameter dictionary to fill.
    """
    if not query:
        return query

    def resolve(match: re.Match) -> str:
        name, default = match["name"], match["default"]
        if default is None or name in RESERVED_PARAMETER_NAMES:
            return match[0]
        return (values or {}).get(name, default)

    return _DECLARATION.sub(resolve, query)


def values_for_run(query: str | None, values: Mapping[str, str] | None) -> dict[str, str]:
    """Return the value each of a query's variables takes on this run.

    Args:
        query: The custom query text, if the test has one.
        values: Variable name to the value this run gives it.

    Returns:
        Variable name to the value used, defaults included, so a result can record what it ran
        with. A key no declaration matches is left out.
    """
    return {
        name: (values or {}).get(name, default)
        for name, default in declared_variables(query).items()
    }
