"""Shared table-group helpers — common-layer logic shared by MCP, the UI, and
any future caller:

* ``validate_table_group_fields`` — required-field + format checks. Callers
  surface the returned bullets verbatim.
* ``is_duplicate_name_error`` — recognizes the name-uniqueness violation.
* ``preview_table_group`` — schema-introspection preview. Returns
  ``(preview, data_chars, sql_generator)``; the ``save_data_chars`` callback
  is built by callers via ``make_save_data_chars``.

None of these belong on the ``TableGroup`` model: preview opens an external
DB connection (I/O against an arbitrary target system), and the field-required
rules are form-shaped per-flavor logic, not model invariants.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from testgen.commands.queries.refresh_data_chars_query import RefreshDataCharsSQL
from testgen.commands.run_refresh_data_chars import write_data_chars
from testgen.common.database.column_chars import ColumnChars, ObjectType
from testgen.common.database.database_service import get_flavor_service
from testgen.common.database.file_declarations import (
    NO_FILES_MATCHED,
    FileDeclaration,
    parse_file_declarations,
    validate_file_declarations,
)
from testgen.common.database.flavor.duckdb_flavor_service import base_location
from testgen.common.database.flavor.flavor_service import resolve_connection_params
from testgen.common.enums import JobStatus
from testgen.common.flavors import declares_files, fixed_table_group_schema, table_group_schema_label
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_table import DataTable
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.table_group import TableGroup, TableGroupMinimal, validate_schema_name
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.ui.services.database_service import target_db_session

LOG = logging.getLogger("testgen")

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_NAME_MIN = 3
_NAME_MAX = 40
_SAMPLE_PCT_MIN = 1
_SAMPLE_PCT_MAX = 100
_INTEGER_MAX = 2**31 - 1
_BIGINT_MAX = 2**63 - 1

# Widths of the ``table_groups`` VARCHAR columns (030_initialize_new_schema_structure.sql).
_MAX_LENGTHS: dict[str, int] = {
    "table_group_schema": 100,
    "profiling_table_set": 2000,
    "profiling_include_mask": 2000,
    "profiling_exclude_mask": 2000,
    "profile_id_column_mask": 2000,
    "profile_sk_column_mask": 150,
    "description": 1000,
    "data_source": 40,
    "source_system": 40,
    "source_process": 40,
    "data_location": 40,
    "business_domain": 40,
    "stakeholder_group": 40,
    "transform_level": 40,
    "data_product": 40,
    "data_classification": 40,
}
_LIST_COLUMNS = frozenset({"profiling_table_set", "profiling_include_mask", "profiling_exclude_mask"})

_PUBLIC_FIELD_NAMES: dict[str, str] = {
    "table_groups_name": "table_group_name",
    "table_group_schema": "schema_name",
    "profiling_table_set": "table_set",
    "profiling_include_mask": "include_masks",
    "profiling_exclude_mask": "exclude_masks",
}


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_int(value: object) -> bool:
    """``bool`` is an ``int`` subclass, so it needs excluding explicitly."""
    return isinstance(value, int) and not isinstance(value, bool)


def validate_table_group_fields(
    table_group: TableGroup,
    connection: Connection | None = None,
    *,
    field_names: Mapping[str, str] | None = None,
) -> list[str]:
    """Return every validation error (empty list = valid).

    Mirrors the per-field form validators on the UI ``Add Table Group`` wizard.

    Args:
        table_group: The table group to check.
        connection: The table group's connection. Pass it to have the file declarations
            checked, which needs the base location they are relative to.
        field_names: Name to show for a model attribute in the messages, keyed by
            attribute. Overrides the public field names, which the messages use by
            default; an attribute with no public name is shown by its own name.
    """
    names = {**_PUBLIC_FIELD_NAMES, **(field_names or {})}

    def field(attr: str) -> str:
        return f"`{names.get(attr, attr)}`"

    errors: list[str] = []

    name = table_group.table_groups_name
    if _missing(name):
        errors.append(f"{field('table_groups_name')} is required.")
    elif not (_NAME_MIN <= len(name.strip()) and len(name) <= _NAME_MAX):
        errors.append(f"{field('table_groups_name')} must be between {_NAME_MIN} and {_NAME_MAX} characters.")

    if connection is not None and declares_files(connection.sql_flavor_code):
        errors.extend(
            validate_file_declarations(
                table_group.file_declarations, base_location(connection.sql_flavor_code, connection.parameters)
            )
        )
    elif _missing(table_group.table_group_schema):
        errors.append(f"{field('table_group_schema')} is required.")

    for attr, max_length in _MAX_LENGTHS.items():
        value = getattr(table_group, attr)
        if isinstance(value, str) and len(value) > max_length:
            if attr in _LIST_COLUMNS:
                errors.append(
                    f"{field(attr)} must be at most {max_length} characters in total,"
                    " counting a comma between entries."
                )
            else:
                errors.append(f"{field(attr)} must be at most {max_length} characters.")

    delay = table_group.profiling_delay_days
    if not _is_int(delay) or delay < 0:
        errors.append(f"{field('profiling_delay_days')} must be a non-negative integer.")
    elif delay > _INTEGER_MAX:
        errors.append(f"{field('profiling_delay_days')} must be at most {_INTEGER_MAX}.")

    pct = table_group.profile_sample_percent
    if not _is_int(pct) or not (_SAMPLE_PCT_MIN <= pct <= _SAMPLE_PCT_MAX):
        errors.append(f"{field('profile_sample_percent')} must be between {_SAMPLE_PCT_MIN} and {_SAMPLE_PCT_MAX}.")

    min_count = table_group.profile_sample_min_count
    if not _is_int(min_count) or min_count < 0:
        errors.append(f"{field('profile_sample_min_count')} must be a non-negative integer.")
    elif min_count > _BIGINT_MAX:
        errors.append(f"{field('profile_sample_min_count')} must be at most {_BIGINT_MAX}.")

    return errors


def apply_table_group_flavor_rules(table_group: TableGroup, connection: Connection | None) -> None:
    """Settle the fields the connection's flavor decides rather than the user.

    A flavor that fixes its schema has the value written here instead of collected from a form
    that does not show the field. The two ways of naming tables are mutually exclusive, so
    whichever one the flavor does not use is cleared — moving a table group to another connection
    then leaves nothing stale behind to filter or declare with.
    """
    if connection is None:
        return

    schema = fixed_table_group_schema(connection.sql_flavor_code)
    if schema is not None:
        table_group.table_group_schema = schema

    if declares_files(connection.sql_flavor_code):
        table_group.profiling_table_set = None
        table_group.profiling_include_mask = None
        table_group.profiling_exclude_mask = None
    else:
        table_group.file_declarations = None


def is_duplicate_name_error(err: IntegrityError) -> bool:
    """Whether ``err`` is a violation of the table group name's per-project uniqueness."""
    return "table_groups_name_unique" in str(err.orig)


def apply_test_definition_flavor_rules(
    test_definition: TestDefinition,
    table_group: TableGroup | TableGroupMinimal,
    *,
    qualifies_table_refs: bool,
) -> None:
    """Settle the test-definition fields the connection's flavor decides rather than the user.

    Where the flavor does not qualify table references it reaches every table through one schema,
    so the reference table's schema is overwritten rather than defaulted: a definition arriving
    from an import or a copy carries the source's schema, which names nothing reachable on the
    target. Where the flavor does qualify, only a blank is filled.

    ``match_table_name`` is what marks a definition as referential.
    """
    if not test_definition.match_table_name:
        return

    if not qualifies_table_refs or not test_definition.match_schema_name:
        test_definition.match_schema_name = test_definition.schema_name or table_group.table_group_schema


def schema_label_for_table_group(table_group_id: str | UUID) -> str | None:
    """The name the table group's database type gives its schema, or None when it reports none."""
    connection = Connection.get_by_table_group(table_group_id)
    return table_group_schema_label(connection.sql_flavor_code if connection else None)


def table_group_qualifies_table_refs(table_group_id: str | UUID) -> bool:
    """Whether SQL against this table group names a table as ``schema.table``.

    Separate from the schema's label: a Data Space is reported to the user under its own name and
    still cannot qualify a table reference.
    """
    connection = Connection.get_by_table_group(table_group_id)
    if not connection:
        return True
    return get_flavor_service(connection.sql_flavor).qualifies_table_refs_with_schema(connection.sql_flavor_code)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


class StatsPreview(TypedDict, total=False):
    id: UUID | None
    table_groups_name: str
    table_group_schema: str
    schema_label: str | None
    table_ct: int | None
    column_ct: int | None
    approx_record_ct: int | None
    approx_data_point_ct: int | None


class PreviewColumn(TypedDict):
    column_name: str
    column_type: str | None


class TablePreview(TypedDict, total=False):
    column_ct: int
    approx_record_ct: int | None
    approx_data_point_ct: int | None
    can_access: bool | None
    # Filled in only for a flavor whose tables are declared as files.
    file_ct: int | None
    columns: list[PreviewColumn]
    error: str | None


class TableGroupPreview(TypedDict):
    stats: StatsPreview
    tables: dict[str, TablePreview]
    success: bool
    message: str | None


_NO_CONNECTION_MESSAGE = "No connection selected. Please select a connection to preview the Table Group."
_NO_TABLES_MESSAGE = (
    "No tables found matching the criteria. Please check the Table Group configuration"
    " or the database permissions."
)
_INACCESSIBLE_MESSAGE = "Some tables were not accessible. Check that TestGen has read access to them."
_NO_DECLARATIONS_READ_MESSAGE = (
    "None of the declared tables could be read. Check that the paths are correct and that the files"
    " are readable by TestGen."
)


def preview_table_group(
    table_group: TableGroup,
    *,
    connection: Connection | None = None,
    verify_access: bool = True,
) -> tuple[TableGroupPreview, list[ColumnChars] | None, RefreshDataCharsSQL | None]:
    """Probe the connected target DB for tables matching ``table_group``'s filters.

    Returns ``(preview, data_chars, sql_generator)`` — three picklable values.
    No connection and DDF failure blank the second and third tuple elements; an
    empty schema still returns the empty list and the generator, and is signalled
    only by ``preview["success"]``. Check ``success``, not the elements.

    Use ``make_save_data_chars(data_chars, sql_generator)`` in callers that
    need to record the introspected metadata in ``data_chars``.
    """
    preview: TableGroupPreview = {
        "stats": {
            "id": table_group.id,
            "table_groups_name": table_group.table_groups_name,
            "table_group_schema": table_group.table_group_schema,
        },
        "tables": {},
        "success": True,
        "message": None,
    }

    if not (connection or table_group.connection_id):
        preview["success"] = False
        preview["message"] = _NO_CONNECTION_MESSAGE
        return preview, None, None

    data_chars: list[ColumnChars] | None = None
    sql_generator: RefreshDataCharsSQL | None = None
    try:
        if connection is None:
            connection = Connection.get(table_group.connection_id)
        preview, data_chars, sql_generator = _build_preview(table_group, connection)

        if verify_access and preview["success"]:
            with target_db_session(connection, table_group) as run:
                for table_name in list(preview["tables"]):
                    # The probe query completing is the access signal — an unreadable table
                    # raises. Its result set is empty for an empty table, so row count says
                    # nothing about access.
                    try:
                        run(*sql_generator.verify_access(table_name))
                    except Exception:
                        preview["tables"][table_name]["can_access"] = False
                    else:
                        preview["tables"][table_name]["can_access"] = True
            if not all(t["can_access"] for t in preview["tables"].values()) and not preview["message"]:
                preview["message"] = _INACCESSIBLE_MESSAGE
    except Exception as error:
        preview["success"] = False
        preview["message"] = error.args[0] if error.args else str(error)
        data_chars = None
        sql_generator = None

    return preview, data_chars, sql_generator


def make_save_data_chars(
    data_chars: list[ColumnChars],
    sql_generator: RefreshDataCharsSQL,
) -> Callable[[UUID], None]:
    """Build the ``save_data_chars(table_group_id)`` callback for the caller.

    Kept out of ``preview_table_group`` so the service's return value stays
    picklable; local closures don't pickle.
    """
    def save(table_group_id: UUID) -> None:
        # Unsaved table groups won't have an ID yet; sync it before writing.
        sql_generator.table_group.id = table_group_id
        write_data_chars(data_chars, sql_generator, datetime.now(UTC))
    return save


def _build_preview(
    table_group: TableGroup,
    connection: Connection,
) -> tuple[TableGroupPreview, list[ColumnChars], RefreshDataCharsSQL]:
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    schema_label = table_group_schema_label(connection.sql_flavor_code)
    declaration_failures: dict[str, str] = {}
    if sql_generator.flavor_service.metadata_via_api:
        params = resolve_connection_params(connection.__dict__)
        api_columns = sql_generator.flavor_service.get_schema_columns(params, table_group.table_group_schema) or []
        data_chars = sql_generator.filter_schema_columns(api_columns)
    else:
        with target_db_session(connection, table_group) as run:
            rows = run(*sql_generator.get_schema_ddf())
            data_chars = [ColumnChars(**column) for column in rows]
            if declares_files(connection.sql_flavor_code):
                declaration_failures = run.declaration_failures
                file_count_map = {
                    row["table_name"]: row["file_ct"]
                    for query, params in sql_generator.get_file_counts()
                    for row in run(query, params)
                }
                for column in data_chars:
                    column.object_type = ObjectType.FILES
                    column.file_ct = file_count_map.get(column.table_name)

    preview: TableGroupPreview = {
        "stats": {
            "id": table_group.id,
            "table_groups_name": table_group.table_groups_name,
            "table_group_schema": table_group.table_group_schema if schema_label else None,
            "schema_label": schema_label,
            "table_ct": 0,
            "column_ct": 0,
            "approx_record_ct": None,
            "approx_data_point_ct": None,
        },
        "tables": {},
        "success": True,
        "message": None,
    }
    stats = preview["stats"]
    tables = preview["tables"]

    for column in data_chars:
        if not tables.get(column.table_name):
            tables[column.table_name] = {
                "column_ct": 0,
                "approx_record_ct": column.approx_record_ct,
                "approx_data_point_ct": None,
                "can_access": None,
                "file_ct": column.file_ct,
                "columns": [],
            }
            stats["table_ct"] += 1
            if column.approx_record_ct is not None:
                stats["approx_record_ct"] = (stats["approx_record_ct"] or 0) + column.approx_record_ct

        stats["column_ct"] += 1
        tables[column.table_name]["column_ct"] += 1
        tables[column.table_name]["columns"].append(
            {"column_name": column.column_name, "column_type": column.column_type}
        )
        if column.approx_record_ct is not None:
            stats["approx_data_point_ct"] = (stats["approx_data_point_ct"] or 0) + column.approx_record_ct
            tables[column.table_name]["approx_data_point_ct"] = (
                tables[column.table_name]["approx_data_point_ct"] or 0
            ) + column.approx_record_ct

    if declares_files(connection.sql_flavor_code):
        _add_declaration_detail(preview, sql_generator, data_chars, declaration_failures)
    elif len(data_chars) <= 0:
        preview["success"] = False
        preview["message"] = _NO_TABLES_MESSAGE

    return preview, data_chars, sql_generator


def _selected_declarations(sql_generator: RefreshDataCharsSQL) -> list[FileDeclaration]:
    """The declarations the table group's criteria would keep.

    A file table group saved through the product carries no criteria, so this is every
    declaration. One narrowed by hand still reports only on the tables it asked for, rather than
    calling the rest missing.
    """
    declarations = parse_file_declarations(sql_generator.table_group.file_declarations)
    probes = [
        ColumnChars(schema_name=sql_generator.table_group.table_group_schema, table_name=d.name, column_name="")
        for d in declarations
    ]
    kept = {column.table_name for column in sql_generator.filter_schema_columns(probes)}
    return [declaration for declaration in declarations if declaration.name in kept]


def _add_declaration_detail(
    preview: TableGroupPreview,
    sql_generator: RefreshDataCharsSQL,
    data_chars: list[ColumnChars],
    declaration_failures: dict[str, str],
) -> None:
    """Report every declaration, including the ones with no files behind them.

    A declaration whose files are missing has no view and therefore no columns, so it is absent
    from the catalog read rather than present and empty.
    """
    tables = preview["tables"]
    for table in tables.values():
        table["error"] = None

    failed = 0
    for declaration in _selected_declarations(sql_generator):
        if declaration.name in tables:
            continue
        failed += 1
        tables[declaration.name] = {
            "column_ct": 0,
            "approx_record_ct": None,
            "approx_data_point_ct": None,
            "can_access": None,
            "columns": [],
            "error": declaration_failures.get(declaration.name) or NO_FILES_MATCHED,
        }

    if not data_chars:
        preview["success"] = False
        preview["message"] = _NO_DECLARATIONS_READ_MESSAGE
    elif failed:
        noun = "table" if failed == 1 else "tables"
        preview["message"] = f"{failed} {noun} could not be read. Check the highlighted paths."


# ---------------------------------------------------------------------------
# Moving a table group to another schema
# ---------------------------------------------------------------------------

class SchemaMoveRefused(Exception):
    """The move cannot proceed. ``reason`` is a stable code; ``message`` is for the caller."""

    def __init__(self, reason: str, message: str, missing_tables: list[str] | None = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.missing_tables = missing_tables or []


@dataclass
class SchemaMove:
    """What a move did: where it went, and which catalogued tables the new schema lacks.

    ``refresh_catalog`` rewrites the catalog against the schema the move names. It is handed back
    rather than run, because it writes on its own connection and commits there and then -- see
    ``apply_schema_move``.
    """

    previous_schema: str
    schema: str
    missing_tables: list[str]
    definitions_repointed: int
    refresh_catalog: Callable[[UUID], None] | None = field(default=None, repr=False, compare=False)


def _tables_in_use(table_group_id: UUID) -> set[str]:
    """Table names the table group's catalog holds, ignoring ones already marked dropped."""
    session = get_current_session()
    rows = session.execute(
        select(DataTable.table_name).where(
            DataTable.table_groups_id == table_group_id,
            DataTable.drop_date.is_(None),
        )
    ).all()
    return {row[0] for row in rows}


def _has_job_in_flight(table_group: TableGroup) -> bool:
    """Whether any non-terminal job would read this table group's schema while it changes."""
    session = get_current_session()
    suite_ids = session.scalars(
        select(TestSuite.id).where(TestSuite.table_groups_id == table_group.id)
    ).all()
    named = [str(table_group.id), *[str(suite_id) for suite_id in suite_ids]]

    active = session.scalars(
        select(JobExecution.id).where(
            JobExecution.project_code == table_group.project_code,
            JobExecution.status.in_(list(JobStatus.active())),
            or_(
                JobExecution.kwargs["table_group_id"].astext.in_(named),
                JobExecution.kwargs["test_suite_id"].astext.in_(named),
                # Monitor generation names the suite under its own key, and profiling enqueues it
                # as a follow-up, so this is the job most likely to be in flight during a move.
                JobExecution.kwargs["monitor_suite_id"].astext.in_(named),
            ),
        )
    ).first()
    return active is not None


def _repoint_definitions(table_group: TableGroup, previous: str, schema: str) -> int:
    """Move the table group's stored test definitions onto ``schema``.

    Only each suite's resolved version is touched: a contract's frozen version is the agreement as
    it was signed, and reads the schema it named.

    ``match_schema_name`` is left alone. A referential test compares against a table this table
    group does not own, on whatever schema the author pointed it at, so moving this table group
    says nothing about where that one lives. A run that needs it elsewhere carries it.
    """
    session = get_current_session()
    suite_ids = session.scalars(
        select(TestSuite.id).where(TestSuite.table_groups_id == table_group.id)
    ).all()
    if not suite_ids:
        return 0

    scoped = and_(
        TestDefinition.test_suite_id.in_(suite_ids),
        TestDefinition.version_clause(),
    )
    result = session.execute(
        update(TestDefinition)
        .where(scoped, TestDefinition.schema_name == previous)
        .values(schema_name=schema)
    )
    return result.rowcount or 0


def move_table_group_schema(
    table_group: TableGroup,
    schema: str,
    *,
    connection: Connection | None = None,
) -> SchemaMove:
    """Point a table group, and everything that reads it, at another schema.

    Probes the target database first: a schema that carries none of the table group's tables is
    refused rather than moved into, since every later run would then find nothing. Tables the
    catalog holds that the new schema lacks are reported rather than refused — a build that
    genuinely dropped a table is a legitimate move — and the catalog reconciles them on the next
    refresh.

    Raises ``SchemaMoveRefused`` for a connection whose tables are not reached through a schema, an
    unusable name, a job already in flight, or a schema that matches nothing. Returns what moved.
    """
    previous = table_group.table_group_schema
    if schema == previous:
        return SchemaMove(previous_schema=previous, schema=schema, missing_tables=[], definitions_repointed=0)

    connection = connection or Connection.get(table_group.connection_id)
    flavor_code = connection.sql_flavor_code if connection else None
    if declares_files(flavor_code) or fixed_table_group_schema(flavor_code) is not None:
        raise SchemaMoveRefused(
            "schema_unsupported",
            "Tables on this connection are not reached through a schema, so there is nothing to move to.",
        )

    if error := validate_schema_name(schema):
        raise SchemaMoveRefused("invalid_schema_name", f"schema {error}.")

    if _has_job_in_flight(table_group):
        raise SchemaMoveRefused(
            "job_in_flight",
            "A job for this table group is still running. Wait for it to finish, then move the schema.",
        )

    probe = TableGroup(**{
        column.name: getattr(table_group, column.name) for column in TableGroup.__table__.columns
    })
    probe.table_group_schema = schema
    preview, data_chars, sql_generator = preview_table_group(probe, connection=connection)

    # An empty schema is reported as a failed preview too, so name that case before the general one
    # or the caller is told it could not be read when it was read and held nothing.
    if not preview["tables"]:
        raise SchemaMoveRefused(
            "schema_empty",
            f"No tables in {schema} match this table group's filters, so its tests would all fail.",
        )
    if not preview["success"]:
        raise SchemaMoveRefused("schema_unreadable", preview["message"] or "The schema could not be read.")

    missing = sorted(_tables_in_use(table_group.id) - set(preview["tables"]))

    table_group.table_group_schema = schema
    repointed = _repoint_definitions(table_group, previous, schema)

    return SchemaMove(
        previous_schema=previous,
        schema=schema,
        missing_tables=missing,
        definitions_repointed=repointed,
        refresh_catalog=(
            make_save_data_chars(data_chars, sql_generator) if data_chars and sql_generator else None
        ),
    )


def apply_schema_move(move: SchemaMove, table_group_id: UUID) -> None:
    """Make the move durable, then rewrite the catalog against the schema it names.

    The catalog is written on its own connection and commits there, so it cannot be undone by the
    caller rolling back. Running it before the move is durable would leave a catalog describing a
    schema that the table group and its test definitions do not name -- which reads as a full
    table drop-and-add to the schema-change monitors.

    A catalog that fails to write is recoverable: the next refresh rebuilds it.
    """
    get_current_session().commit()
    if move.refresh_catalog is None:
        return
    try:
        move.refresh_catalog(table_group_id)
    except Exception:
        LOG.exception("Catalog refresh after the schema move encountered errors")
