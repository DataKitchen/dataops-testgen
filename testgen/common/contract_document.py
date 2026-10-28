"""A contract draft's metadata document, generated from the data catalog and profiling.

Every function here works on the document only. Nothing writes back to the catalog, the
profiling results or the table group.

Each generation declares the catalog's columns and refreshes their physical and logical types.
The other fields the catalog or profiling supplies fall in two groups, each refreshed only when a
generation asks for it: profiling (functional types, keys, granularity, formats and profiled
values) and catalog metadata (descriptions, tags, classification and the critical, PII and
excluded flags). A refreshed field takes the source's value, and is removed when the source has none. What
profiling observed goes in a column's ``profiledValues`` custom property, never in
``logicalTypeOptions``: a bound there is a constraint every reader enforces, so it holds only what
was agreed. Fields no source supplies are left as they are. A table or column the catalog no
longer holds keeps its descriptor, so Schema Conformance reports the drift, and a column the
profiling run has no results for keeps its profiled values.
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
_FUNCTIONAL_TYPE_FORMATS = {"Email": "email", "Zip": "us-zip", "Zip3": "us-zip3", "State": "us-state", "Phone": "phone"}
# Profiled functional data types that identify each row, in order of preference.
_PRIMARY_KEY_TYPES = ("ID-Unique-SK", "ID-Unique")
# The two halves of a profiled functional table type, such as ``cumulative-transaction``. A table
# profiling has seen only once has the grain alone, such as ``transaction``.
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
PII_MARKER = "pii"
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


def physical_name(node: dict) -> str | None:
    """The database name of an ODCS table or column: its ``physicalName``, else its ``name``."""
    physical = node.get("physicalName")
    return physical if isinstance(physical, str) and physical else node.get("name")


def physical_column_names(table: dict) -> dict[str, str]:
    """Each column an ODCS table declares, its ``physical_name`` by its ``name``."""
    return {
        prop["name"]: physical_name(prop)
        for prop in table.get("properties") or []
        if isinstance(prop, dict) and isinstance(prop.get("name"), str)
    }


def declared_tables(document: dict | None) -> list[str]:
    """The physical names of the tables a metadata document's schema section declares, in document order."""
    if not document:
        return []
    return [physical_name(table) for table in document.get("schema") or []]


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
    declared = {physical_name(prop) for prop in existing_properties}
    return [
        *existing_properties,
        *({"name": column.column_name} for column in columns if column.column_name not in declared),
    ]


def _refresh_catalog_metadata(
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


def _refresh_column_catalog_metadata(prop: dict, column: DataColumnChars, table: DataTable | None) -> None:
    """Refresh a column descriptor's catalog metadata from its catalog column: description, tags,
    classification and the critical, PII and excluded flags."""
    _refresh_catalog_metadata(
        prop,
        column.description,
        bool(
            column.critical_data_element
            if column.critical_data_element is not None
            else table and table.critical_data_element
        ),
        {tag: getattr(column, tag, None) for tag in TAG_FIELDS},
        is_property=True,
    )
    _set_custom_property(prop, PII_MARKER, _flag(column.pii_flag))
    _set_custom_property(prop, EXCLUDED_MARKER, _flag(column.excluded_data_element))


def _refresh_column_types(prop: dict, column: DataColumnChars) -> None:
    """Refresh a column descriptor's physical and logical types from its catalog column. A changed
    logical type drops the string format and profiled values derived from the previous one."""
    if prop.get("logicalType") not in (None, column.logical_type):
        options = dict(prop.get("logicalTypeOptions") or {})
        options.pop("format", None)
        _set_field(prop, "logicalTypeOptions", options or None)
        _set_custom_property(prop, PROFILED_VALUES, None)
    _set_field(prop, "physicalType", column.db_data_type)
    _set_field(prop, "logicalType", column.logical_type)


def _refresh_column_profiling(prop: dict, column: DataColumnChars) -> None:
    """Refresh a column descriptor's functional type and string format from its catalog column. A
    column the catalog excludes gets no format and loses its profiled values, since profiling skips
    it."""
    _set_custom_property(prop, "functionalDataType", column.functional_data_type)

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


def _has_marker(prop: dict, marker: str) -> bool:
    return any(
        entry.get("property") == marker and entry.get("value") is True
        for entry in prop.get("customProperties") or []
    )


def is_excluded(prop: dict) -> bool:
    """Whether a column descriptor carries the excluded-data-element marker."""
    return _has_marker(prop, EXCLUDED_MARKER)


def is_pii(prop: dict) -> bool:
    """Whether a column descriptor carries the PII marker."""
    return _has_marker(prop, PII_MARKER)


def _withholds_profiled_values(column: DataColumnChars) -> bool:
    """Whether a catalog column's profiled values stay out of the document: it is excluded from
    testing or flagged PII."""
    return bool(column.excluded_data_element) or column.pii_flag is not None


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
    period, _, grain = functional_table_type.rpartition("-")
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
            prop = next((prop for prop in properties if physical_name(prop) == candidates[0]), None)
            if prop is not None:
                prop["primaryKey"] = True
                prop["primaryKeyPosition"] = 1
            return


def refresh_tables(
    document: dict,
    table_group: TableGroup,
    table_names: list[str],
    *,
    profiling: bool = True,
    catalog_metadata: bool = True,
) -> dict[str, int]:
    """Declare each table on ``document`` and refresh the tables and their columns from the data
    catalog.

    A table not declared yet is appended, and so is a catalog column not declared yet, and each
    column's physical and logical types are refreshed. With ``profiling``, the functional types,
    granularity, primary key and string formats are refreshed: profiling's table type becomes the
    table's granularity, its identifying column the primary key, and its recognized formats string
    formats. With ``catalog_metadata``, each table's and column's description, tags, classification and
    flags are refreshed; each carries only the tags set at its own level, and a column is a
    critical data element by its own flag, or by its table's when it has none.

    A column the catalog excludes from testing stays declared, since the live table holds it. With
    ``profiling``, it gets no primary key, format or profiled values, whatever its own excluded
    marker says; the marker itself is catalog metadata. A column the catalog flags PII loses its profiled
    values whichever groups are refreshed. A table the catalog does not hold is left as it is, and
    so is a column, apart from its primary key when ``profiling`` is set. A table and a column are
    matched to the catalog by ``physical_name``.

    Updates ``document`` in place. Returns the number of catalog columns found for each table.
    """
    if document.get("schema") is None:
        document["schema"] = []
    declared = document["schema"]
    column_counts: dict[str, int] = {}

    for table_name in table_names:
        descriptor = next((entry for entry in declared if physical_name(entry) == table_name), None)
        if descriptor is None:
            descriptor = {"name": table_name}
            declared.append(descriptor)

        columns = catalog_columns(table_group.id, table_name)
        column_counts[table_name] = len(columns)
        properties = descriptor["properties"] = _merge_properties(descriptor.get("properties") or [], columns)

        table = _catalog_table(table_group.id, table_name)
        if table is not None:
            if catalog_metadata:
                _refresh_catalog_metadata(
                    descriptor,
                    table.description,
                    bool(table.critical_data_element),
                    {tag: getattr(table, tag, None) for tag in TAG_FIELDS},
                    is_property=False,
                )
            if profiling:
                _refresh_table_type(descriptor, table)

        by_name = {column.column_name: column for column in columns}
        for prop in properties:
            if (column := by_name.get(physical_name(prop))) is not None:
                _refresh_column_types(prop, column)
                if column.pii_flag is not None:
                    _set_custom_property(prop, PROFILED_VALUES, None)
                if profiling:
                    _refresh_column_profiling(prop, column)
                if catalog_metadata:
                    _refresh_column_catalog_metadata(prop, column, table)

        if profiling:
            _refresh_primary_key(properties, columns)

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


def fill_profiled_values(
    document: dict, table_groups_id: UUID, profile_run_id: UUID, table_names: list[str]
) -> None:
    """Refresh each declared column's ``profiledValues`` from the profiling run.

    The values follow the column's ``logicalType``: the observed minimum and maximum for a number,
    integer, date or timestamp, and the observed shortest and longest length for a string. A column
    the data catalog excludes or flags PII gets none and loses any it holds, whatever its markers
    say; the excluded and PII markers decide only for a column the catalog no longer holds. Values
    the run no longer supplies are removed; a column the run has no results for is left as it is.
    The entry's description dates the run.
    """
    session = get_current_session()
    catalog_withheld = {
        (row.table_name, row.column_name): _withholds_profiled_values(row)
        for row in session.execute(
            select(
                DataColumnChars.table_name,
                DataColumnChars.column_name,
                DataColumnChars.excluded_data_element,
                DataColumnChars.pii_flag,
            )
            .where(
                DataColumnChars.table_groups_id == table_groups_id,
                DataColumnChars.table_name.in_(table_names),
                DataColumnChars.drop_date.is_(None),
            )
        )
    }
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
        table_name = physical_name(table)
        if table_name not in table_names:
            continue
        for prop in table.get("properties") or []:
            column_key = (table_name, physical_name(prop))
            withheld = catalog_withheld.get(column_key, is_excluded(prop) or is_pii(prop))
            if withheld:
                _set_custom_property(prop, PROFILED_VALUES, None)
                continue
            profile = profiles.get(column_key)
            if profile is None:
                continue
            logical_type = prop.get("logicalType")
            values = {}
            for key, field in _PROFILED_VALUE_SOURCES.get(logical_type, ()):
                if (value := _profiled_value(logical_type, getattr(profile, field, None))) is not None:
                    values[key] = value
            _set_custom_property(prop, PROFILED_VALUES, values or None, description)
