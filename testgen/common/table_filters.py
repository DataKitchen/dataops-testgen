from collections.abc import Callable, Collection
from dataclasses import dataclass

from testgen.common.clean_sql import escape_bind_colons, expand_subset
from testgen.common.database.database_service import FinalParam

FILTER_PARAM_SUFFIXES = ("TABLE_FILTER_OPEN", "TABLE_FILTER_CLOSE", "TABLE_FILTER_CLOSE_UNALIASED")


@dataclass(frozen=True)
class TableFilter:
    table_name: str
    condition: str


def parse_table_filters(value: list[dict] | None) -> list[TableFilter]:
    """Return a table group's stored table filters, skipping entries without a table name or a condition.

    Args:
        value: The table group's ``table_filters`` column: a list of ``{"table_name", "condition"}`` entries.
    """
    filters = []
    for entry in value or []:
        table_name = (entry.get("table_name") or "").strip()
        condition = (entry.get("condition") or "").strip()
        if table_name and condition:
            filters.append(TableFilter(table_name, condition))
    return filters


def table_filter_condition(value: list[dict] | None, table_name: str | None) -> str | None:
    """Return the filter condition a table group defines for ``table_name``, or None.

    Args:
        value: The table group's ``table_filters`` column.
        table_name: The table's name, matched exactly.
    """
    if not table_name:
        return None
    return next((f.condition for f in parse_table_filters(value) if f.table_name == table_name), None)


def catalog_table_name(table_name: str | None, catalog_tables: Collection[str]) -> str | None:
    """Return the catalog's name for ``table_name``: the exact name, else the one catalog table whose name
    differs from it only in letter case, else ``table_name`` unchanged.

    Args:
        table_name: A table name as a test definition stores it.
        catalog_tables: The names of the tables in the table group's catalog.
    """
    if not table_name or table_name in catalog_tables:
        return table_name
    folded = [name for name in catalog_tables if name.lower() == table_name.lower()]
    return folded[0] if len(folded) == 1 else table_name


def filter_condition_for_test_table(
    value: list[dict] | None, table_name: str | None, catalog_tables: Callable[[], Collection[str]],
) -> str | None:
    """Return the filter condition for the table a test definition names, resolved as :func:`catalog_table_name`
    resolves it.

    Args:
        value: The table group's ``table_filters`` column.
        table_name: The table's name as the test definition stores it.
        catalog_tables: Returns the names of the tables in the table group's catalog. Called only when no filter
            names ``table_name`` exactly and one names it apart from letter case.
    """
    if not table_name:
        return None
    filters = parse_table_filters(value)
    if not any(f.table_name.lower() == table_name.lower() for f in filters):
        return None
    if all(f.table_name != table_name for f in filters):
        table_name = catalog_table_name(table_name, catalog_tables())
    return next((f.condition for f in filters if f.table_name == table_name), None)


def filtered_table_ref(
    table_ref: str, condition: str | None, schema_name: str, alias: str | None, escape_colons: bool = True,
) -> str:
    """Return a FROM target that reads only the records of ``table_ref`` matching ``condition``.

    Args:
        table_ref: The table reference as the query would otherwise write it.
        condition: The table's filter condition, or None for no filter.
        schema_name: The table's schema, which ``{DATA_SCHEMA}`` in the condition expands to.
        alias: The alias for the derived table, or None when the caller writes its own alias after it.
        escape_colons: Escape the condition's colons that SQLAlchemy would read as bind parameters. False for a
            query whose caller escapes every colon in it.

    Returns:
        ``table_ref`` unchanged without a condition; otherwise a derived table selecting the matching records.
    """
    if not condition:
        return table_ref
    derived = f"(SELECT * FROM {table_ref} WHERE ({_render_condition(condition, schema_name, escape_colons)}))"
    return f"{derived} {alias}" if alias else derived


def table_filter_params(
    condition: str | None,
    table_name: str,
    schema_name: str,
    quote: str,
    prefix: str = "",
    escape_colons: bool = True,
) -> dict[str, FinalParam]:
    """Return the template parameters that wrap a table reference so it reads only the filtered records.

    A template writes a filtered table as ``{TABLE_FILTER_OPEN}<table ref>{TABLE_FILTER_CLOSE}``, or with
    ``{TABLE_FILTER_CLOSE_UNALIASED}`` when it gives the table its own alias. Without a condition, all three
    render empty, so the reference is the table itself.

    Args:
        condition: The table's filter condition, or None for no filter.
        table_name: The table's name, which aliases the derived table.
        schema_name: The table's schema, which ``{DATA_SCHEMA}`` in the condition expands to.
        quote: The flavor's identifier quote character.
        prefix: Prepended to each parameter name, such as ``MATCH_`` for a test's match table.
        escape_colons: Escape the condition's colons that SQLAlchemy would read as bind parameters. False for a
            query whose caller escapes every colon in it.
    """
    open_, close, close_unaliased = (f"{prefix}{suffix}" for suffix in FILTER_PARAM_SUFFIXES)
    if not condition:
        return {open_: FinalParam(""), close: FinalParam(""), close_unaliased: FinalParam("")}
    where = f" WHERE ({_render_condition(condition, schema_name, escape_colons)}))"
    return {
        open_: FinalParam("(SELECT * FROM "),
        close: FinalParam(f"{where} {quote}{table_name}{quote}"),
        close_unaliased: FinalParam(where),
    }


def _render_condition(condition: str, schema_name: str, escape_colons: bool) -> str:
    expanded = expand_subset(condition, schema_name)
    return escape_bind_colons(expanded) if escape_colons else expanded
