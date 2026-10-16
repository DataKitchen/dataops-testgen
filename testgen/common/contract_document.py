"""A contract draft's metadata document, generated from the data catalog and profiling.

Every function here works on the document only. Nothing writes back to the catalog, the
profiling results or the table group.

Every field the catalog or profiling supplies is refreshed on each generation: it takes the
source's value, and is removed when the source has none. What profiling observed goes in a
column's ``profiledValues`` custom property, never in ``logicalTypeOptions``: a bound there is a
constraint every reader enforces, so it holds only what was agreed. Fields no source supplies are
left as they are. A table or column the catalog no longer holds keeps its descriptor, so Schema
Conformance reports the drift, and a column the profiling run has no results for keeps its
profiled values.
"""

import math
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import asc, select

from testgen.common.data_catalog_service import TAG_FIELDS
from testgen.common.models import get_current_session
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.data_table import DataTable
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup

# Catalog tag -> the ODCS field it fills. A tag with no native field becomes a custom property.
_NATIVE_PROPERTY_TAGS = {"data_classification": "classification"}
_NATIVE_CONTRACT_TAGS = {"business_domain": "domain", "data_product": "dataProduct"}
# Profiled functional data type -> the string ``format`` it declares.
_FUNCTIONAL_TYPE_FORMATS = {"Email": "email", "Zip": "us-zip", "State": "us-state", "Phone": "phone"}
# Profiled functional data types that identify each row, in order of preference.
_PRIMARY_KEY_TYPES = ("ID-Unique-SK", "ID-Unique")
# The two halves of a profiled functional table type, such as ``cumulative-transaction``.
_TABLE_GRAINS = {
    "transaction": "One row per transaction",
    "entity": "One row per entity, such as a customer or an organization",
    "summary": "One row per combination of grouping keys, holding aggregated measures",
    "bridge": "One row per link between the keys it relates",
}
_TABLE_PERIODS = {
    "cumulative": "rows accumulate and are not removed",
    "window": "older rows roll off as new rows arrive",
}
EXCLUDED_MARKER = "excludedDataElement"
PROFILED_VALUES = "profiledValues"
# Column logicalType -> each profiled value it records, and the profiling result field it comes from.
_PROFILED_VALUE_SOURCES: dict[str, tuple[tuple[str, str], ...]] = {
    "integer": (("minimum", "min_value"), ("maximum", "max_value")),
    "number": (("minimum", "min_value"), ("maximum", "max_value")),
    "date": (("minimum", "min_date"), ("maximum", "max_date")),
    "timestamp": (("minimum", "min_date"), ("maximum", "max_date")),
    "string": (("minLength", "min_length"), ("maxLength", "max_length")),
}
# The catalog tags a table group carries; it has no aggregation level.
_CONTRACT_TAGS = tuple(tag for tag in (*TAG_FIELDS, "data_location") if hasattr(TableGroup, tag))


def declared_tables(document: dict | None) -> list[str]:
    """The table names a metadata document's schema section declares, in document order."""
    if not document:
        return []
    return [table["name"] for table in document.get("schema") or []]


def catalog_columns(table_groups_id: UUID, table_name: str) -> list[DataColumnChars]:
    """A table's columns in the table group's data catalog, ordered by ordinal position."""
    return get_current_session().scalars(
        select(DataColumnChars)
        .where(
            DataColumnChars.table_groups_id == table_groups_id,
            DataColumnChars.table_name == table_name,
            DataColumnChars.drop_date.is_(None),
        )
        .order_by(asc(DataColumnChars.ordinal_position))
    ).all()


def catalog_table_names(table_groups_id: UUID) -> list[str]:
    """Every table in the table group's data catalog, by name."""
    return list(get_current_session().scalars(
        select(DataTable.table_name)
        .where(DataTable.table_groups_id == table_groups_id, DataTable.drop_date.is_(None))
        .order_by(asc(DataTable.table_name))
    ).all())


def profiled_table_names(profile_run_id: UUID, table_names: list[str]) -> list[str]:
    """Those of ``table_names`` the profiling run has results for, in the order given."""
    profiled = set(get_current_session().scalars(
        select(ProfileResult.table_name).where(
            ProfileResult.profile_run_id == profile_run_id,
            ProfileResult.table_name.in_(table_names),
        ).distinct()
    ))
    return [name for name in table_names if name in profiled]


def _catalog_table(table_groups_id: UUID, table_name: str) -> DataTable | None:
    return get_current_session().scalars(
        select(DataTable).where(
            DataTable.table_groups_id == table_groups_id,
            DataTable.table_name == table_name,
            DataTable.drop_date.is_(None),
        )
    ).first()


def _camel_case(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _set_field(node: dict, key: str, value: Any) -> None:
    """Set ``key`` to ``value``, or remove it when ``value`` is None or empty."""
    if value is None or value == "":
        node.pop(key, None)
    else:
        node[key] = value


def _set_custom_property(node: dict, name: str, value: Any, description: str | None = None) -> None:
    """Set the ``name`` custom property to ``value`` where it stands, dropping any duplicate entries
    for it, or remove it when ``value`` is None or empty. A ``description`` replaces the entry's own.
    Every other custom property is left as it is."""
    pending = value is not None and value != ""
    entries = []
    for entry in node.get("customProperties") or []:
        if entry.get("property") != name:
            entries.append(entry)
        elif pending:
            entries.append({**entry, "value": value, **({"description": description} if description else {})})
            pending = False
    if pending:
        entries.append({"property": name, "value": value, **({"description": description} if description else {})})
    _set_field(node, "customProperties", entries or None)


def _flag(value: bool | None) -> bool | None:
    """``True`` for a set flag, None otherwise."""
    return True if value else None


def _merge_properties(existing_properties: list[dict], columns: list[DataColumnChars]) -> list[dict]:
    """A table's column descriptors: every one already declared, in order, then a bare descriptor
    for each catalog column not declared yet.

    A declared column the catalog no longer holds stays declared.
    """
    declared = {prop.get("name") for prop in existing_properties}
    return [
        *existing_properties,
        *({"name": column.column_name} for column in columns if column.column_name not in declared),
    ]


def _refresh_governance(
    node: dict,
    description: str | None,
    critical_data_element: bool,
    tags: dict[str, str | None],
    *,
    is_property: bool,
) -> None:
    """Refresh a descriptor's description, critical-data-element flag and catalog tags.

    A column property holds the flag and the classification in their own ODCS fields; a table
    has neither field, so there they become custom properties like every other tag.
    """
    _set_field(node, "description", description)
    for tag, value in tags.items():
        if is_property and tag in _NATIVE_PROPERTY_TAGS:
            _set_field(node, _NATIVE_PROPERTY_TAGS[tag], value)
        else:
            _set_custom_property(node, _camel_case(tag), value)
    if is_property:
        _set_field(node, "criticalDataElement", _flag(critical_data_element))
    else:
        _set_custom_property(node, "criticalDataElement", _flag(critical_data_element))


def _refresh_column(prop: dict, column: DataColumnChars, table: DataTable | None) -> None:
    """Refresh a column descriptor from its catalog column: types, governance, markers and string
    format. An excluded column loses its profiled values too, since profiling skips it."""
    _set_field(prop, "physicalType", column.db_data_type)
    _set_field(prop, "logicalType", column.logical_type)
    _set_custom_property(prop, "functionalDataType", column.functional_data_type)
    _refresh_governance(
        prop,
        column.description,
        bool(column.critical_data_element or (table and table.critical_data_element)),
        {tag: getattr(column, tag, None) for tag in TAG_FIELDS},
        is_property=True,
    )
    _set_custom_property(prop, "pii", _flag(column.pii_flag))
    _set_custom_property(prop, EXCLUDED_MARKER, _flag(column.excluded_data_element))

    string_format = (
        _FUNCTIONAL_TYPE_FORMATS.get(column.functional_data_type)
        if prop.get("logicalType") == "string" and not column.excluded_data_element
        else None
    )
    options = dict(prop.get("logicalTypeOptions") or {})
    _set_field(options, "format", string_format)
    _set_field(prop, "logicalTypeOptions", options or None)
    if column.excluded_data_element:
        _set_custom_property(prop, PROFILED_VALUES, None)


def is_excluded(prop: dict) -> bool:
    """Whether a column descriptor carries the excluded-data-element marker."""
    return any(
        entry.get("property") == EXCLUDED_MARKER and entry.get("value") is True
        for entry in prop.get("customProperties") or []
    )


def refresh_identity(document: dict, table_group: TableGroup) -> None:
    """Refresh the contract's description and tags from the table group.

    The description becomes ``description.purpose``, and the business domain and data product
    fill the native ``domain`` and ``dataProduct``. Every other tag becomes a top-level custom
    property.
    """
    for tag in _CONTRACT_TAGS:
        value = getattr(table_group, tag, None)
        if tag in _NATIVE_CONTRACT_TAGS:
            _set_field(document, _NATIVE_CONTRACT_TAGS[tag], value)
        else:
            _set_custom_property(document, _camel_case(tag), value)
    description = document.get("description")
    if isinstance(description, dict):
        _set_field(description, "purpose", table_group.description)
        if not description:
            del document["description"]
    elif description is None and table_group.description:
        document["description"] = {"purpose": table_group.description}


def _granularity(functional_table_type: str) -> str | None:
    period, _, grain = functional_table_type.partition("-")
    parts = [part for part in (_TABLE_GRAINS.get(grain), _TABLE_PERIODS.get(period)) if part]
    if not parts:
        return None
    text = "; ".join(parts)
    return f"{text[0].upper()}{text[1:]}."


def _refresh_table_type(descriptor: dict, table: DataTable) -> None:
    table_type = table.functional_table_type or None
    _set_field(descriptor, "dataGranularityDescription", _granularity(table_type) if table_type else None)
    _set_custom_property(descriptor, "functionalTableType", table_type)


def _refresh_primary_key(properties: list[dict], columns: list[DataColumnChars]) -> None:
    """Declare the table's identifying column as its primary key, when profiling found exactly one,
    and no primary key otherwise. A table with no catalog columns is left as it is."""
    if not columns:
        return
    for prop in properties:
        prop.pop("primaryKey", None)
        prop.pop("primaryKeyPosition", None)
    eligible = [column for column in columns if not column.excluded_data_element]
    for functional_type in _PRIMARY_KEY_TYPES:
        candidates = [column.column_name for column in eligible if column.functional_data_type == functional_type]
        if len(candidates) > 1:
            return
        if candidates:
            prop = next((prop for prop in properties if prop.get("name") == candidates[0]), None)
            if prop is not None:
                prop["primaryKey"] = True
                prop["primaryKeyPosition"] = 1
            return


def refresh_tables(document: dict, table_group: TableGroup, table_names: list[str]) -> dict[str, int]:
    """Declare each table on ``document`` and refresh the tables and their columns from the data
    catalog.

    A table not declared yet is appended, and so is a catalog column not declared yet. Each table and
    column carries only the tags set at its own level. A column is a critical data element when it or its table is one.
    Profiling's table type becomes the table's granularity, its identifying column the primary key,
    and its recognized formats string formats. A column excluded from testing stays declared, since
    the live table holds it, but is marked excluded and gets no primary key, format or profiled
    values. A table the catalog does not hold is left as it is, and so is a column, apart from its
    primary key.

    Updates ``document`` in place. Returns the number of catalog columns found for each table.
    """
    if document.get("schema") is None:
        document["schema"] = []
    schema = document["schema"]
    column_counts: dict[str, int] = {}

    for table_name in table_names:
        descriptor = next((entry for entry in schema if entry["name"] == table_name), None)
        if descriptor is None:
            descriptor = {"name": table_name}
            schema.append(descriptor)

        columns = catalog_columns(table_group.id, table_name)
        column_counts[table_name] = len(columns)
        descriptor["properties"] = _merge_properties(descriptor.get("properties") or [], columns)

        table = _catalog_table(table_group.id, table_name)
        if table is not None:
            _refresh_governance(
                descriptor,
                table.description,
                bool(table.critical_data_element),
                {tag: getattr(table, tag, None) for tag in TAG_FIELDS},
                is_property=False,
            )
            _refresh_table_type(descriptor, table)

        by_name = {column.column_name: column for column in columns}
        for prop in descriptor["properties"]:
            if (column := by_name.get(prop.get("name"))) is not None:
                _refresh_column(prop, column, table)

        _refresh_primary_key(descriptor["properties"], columns)

    return column_counts


def _profiled_value(logical_type: str, raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat() if logical_type == "date" else raw.isoformat(sep=" ")
    if isinstance(raw, date):
        return raw.isoformat()
    if logical_type in ("integer", "string"):
        return int(raw) if math.isfinite(float(raw)) and float(raw).is_integer() else None
    value = float(raw)
    if not math.isfinite(value):
        return None
    return int(value) if value.is_integer() else value


def fill_profiled_values(document: dict, profile_run_id: UUID, table_names: list[str]) -> None:
    """Refresh each declared column's ``profiledValues`` from the profiling run.

    The values follow the column's ``logicalType``: the observed minimum and maximum for a number,
    integer, date or timestamp, and the observed shortest and longest length for a string. A column
    marked excluded gets none. Values the run no longer supplies are removed; a column the run has
    no results for is left as it is. The entry's description dates the run.
    """
    session = get_current_session()
    started = session.scalar(select(ProfilingRun.profiling_starttime).where(ProfilingRun.id == profile_run_id))
    description = (
        f"Values TestGen profiling observed{f' on {started.date().isoformat()}' if started else ''}. "
        "A description of the data, not part of the agreement."
    )
    profiles = {
        (row.table_name, row.column_name): row
        for row in session.scalars(
            select(ProfileResult).where(
                ProfileResult.profile_run_id == profile_run_id,
                ProfileResult.table_name.in_(table_names),
            )
        )
    }
    for table in document.get("schema") or []:
        if table["name"] not in table_names:
            continue
        for prop in table.get("properties") or []:
            profile = profiles.get((table["name"], prop.get("name")))
            if profile is None:
                continue
            logical_type = prop.get("logicalType")
            values = {}
            if not is_excluded(prop):
                for key, field in _PROFILED_VALUE_SOURCES.get(logical_type, ()):
                    if (value := _profiled_value(logical_type, getattr(profile, field, None))) is not None:
                        values[key] = value
            _set_custom_property(prop, PROFILED_VALUES, values or None, description)
