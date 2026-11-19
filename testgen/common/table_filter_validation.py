import logging

from testgen.common.database.database_service import get_flavor_service
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.common.table_filters import filtered_table_ref, parse_table_filters
from testgen.ui.services.database_service import TargetQuery, target_db_session

LOG = logging.getLogger("testgen")


class InvalidTableFilters(ValueError):
    """The table filters cannot be saved. ``messages`` holds one user-facing message per problem."""

    def __init__(self, *messages: str):
        super().__init__(" ".join(messages))
        self.messages = list(messages)


def normalize_table_filters(value: list[dict] | None) -> list[dict] | None:
    """Return table filters in their stored form: trimmed, without blank entries, and None when empty.

    Args:
        value: Filters as ``{"table_name", "condition"}`` entries.

    Raises:
        InvalidTableFilters: An entry has a table name but no condition, a condition but no table name,
            or two entries name the same table. It carries every such problem.
    """
    seen: set[str] = set()
    problems: list[str] = []
    for entry in value or []:
        table_name = (entry.get("table_name") or "").strip()
        condition = (entry.get("condition") or "").strip()
        if table_name and not condition:
            problems.append(f"Enter a filter condition for table {table_name}.")
        if condition and not table_name and (problem := "Select a table for each filter condition.") not in problems:
            problems.append(problem)
        if table_name in seen and (problem := f"Table {table_name} has more than one filter.") not in problems:
            problems.append(problem)
        if table_name:
            seen.add(table_name)
    if problems:
        raise InvalidTableFilters(*problems)
    filters = [{"table_name": f.table_name, "condition": f.condition} for f in parse_table_filters(value)]
    return filters or None


def table_filter_errors(
    run: TargetQuery, connection: Connection, table_group: TableGroup, value: list[dict] | None,
) -> dict[str, str]:
    """Read one record of each filtered table through its filter, and return the filters that fail.

    Args:
        run: Runs a query on an open target session.
        connection: The table group's connection.
        table_group: The table group the filters are for; its schema holds the tables.
        value: Filters as ``{"table_name", "condition"}`` entries, in their stored form.

    Returns:
        The database's error for each failing filter, keyed by table name, in the filters' order.
    """
    flavor_service = get_flavor_service(connection.sql_flavor)
    quote = flavor_service.quote_character
    schema = table_group.table_group_schema
    prefix, suffix = flavor_service.row_limit_clauses(1)
    errors: dict[str, str] = {}
    for table_filter in parse_table_filters(value):
        source = filtered_table_ref(
            flavor_service.get_table_ref(schema, table_filter.table_name, connection.sql_flavor_code),
            table_filter.condition,
            schema,
            f"{quote}{table_filter.table_name}{quote}",
        )
        try:
            run(f"SELECT {prefix} 1 AS checked FROM {source} {suffix}".strip())
        except Exception as e:
            LOG.info(f"Table filter for {table_filter.table_name} failed validation: {e}")
            errors[table_filter.table_name] = _error_text(e)
    return errors


def validate_table_filters(connection: Connection, table_group: TableGroup, value: list[dict] | None) -> None:
    """Check each table filter by reading one record of its table through it.

    Args:
        connection: The table group's connection.
        table_group: The table group the filters are for; its schema holds the tables.
        value: Filters as ``{"table_name", "condition"}`` entries, in their stored form.

    Raises:
        InvalidTableFilters: A filter's query fails. It carries the database's error for each failing filter.
    """
    if not parse_table_filters(value):
        return
    with target_db_session(connection, table_group) as run:
        errors = table_filter_errors(run, connection, table_group, value)
    if errors:
        raise InvalidTableFilters(
            *(f"The filter for table {table_name} is not valid: {error}" for table_name, error in errors.items())
        )


def _error_text(error: Exception) -> str:
    return str(getattr(error, "orig", None) or error).strip().splitlines()[0]
