"""Shared table-group helpers — common-layer logic shared by MCP, the UI, and
any future caller:

* ``validate_table_group_fields`` — required-field + format checks. Callers
  surface the returned bullets verbatim.
* ``validate_table_naming`` — whether a table group names its tables the way its
  connection does: by schema, or by file declarations.
* ``is_duplicate_name_error`` — recognizes the name-uniqueness violation.
* ``preview_table_group`` — schema-introspection preview. Returns
  ``(preview, data_chars, sql_generator)``; the ``save_data_chars`` callback
  is built by callers via ``make_save_data_chars``.
* ``cascade_delete_table_group`` — deletes a table group and everything recorded
  against it, unless a job for it is still running.
* ``delete_blockers`` — the jobs that keep ``cascade_delete_table_group`` from
  deleting a table group, read without locking or canceling anything.

None of these belong on the ``TableGroup`` model: preview opens an external
DB connection (I/O against an arbitrary target system), and the field-required
rules are form-shaped per-flavor logic, not model invariants.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypedDict
from uuid import UUID

from sqlalchemy import or_, select, update
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
from testgen.common.enums import JobKey, JobStatus
from testgen.common.flavors import declares_files, fixed_table_group_schema, table_group_schema_label
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_table import DataTable
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup, TableGroupMinimal, validate_schema_name
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.common.run_overrides import MATCH_SCHEMA_OVERRIDE_UNSUPPORTED, SCHEMA_OVERRIDE_UNSUPPORTED
from testgen.ui.services.database_service import TargetQuery, target_db_session
from testgen.utils import get_exception_message

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
    elif error := validate_schema_name(table_group.table_group_schema or ""):
        # The same rule the move applies, so a table group cannot be created on a schema it could
        # never be moved to, nor on one wider than the catalog columns it has to land in.
        errors.append(f"{field('table_group_schema')} {error}.")

    for attr, max_length in _MAX_LENGTHS.items():
        value = getattr(table_group, attr)
        if isinstance(value, str) and len(value) > max_length:
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


def validate_table_naming(
    connection: Connection,
    *,
    schema: str | None,
    file_declarations: Sequence[object] | None,
    criteria: tuple[object, ...] = (),
    require: bool = True,
    field_names: Mapping[str, str] | None = None,
) -> list[str]:
    """Return every way the arguments name tables differently from how this connection does.

    A connection's tables are either files, declared one at a time, or a schema the target
    database already holds.

    Args:
        connection: The table group's connection.
        schema: The schema supplied, or None.
        file_declarations: The declarations supplied, or None.
        criteria: The table set, include mask and exclude mask supplied, each None when omitted.
        require: Also reject supplying neither a schema nor declarations.
        field_names: Name to show for a model attribute in the messages, as for
            ``validate_table_group_fields``.
    """
    names = {**_PUBLIC_FIELD_NAMES, **(field_names or {})}

    def field(attr: str) -> str:
        return f"`{names.get(attr, attr)}`"

    declarations = field("file_declarations")
    errors: list[str] = []
    if declares_files(connection.sql_flavor_code):
        if schema is not None:
            no_schema = "Tables on this connection are files, so it has no schema to choose."
            # Only on create. Telling an update to supply the declarations invites it to send a
            # partial list, and the field replaces the whole one.
            errors.append(f"{no_schema} Supply {declarations}." if require else no_schema)
        if any(value is not None for value in criteria):
            errors.append(
                f"Tables on this connection are files, so {field('profiling_table_set')}, "
                f"{field('profiling_include_mask')} and {field('profiling_exclude_mask')} do not apply. "
                f"Name the tables to read with {declarations}."
            )
        if require and not file_declarations:
            errors.append(
                f"Tables on this connection are declared one file or pattern at a time. Supply {declarations}."
            )
        return errors

    if file_declarations is not None:
        errors.append(
            f"{declarations} applies only to a connection whose tables are files. "
            f"Use {field('table_group_schema')} and the table filters instead."
        )
    if require and not schema:
        label = table_group_schema_label(connection.sql_flavor_code)
        holding = f" It names the {label.lower()} holding the tables." if label else ""
        errors.append(f"{field('table_group_schema')} is required for this connection.{holding}")
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


def unsupported_schema_override(
    table_group_id: str | UUID,
    *,
    schema_name: str | None = None,
    match_schema_name: str | None = None,
) -> str | None:
    """Return why a schema override does not apply to this table group's connection, else ``None``.

    Args:
        table_group_id: The table group the run reads.
        schema_name: The run's override of the table group's own schema, if given.
        match_schema_name: The run's override of referential tests' second schema, if given.

    Returns:
        The refusal message, or ``None`` when both overrides apply.
    """
    connection = Connection.get_by_table_group(table_group_id)
    if not connection:
        return None

    flavor_code = connection.sql_flavor_code
    # A pinned schema is not the user's to choose, and a flavor that does not qualify a table
    # reference with a schema has nowhere to put one.
    applies = (
        fixed_table_group_schema(flavor_code) is None
        and get_flavor_service(connection.sql_flavor).qualifies_table_refs_with_schema(flavor_code)
    )
    if applies:
        return None

    if schema_name:
        return SCHEMA_OVERRIDE_UNSUPPORTED
    if match_schema_name:
        return MATCH_SCHEMA_OVERRIDE_UNSUPPORTED
    return None


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
        preview, data_chars, sql_generator = _build_preview(table_group, connection, verify_access=verify_access)

        if verify_access and preview["success"]:
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


def _probe_access(run: TargetQuery, sql_generator: RefreshDataCharsSQL, table_names: Iterable[str]) -> dict[str, bool]:
    """Return whether each table can be read, keyed by table name."""
    access: dict[str, bool] = {}
    for table_name in table_names:
        # The probe query completing is the access signal — an unreadable table
        # raises. Its result set is empty for an empty table, so row count says
        # nothing about access.
        try:
            run(*sql_generator.verify_access(table_name))
        except Exception:
            access[table_name] = False
        else:
            access[table_name] = True
    return access


def _build_preview(
    table_group: TableGroup,
    connection: Connection,
    *,
    verify_access: bool,
) -> tuple[TableGroupPreview, list[ColumnChars], RefreshDataCharsSQL]:
    sql_generator = RefreshDataCharsSQL(connection, table_group)
    schema_label = table_group_schema_label(connection.sql_flavor_code)
    declaration_failures: dict[str, str] = {}
    access: dict[str, bool] | None = None
    if sql_generator.flavor_service.metadata_via_api:
        params = resolve_connection_params(connection.__dict__)
        api_columns = sql_generator.flavor_service.get_schema_columns(params, table_group.table_group_schema) or []
        data_chars = sql_generator.filter_schema_columns(api_columns)
        if verify_access:
            with target_db_session(connection, table_group) as run:
                access = _probe_access(run, sql_generator, dict.fromkeys(c.table_name for c in data_chars))
    else:
        with target_db_session(connection, table_group) as run:
            rows = run(*sql_generator.get_schema_ddf())
            data_chars = [ColumnChars(**column) for column in rows]
            if declares_files(connection.sql_flavor_code):
                declaration_failures = run.declaration_failures
                file_count_map = {}
                for query, params in sql_generator.get_file_counts(skip=declaration_failures):
                    try:
                        rows = run(query, params)
                    except Exception:
                        # A file that can be read but not listed, such as one in an object store the
                        # credentials cannot list, still previews; only its file count is unknown.
                        LOG.warning("Could not count the files of a declaration", exc_info=True)
                        continue
                    file_count_map.update({row["table_name"]: row["file_ct"] for row in rows})
                for column in data_chars:
                    column.object_type = ObjectType.FILES
                    column.file_ct = file_count_map.get(column.table_name)
            # In the same session, because on a file connection opening another rebuilds every view.
            if verify_access:
                access = _probe_access(run, sql_generator, dict.fromkeys(c.table_name for c in data_chars))

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

    if access is not None and preview["success"]:
        for table_name, table in tables.items():
            # A declaration whose view could not be built is listed without columns, and has no
            # view for a probe to read.
            table["can_access"] = access.get(table_name, False)

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


def _jobs_in_flight(table_group: TableGroup, *clauses) -> list[JobExecution]:
    """The non-terminal jobs that name this table group or one of its test suites, queued jobs
    included, oldest first.

    :param clauses: Further conditions on ``JobExecution`` that a job must meet to count.
    """
    session = get_current_session()
    suite_ids = session.scalars(
        select(TestSuite.id).where(TestSuite.table_groups_id == table_group.id)
    ).all()
    named = [str(table_group.id), *[str(suite_id) for suite_id in suite_ids]]

    return list(session.scalars(
        select(JobExecution).where(
            JobExecution.project_code == table_group.project_code,
            JobExecution.status.in_(list(JobStatus.active())),
            or_(
                JobExecution.kwargs["table_group_id"].astext.in_(named),
                JobExecution.kwargs["test_suite_id"].astext.in_(named),
                # Monitor generation names the suite under its own key, and profiling enqueues it
                # as a follow-up, so this is the job most likely to be in flight during a move.
                JobExecution.kwargs["monitor_suite_id"].astext.in_(named),
            ),
            *clauses,
        ).order_by(JobExecution.created_at)
    ).all())


def _has_job_in_flight(table_group: TableGroup, *clauses) -> bool:
    """Whether any non-terminal job names this table group or one of its test suites, queued jobs
    included.

    :param clauses: Further conditions on ``JobExecution`` that a job must meet to count.
    """
    return bool(_jobs_in_flight(table_group, *clauses))


def _repoint_definitions(table_group: TableGroup, previous: str, schema: str) -> int:
    """Move the table group's stored test definitions onto ``schema``.

    Every version is moved, frozen ones included. Where a contract's data is read is not one of
    the terms it froze -- a contract checks a deliverable that is rebuilt each cycle, so an
    agreement left reading the schema it was signed against would report every table missing from
    the next run on. The terms themselves are untouched.

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

    result = session.execute(
        update(TestDefinition)
        .where(
            TestDefinition.test_suite_id.in_(suite_ids),
            TestDefinition.schema_name == previous,
        )
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
            "Table groups on this connection have no schema to change.",
        )

    if error := validate_schema_name(schema):
        raise SchemaMoveRefused("invalid_schema_name", f"schema {error}.")

    if _has_job_in_flight(table_group):
        raise SchemaMoveRefused(
            "job_in_flight",
            "A job for this table group is still running. Wait for it to finish, then try again.",
        )

    probe = TableGroup(**{
        column.name: getattr(table_group, column.name) for column in TableGroup.__table__.columns
    })
    probe.table_group_schema = schema
    preview, data_chars, sql_generator = preview_table_group(probe, connection=connection)

    # An empty schema is reported as a failed preview too, so the two cases are told apart by what
    # the probe returned rather than by `success`: a schema that was read and held nothing comes
    # back with an empty list, one that could not be read at all with none.
    if data_chars is None:
        raise SchemaMoveRefused("schema_unreadable", preview["message"] or "The schema could not be read.")
    if not preview["tables"]:
        raise SchemaMoveRefused(
            "schema_empty",
            f"No tables in {schema} match this table group's table filters.",
        )

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


# Membership fields: the ones that decide which tables of the schema belong to a table group.
CATALOG_MEMBERSHIP_FIELDS = (
    "table_group_schema",
    "profiling_table_set",
    "profiling_include_mask",
    "profiling_exclude_mask",
    "file_declarations",
)


def catalog_membership(table_group: TableGroup) -> tuple:
    """The table group's membership fields, with every empty value read as ``None``.

    Forms post an empty string for a field the database holds as NULL, and both select the same tables.
    """
    return tuple(getattr(table_group, name) or None for name in CATALOG_MEMBERSHIP_FIELDS)


def write_table_group_catalog(table_group: TableGroup, connection: Connection | None = None) -> str | None:
    """Commit a saved table group, then write its data catalog from the tables the target holds now.

    The table group is committed before the target is read, so no app-database transaction stays open
    while the target lists its schema. The catalog is written on its own connection and commits there,
    which also needs the table group committed first.

    :param table_group: Saved table group.
    :param connection: The table group's connection, when the caller already has it.
    :returns: Why the catalog could not be read or written, or ``None`` when it was written.
    """
    get_current_session().commit()
    preview, data_chars, sql_generator = preview_table_group(table_group, connection=connection, verify_access=False)
    if not preview["success"] or not data_chars or sql_generator is None:
        return preview["message"] or "The target could not be read."

    try:
        make_save_data_chars(data_chars, sql_generator)(table_group.id)
    except Exception as error:
        LOG.exception("Data catalog write for table group %s encountered errors", table_group.id)
        return get_exception_message(error)
    return None


def update_catalog_for_edit(
    table_group: TableGroup,
    membership_before: tuple,
    move: SchemaMove | None,
    connection: Connection | None = None,
) -> str | None:
    """Bring a saved table group's data catalog in line with an edit to it.

    A schema move rewrites the catalog against the schema it names. Its probe ran with the edited
    filters applied, so that write also covers a filter change made in the same edit. Without a move,
    the catalog is rewritten when the edit changed which tables belong to the table group.

    :param table_group: Saved table group, with the edit applied.
    :param membership_before: ``catalog_membership`` of the table group before the edit.
    :param move: The schema move the edit made, if any.
    :param connection: The table group's connection, when the caller already has it.
    :returns: Why the catalog could not be read or written, or ``None`` when it was written or
        needed no change.
    """
    if move:
        return apply_schema_move(move, table_group.id)
    if membership_before != catalog_membership(table_group):
        return write_table_group_catalog(table_group, connection)
    return None


def apply_schema_move(move: SchemaMove, table_group_id: UUID) -> str | None:
    """Make the move durable, then rewrite the catalog against the schema it names.

    The catalog is written on its own connection and commits there, so it cannot be undone by the
    caller rolling back. Running it before the move is durable would leave a catalog describing a
    schema that the table group and its test definitions do not name -- which reads as a full
    table drop-and-add to the schema-change monitors.

    A catalog that fails to write is recoverable: the next refresh rebuilds it.

    :returns: Why the catalog could not be written, or ``None`` when it was written or the move
        carries no catalog to write.
    """
    get_current_session().commit()
    if move.refresh_catalog is None:
        return None
    try:
        move.refresh_catalog(table_group_id)
    except Exception as error:
        LOG.exception("Catalog refresh after the schema move encountered errors")
        return get_exception_message(error)
    return None


# ---------------------------------------------------------------------------
# Deleting a table group
# ---------------------------------------------------------------------------

class DeleteBlocker(StrEnum):
    """What keeps a table group from being deleted."""

    JOB = "job"
    CATALOG_REFRESH = "catalog_refresh"


def delete_blockers(table_group: TableGroup) -> list[JobExecution]:
    """The jobs that keep ``cascade_delete_table_group`` from deleting the table group, read without
    locking or canceling anything.

    :returns: Every queued or running job other than a catalog refresh that names the table group or
        one of its test suites, and every refresh of its catalog that has started. Empty when the
        delete would go ahead.
    """
    return [
        job
        for job in _jobs_in_flight(table_group)
        if job.job_key != JobKey.refresh_data_catalog or JobExecution.has_started(job.status, job.claimed_at)
    ]


def cascade_delete_table_group(table_group: TableGroup) -> DeleteBlocker | None:
    """Delete a table group with its test suites, runs, results, schedules, hygiene issues, and
    data catalog, unless a job for it is queued or running.

    Catalog refreshes for the table group that have not started are canceled rather than counted.

    :returns: Why nothing was deleted -- a job other than a catalog refresh names the table group
        or one of its test suites, or a refresh of its catalog has started -- or ``None`` once it
        is deleted.
    """
    if _has_job_in_flight(table_group, JobExecution.job_key != JobKey.refresh_data_catalog):
        return DeleteBlocker.JOB
    if not JobExecution.cancel_queued_catalog_refreshes(TableGroup, table_group.id):
        return DeleteBlocker.CATALOG_REFRESH
    TableGroup.cascade_delete([str(table_group.id)])
    return None


def save_new_table_group(table_group: TableGroup, *, add_scorecard: bool = False) -> ScoreDefinition | None:
    """Save a new table group, with a scorecard for it when ``add_scorecard``.

    :returns: the scorecard created, if any.
    """
    table_group.save()
    if not add_scorecard:
        return None
    scorecard = ScoreDefinition.from_table_group(table_group)
    scorecard.save()
    return scorecard
