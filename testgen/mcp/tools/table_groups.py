"""MCP tools for table groups — create, update, append tables, preview.

Each tool gates on the ``edit`` permission. Validation and target-DB
introspection are delegated to ``testgen.common.database.table_group_service``
so the rules and SQL paths stay in one place.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field
from sqlalchemy.exc import IntegrityError

from testgen.common.database.table_group_service import (
    SchemaMoveRefused,
    apply_table_group_flavor_rules,
    catalog_membership,
    is_duplicate_name_error,
    move_table_group_schema,
    update_catalog_for_edit,
    validate_table_group_fields,
    validate_table_naming,
    write_table_group_catalog,
)
from testgen.common.database.table_group_service import (
    preview_table_group as preview_table_group_service,
)
from testgen.common.file_declaration_schema import FileDeclarationSpec
from testgen.common.flavors import declares_files, table_group_schema_label
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup, table_group_defaults
from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_flavor_label,
    format_page_footer,
    format_page_info,
    render_diff_table,
    report_no_change,
    resolve_connection,
    resolve_table_group,
    target_db_error_text,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc, format_boolean
from testgen.utils import friendly_score

_DOC_GROUP = DocGroup.MANAGE

_DUPLICATE_NAME_MESSAGE = "A Table Group with the same name already exists."
_FIELD_NAMES = {
    "table_group_schema": "schema",
    "profiling_include_mask": "include_mask",
    "profiling_exclude_mask": "exclude_mask",
}
_PII_FLAG_DENIED_MESSAGE = (
    "Changing PII detection requires permission to view PII. "
    "Leave this setting unchanged or contact your administrator."
)
_TABLE_COMPARISON_DESCRIPTION = (
    "Whether profiling collects value hashes, which Table Comparison test generation needs for tests that "
    "detect changed, moved, or swapped values. Adds profiling time. Has no effect on SAP HANA and Salesforce "
    "Data 360 connections."
)


class FileDeclaration(FileDeclarationSpec):
    """One table on a file connection, named by the path its rows come from."""


def _verify_table_naming(
    connection: Connection,
    *,
    schema: str | None,
    file_declarations: list[FileDeclaration] | None,
    criteria: tuple[object, ...] = (),
    require: bool = True,
) -> None:
    """Raise ``MCPUserError`` when the arguments name tables in a way this connection does not use."""
    errors = validate_table_naming(
        connection,
        schema=schema,
        file_declarations=file_declarations,
        criteria=criteria,
        require=require,
        field_names=_FIELD_NAMES,
    )
    if errors:
        raise MCPUserError(errors[0])


@with_database_session
@mcp_permission("view")
def list_table_groups(
    project_code: Annotated[str | None, Field(description="List groups in a project.")] = None,
    connection_id: Annotated[int | None, Field(description="List groups on a specific connection.")] = None,
    page: Annotated[int, Field(description="Page number starting at 1 (default 1).")] = 1,
    limit: Annotated[int, Field(description="Page size (default 20, max 100).")] = 20,
) -> str:
    """List table groups in a project or on a specific connection.

    Pass exactly one of `project_code` or `connection_id`. Returns each group's
    table count, last profile / test timestamps, and current quality score.
    """
    if (project_code is None) == (connection_id is None):
        raise MCPUserError("Pass either `project_code` or `connection_id`, not both.")
    validate_page(page)
    validate_limit(limit, 100)

    perms = get_project_permissions()
    if project_code is not None:
        perms.verify_access(project_code, not_found=MCPResourceNotAccessible("Project", project_code))
        rows, total = TableGroup.list_for_project(project_code, page=page, limit=limit)
        heading = f"Table groups for project `{project_code}`"
    else:
        connection = resolve_connection(connection_id)
        rows, total = TableGroup.list_for_connection(connection.connection_id, page=page, limit=limit)
        heading = f"Table groups on connection `{connection.connection_name}` (`{connection.connection_id}`)"

    if not rows:
        if page > 1:
            return f"No table groups on page {page} (total: {total})."
        return f"{heading} — none found."

    doc = MdDoc()
    doc.heading(1, heading)
    doc.text(format_page_info(total, page, limit))
    # Rows can span connections, so the schema column carries whatever the listed ones call
    # theirs, and is dropped only when none of them reports one.
    schema_labels = [table_group_schema_label(row.sql_flavor_code) for row in rows]
    schema_header = " / ".join(sorted({label for label in schema_labels if label}))
    table_rows: list[list[object]] = []
    for row, schema_label in zip(rows, schema_labels, strict=True):
        table_row: list[object] = [
            str(row.id),
            row.table_groups_name,
            row.connection_name,
            row.table_count,
            row.column_count,
            row.row_count,
            row.last_profiled_date,
            row.last_tested_date,
            friendly_score(row.quality_score),
        ]
        if schema_header:
            table_row.insert(3, row.table_group_schema if schema_label else None)
        table_rows.append(table_row)
    headers = ["ID", "Name", "Connection", "Tables", "Columns", "Rows", "Last profiled", "Last tested", "Quality Score"]
    if schema_header:
        headers.insert(3, schema_header)
    doc.table(headers, table_rows, code=[0, 3] if schema_header else [0])
    if footer := format_page_footer(total, page, limit):
        doc.text(footer)
    return doc.render()


@with_database_session
@mcp_permission("view")
def get_table_group(
    table_group_id: Annotated[
        str,
        Field(description="The table group UUID, e.g. from `list_table_groups` or `get_data_inventory`."),
    ],
) -> str:
    """Get a table group's full configuration.
    Returns filters, sampling, profiling flags, catalog tags, and recent activity.
    Use this before editing a table group or generating tests.
    """
    table_group = resolve_table_group(table_group_id)
    # Defense in depth: route through resolve_connection (perm-scoped) rather than Connection.get.
    connection = resolve_connection(table_group.connection_id) if table_group.connection_id else None

    doc = MdDoc()
    doc.heading(1, f"Table group `{table_group.table_groups_name}`")
    doc.field("ID", str(table_group.id), code=True)
    doc.field("Project", table_group.project_code, code=True)
    if connection is not None:
        doc.field(
            "Connection",
            f"{connection.connection_name} (`{connection.connection_id}`, {format_flavor_label(connection.sql_flavor_code)})",
        )
    declares_its_files = connection is not None and declares_files(connection.sql_flavor_code)
    if schema_label := table_group_schema_label(connection.sql_flavor_code if connection else None):
        doc.field(schema_label, table_group.table_group_schema, code=True)
    if table_group.description:
        doc.field("Description", table_group.description)

    if declares_its_files:
        doc.heading(2, "Declared tables")
        _render_declared_tables(doc, table_group)

    doc.heading(2, "Criteria")
    if table_group.profiling_table_set:
        doc.field(_DIFF_LABELS["profiling_table_set"], table_group.profiling_table_set, code=True)
    if table_group.profiling_include_mask:
        doc.field(_DIFF_LABELS["profiling_include_mask"], table_group.profiling_include_mask, code=True)
    if table_group.profiling_exclude_mask:
        doc.field(_DIFF_LABELS["profiling_exclude_mask"], table_group.profiling_exclude_mask, code=True)
    doc.field(_DIFF_LABELS["profile_id_column_mask"], table_group.profile_id_column_mask, code=True)
    doc.field(_DIFF_LABELS["profile_sk_column_mask"], table_group.profile_sk_column_mask, code=True)

    doc.heading(2, "Settings")
    doc.field(_DIFF_LABELS["profile_flag_cdes"], table_group.profile_flag_cdes)
    doc.field(_DIFF_LABELS["profile_flag_pii"], table_group.profile_flag_pii)
    doc.field(_DIFF_LABELS["profile_exclude_xde"], table_group.profile_exclude_xde)
    doc.field(_DIFF_LABELS["profile_table_comparison"], table_group.profile_table_comparison)
    doc.field(_DIFF_LABELS["include_in_dashboard"], table_group.include_in_dashboard)
    doc.field(_DIFF_LABELS["profiling_delay_days"], table_group.profiling_delay_days)

    doc.heading(2, "Sampling parameters")
    doc.field(_DIFF_LABELS["profile_use_sampling"], table_group.profile_use_sampling)
    if table_group.profile_use_sampling:
        doc.field(_DIFF_LABELS["profile_sample_percent"], table_group.profile_sample_percent)
        doc.field(_DIFF_LABELS["profile_sample_min_count"], table_group.profile_sample_min_count)

    if any(getattr(table_group, attr, None) for attr in _CATALOG_ATTRS):
        doc.heading(2, "Catalog tags")
        for attr in _CATALOG_ATTRS:
            value = getattr(table_group, attr, None)
            if value:
                doc.field(_DIFF_LABELS[attr], value)

    if table_group.dq_score_testing is not None or table_group.dq_score_profiling is not None:
        doc.heading(2, "Latest activity")
        if (profiling := friendly_score(table_group.dq_score_profiling)) is not None:
            doc.field("Profiling Score", profiling)
        if (testing := friendly_score(table_group.dq_score_testing)) is not None:
            doc.field("Testing Score", testing)
        if (quality := friendly_score(table_group.quality_score)) is not None:
            doc.field("Quality Score", quality)

    return doc.render()


@with_database_session
@mcp_permission("edit")
def create_table_group(
    connection_id: Annotated[int, Field(description="Bigint connection ID, e.g. from ``get_data_inventory``.")],
    table_group_name: Annotated[
        str,
        Field(description="3-40 character display name. Must be unique within the project."),
    ],
    schema: Annotated[
        str | None,
        Field(
            description="Schema name on the target database, e.g. ``public``. On a Salesforce Data 360 connection, "
            "the data space name. Omit on a connection whose tables are files, which has no schema to choose.",
        ),
    ] = None,
    *,
    file_declarations: Annotated[
        list[FileDeclaration] | None,
        Field(
            description="One entry per table. Required on a file connection, where the tables are named here "
            "instead of read from a schema. Rejected on every other connection.",
        ),
    ] = None,
    description: Annotated[str | None, Field(description="Optional free-text description.")] = None,
    table_set: Annotated[
        list[str] | None,
        Field(description="Explicit list of table names. The include and exclude masks still apply to them."),
    ] = None,
    include_mask: Annotated[
        str | None,
        Field(
            description="Comma-separated SQL LIKE patterns to include (e.g. ``fact_%,dim_%``)."
            " Omit for the default include mask."
        ),
    ] = None,
    exclude_mask: Annotated[
        str | None,
        Field(
            description="Comma-separated SQL LIKE patterns to exclude. Omit for the default exclude mask;"
            " pass an empty string to exclude nothing."
        ),
    ] = None,
    profile_id_column_mask: Annotated[
        str | None,
        Field(description="SQL LIKE pattern marking ID columns. Omit for the default ID column mask."),
    ] = None,
    profile_sk_column_mask: Annotated[
        str | None,
        Field(description="SQL LIKE pattern marking surrogate-key columns. Omit for the default SK column mask."),
    ] = None,
    profile_use_sampling: Annotated[
        bool | None,
        Field(description="Whether to sample large tables during profiling."),
    ] = None,
    profile_sample_percent: Annotated[int | None, Field(description="Sample size as a percent (1-100).")] = None,
    profile_sample_min_count: Annotated[int | None, Field(description="Minimum row count when sampling.")] = None,
    profiling_delay_days: Annotated[
        int | None,
        Field(description="Number of days to wait before new profiling will be available to generate tests."),
    ] = None,
    profile_flag_cdes: Annotated[
        bool | None,
        Field(description="Whether profiling flags Critical Data Elements."),
    ] = None,
    profile_flag_pii: Annotated[
        bool | None,
        Field(description="Whether profiling flags Personally Identifiable Information."),
    ] = None,
    profile_exclude_xde: Annotated[
        bool | None,
        Field(description="Whether profiling excludes columns flagged as excluded data elements."),
    ] = None,
    profile_table_comparison: Annotated[
        bool | None,
        Field(description=_TABLE_COMPARISON_DESCRIPTION + " Default false."),
    ] = None,
    include_in_dashboard: Annotated[
        bool | None,
        Field(description="Whether the table group appears on the project dashboard."),
    ] = None,
    add_scorecard: Annotated[
        bool,
        Field(description="Whether to add a scorecard for the table group to the Quality Dashboard."),
    ] = True,
    data_source: Annotated[str | None, Field(description="Catalog tag — original source of the dataset.")] = None,
    source_system: Annotated[
        str | None,
        Field(description="Catalog tag — enterprise system source for the dataset."),
    ] = None,
    source_process: Annotated[
        str | None,
        Field(description="Catalog tag — process, program, or data flow that produced the dataset."),
    ] = None,
    data_location: Annotated[
        str | None,
        Field(
            description="Catalog tag — physical or virtual location of the dataset (e.g. ``Headquarters``, ``Cloud``).",
        ),
    ] = None,
    business_domain: Annotated[
        str | None,
        Field(
            description="Catalog tag — business division responsible for the dataset (e.g. ``Finance``, ``Sales``, "
            "``Manufacturing``).",
        ),
    ] = None,
    stakeholder_group: Annotated[
        str | None,
        Field(description="Catalog tag — data owners or stakeholders responsible for the dataset."),
    ] = None,
    transform_level: Annotated[
        str | None,
        Field(
            description="Catalog tag — data warehouse processing stage (e.g. ``Raw``, ``Conformed``, ``Processed``, "
            "``Reporting``) or Medallion level (``bronze``, ``silver``, ``gold``).",
        ),
    ] = None,
    data_product: Annotated[
        str | None,
        Field(description="Catalog tag — data domain that comprises the dataset."),
    ] = None,
    data_classification: Annotated[
        str | None,
        Field(
            description="Catalog tag — information classification level of the dataset (e.g. ``Public``, ``Internal``, "
            "``Confidential``, ``Restricted``).",
        ),
    ] = None,
) -> str:
    """Create a table group on an existing connection, by schema or by file path.

    The table group inherits its project from the connection. ``include_mask``
    and ``exclude_mask`` are SQL ``LIKE`` patterns (e.g. ``fact_%,dim_%``);
    ``table_set`` is an explicit list. All filters compose with ``AND``. A file connection takes
    ``file_declarations`` instead of any of those, and no ``schema``.
    """
    connection = resolve_connection(connection_id)
    _verify_table_naming(
        connection,
        schema=schema,
        file_declarations=file_declarations,
        criteria=(table_set, include_mask, exclude_mask),
    )

    table_group = TableGroup(
        project_code=connection.project_code,
        connection_id=connection.connection_id,
        table_groups_name=table_group_name,
        table_group_schema=schema,
        file_declarations=(
            [declaration.to_payload() for declaration in file_declarations] if file_declarations else None
        ),
        **table_group_defaults(),
    )
    _apply_args_to_table_group(
        table_group,
        description=description,
        table_set=table_set,
        include_mask=include_mask,
        exclude_mask=exclude_mask,
        profile_id_column_mask=profile_id_column_mask,
        profile_sk_column_mask=profile_sk_column_mask,
        profile_use_sampling=profile_use_sampling,
        profile_sample_percent=profile_sample_percent,
        profile_sample_min_count=profile_sample_min_count,
        profiling_delay_days=profiling_delay_days,
        profile_flag_cdes=profile_flag_cdes,
        profile_flag_pii=profile_flag_pii,
        profile_exclude_xde=profile_exclude_xde,
        profile_table_comparison=profile_table_comparison,
        include_in_dashboard=include_in_dashboard,
        data_source=data_source,
        source_system=source_system,
        source_process=source_process,
        data_location=data_location,
        business_domain=business_domain,
        stakeholder_group=stakeholder_group,
        transform_level=transform_level,
        data_product=data_product,
        data_classification=data_classification,
    )

    apply_table_group_flavor_rules(table_group, connection)
    errors = validate_table_group_fields(table_group, connection, field_names=_FIELD_NAMES)
    if errors:
        _raise_validation_error(errors, "Table group creation rejected. No changes saved.")

    try:
        table_group.save(add_scorecard_definition=add_scorecard)
    except IntegrityError as err:
        _maybe_raise_duplicate_name(err)
        raise

    catalog_error = write_table_group_catalog(table_group, connection)
    return _render_created_table_group(table_group, connection, catalog_error)


@with_database_session
@mcp_permission("edit")
def update_table_group(
    table_group_id: Annotated[str, Field(description="UUID of the table group to update.")],
    *,
    table_group_name: Annotated[
        str | None,
        Field(description="New display name (3-40 chars). Must be unique within the project."),
    ] = None,
    schema: Annotated[
        str | None,
        Field(
            description="New schema name on the target database. On a Salesforce Data 360 connection, the data "
            "space name. Rejected if the table group has been used.",
        ),
    ] = None,
    file_declarations: Annotated[
        list[FileDeclaration] | None,
        Field(
            description="File connections only. Replaces the table group's whole list of tables, so send every "
            "table to keep, not just the ones that changed.",
        ),
    ] = None,
    description: Annotated[str | None, Field(description="Free-text description.")] = None,
    table_set: Annotated[
        list[str] | None,
        Field(description="Replacement explicit table list (full replacement of the current list)."),
    ] = None,
    include_mask: Annotated[str | None, Field(description="Comma-separated SQL LIKE patterns to include.")] = None,
    exclude_mask: Annotated[str | None, Field(description="Comma-separated SQL LIKE patterns to exclude.")] = None,
    profile_id_column_mask: Annotated[str | None, Field(description="SQL LIKE pattern marking ID columns.")] = None,
    profile_sk_column_mask: Annotated[
        str | None,
        Field(description="SQL LIKE pattern marking surrogate-key columns."),
    ] = None,
    profile_use_sampling: Annotated[
        bool | None,
        Field(description="Whether to sample large tables during profiling."),
    ] = None,
    profile_sample_percent: Annotated[int | None, Field(description="Sample size as a percent (1-100).")] = None,
    profile_sample_min_count: Annotated[int | None, Field(description="Minimum row count when sampling.")] = None,
    profiling_delay_days: Annotated[
        int | None,
        Field(description="Number of days to wait before new profiling will be available to generate tests."),
    ] = None,
    profile_flag_cdes: Annotated[bool | None, Field(description="Whether profiling flags CDEs.")] = None,
    profile_flag_pii: Annotated[bool | None, Field(description="Whether profiling flags PII.")] = None,
    profile_exclude_xde: Annotated[bool | None, Field(description="Whether profiling excludes XDE columns.")] = None,
    profile_table_comparison: Annotated[bool | None, Field(description=_TABLE_COMPARISON_DESCRIPTION)] = None,
    include_in_dashboard: Annotated[
        bool | None,
        Field(description="Whether the table group appears on the project dashboard."),
    ] = None,
    data_source: Annotated[str | None, Field(description="Catalog tag — original source of the dataset.")] = None,
    source_system: Annotated[
        str | None,
        Field(description="Catalog tag — enterprise system source for the dataset."),
    ] = None,
    source_process: Annotated[
        str | None,
        Field(description="Catalog tag — process, program, or data flow that produced the dataset."),
    ] = None,
    data_location: Annotated[
        str | None,
        Field(
            description="Catalog tag — physical or virtual location of the dataset (e.g. ``Headquarters``, ``Cloud``).",
        ),
    ] = None,
    business_domain: Annotated[
        str | None,
        Field(
            description="Catalog tag — business division responsible for the dataset (e.g. ``Finance``, ``Sales``, "
            "``Manufacturing``).",
        ),
    ] = None,
    stakeholder_group: Annotated[
        str | None,
        Field(description="Catalog tag — data owners or stakeholders responsible for the dataset."),
    ] = None,
    transform_level: Annotated[
        str | None,
        Field(
            description="Catalog tag — data warehouse processing stage (e.g. ``Raw``, ``Conformed``, ``Processed``, "
            "``Reporting``) or Medallion level (``bronze``, ``silver``, ``gold``).",
        ),
    ] = None,
    data_product: Annotated[
        str | None,
        Field(description="Catalog tag — data domain that comprises the dataset."),
    ] = None,
    data_classification: Annotated[
        str | None,
        Field(
            description="Catalog tag — information classification level of the dataset (e.g. ``Public``, ``Internal``, "
            "``Confidential``, ``Restricted``).",
        ),
    ] = None,
) -> str:
    """Update fields on an existing table group. Atomic — no partial save.

    Connection and project are immutable — delete and recreate the table group
    to re-parent it. When ``schema`` changes, profiling, test generation, monitors, and test runs
    read the new schema, and tests keep their history. Referential tests keep the schema of their
    second table. The change is refused when the schema
    cannot be read, when no table in it matches the table group's table filters, or while a job
    for the table group is running. The result lists tables the new schema does not have. On a
    file connection, ``schema`` cannot be changed, and ``file_declarations`` replaces the whole
    table list — read the current one with ``get_table_group`` first.
    """
    supplied = {
        "table_group_name": table_group_name,
        "schema": schema,
        "file_declarations": file_declarations,
        "description": description,
        "table_set": table_set,
        "include_mask": include_mask,
        "exclude_mask": exclude_mask,
        "profile_id_column_mask": profile_id_column_mask,
        "profile_sk_column_mask": profile_sk_column_mask,
        "profile_use_sampling": profile_use_sampling,
        "profile_sample_percent": profile_sample_percent,
        "profile_sample_min_count": profile_sample_min_count,
        "profiling_delay_days": profiling_delay_days,
        "profile_flag_cdes": profile_flag_cdes,
        "profile_flag_pii": profile_flag_pii,
        "profile_exclude_xde": profile_exclude_xde,
        "profile_table_comparison": profile_table_comparison,
        "include_in_dashboard": include_in_dashboard,
        "data_source": data_source,
        "source_system": source_system,
        "source_process": source_process,
        "data_location": data_location,
        "business_domain": business_domain,
        "stakeholder_group": stakeholder_group,
        "transform_level": transform_level,
        "data_product": data_product,
        "data_classification": data_classification,
    }
    if all(value is None for value in supplied.values()):
        raise MCPUserError("No fields supplied to update.")

    table_group = resolve_table_group(table_group_id)
    connection = Connection.get(table_group.connection_id)
    if connection is not None:
        # An update settles one field at a time, so how this table group names its tables is
        # already decided; only a change that contradicts it is worth refusing.
        _verify_table_naming(
            connection,
            schema=schema,
            file_declarations=file_declarations,
            criteria=(table_set, include_mask, exclude_mask),
            require=False,
        )

    schema_label = table_group_schema_label(connection.sql_flavor_code if connection else None)

    moving_to = schema if schema is not None and schema != table_group.table_group_schema else None

    if (
        profile_flag_pii is not None
        and profile_flag_pii != table_group.profile_flag_pii
        and not get_project_permissions().has_permission("view_pii", table_group.project_code)
    ):
        raise MCPPermissionDenied(_PII_FLAG_DENIED_MESSAGE)

    before = _snapshot(table_group)
    membership_before = catalog_membership(table_group)
    _apply_args_to_table_group(table_group, **{k: v for k, v in supplied.items() if k != "schema"})

    apply_table_group_flavor_rules(table_group, connection)
    errors = validate_table_group_fields(table_group, connection, field_names=_FIELD_NAMES)
    if errors:
        _raise_validation_error(errors, "Update rejected. No changes saved.")

    move = None
    if moving_to:
        try:
            move = move_table_group_schema(table_group, moving_to)
        except SchemaMoveRefused as refusal:
            raise MCPUserError(refusal.message) from refusal

    after = _snapshot(table_group)

    doc = MdDoc()
    doc.heading(1, f"Table Group `{table_group.table_groups_name}` updated")
    doc.field("ID", str(table_group.id), code=True)

    diff_attrs, diff_labels = _diff_shape(schema_label)
    rendered = render_diff_table(doc, before, after, attrs=diff_attrs, labels=diff_labels)
    if not rendered:
        return report_no_change(doc)

    try:
        table_group.save()
    except IntegrityError as err:
        _maybe_raise_duplicate_name(err)
        raise

    catalog_error = update_catalog_for_edit(table_group, membership_before, move, connection)
    if move:
        doc.field("Test definitions updated", str(move.definitions_repointed))
        if move.missing_tables:
            doc.text(
                f"{len(move.missing_tables)} tables are not in `{move.schema}`. The next test run "
                "deactivates their tests, and the next monitor run deletes their monitors along with "
                "the thresholds they learned: "
                + ", ".join(f"`{name}`" for name in sorted(move.missing_tables))
            )
    if catalog_error:
        doc.text(
            "The data catalog could not be read from the target, so it keeps the tables it had "
            f"before this change until the table group is profiled or tested. {catalog_error}"
        )

    return doc.render()


@with_database_session
@mcp_permission("edit")
def preview_table_group(
    table_group_id: Annotated[str, Field(description="UUID of the table group.")],
    verify_access: Annotated[bool, Field(description="When True, probe read access on every matched table.")] = False,
    include_columns: Annotated[
        bool, Field(description="When True, also list every matched table's columns and column types.")
    ] = False,
) -> str:
    """Probe the data source for the tables a table group covers.

    On a database, these are the tables matching its filters; on a file data source, its declared files.

    Returns counts plus a per-table breakdown, and each table's columns with their types when
    ``include_columns`` is set. Does not save anything to the application database.
    """
    table_group = resolve_table_group(table_group_id)
    connection = Connection.get_by_table_group(table_group.id)
    if connection is None:
        raise MCPUserError("Cannot preview — the table group's connection is unavailable.")

    preview, _data_chars, _sql_generator = preview_table_group_service(
        table_group, connection=connection, verify_access=verify_access,
    )
    stats = preview["stats"]
    name = stats.get("table_groups_name") or table_group.table_groups_name

    doc = MdDoc()

    if not preview["success"]:
        if preview.get("message", "").startswith("No tables found matching the criteria"):
            doc.heading(1, f"Preview for table group `{name}` returned no tables")
            doc.text(preview["message"])
        else:
            doc.heading(1, f"Preview failed for table group `{name}`")
            doc.text(
                target_db_error_text(preview.get("message"))
                or "Preview failed for an unknown reason."
            )
        return doc.render()

    doc.heading(1, f"Preview for table group `{name}`")
    doc.field("Table Group ID", str(table_group.id), code=True)
    if schema_label := table_group_schema_label(connection.sql_flavor_code):
        doc.field(schema_label, stats.get("table_group_schema"), code=True)
    doc.field("Tables matched", stats.get("table_ct") or 0)
    doc.field("Total columns", stats.get("column_ct") or 0)
    if stats.get("approx_record_ct") is not None:
        doc.field("Approx rows", stats.get("approx_record_ct"))
    if stats.get("approx_data_point_ct") is not None:
        doc.field("Approx data points", stats.get("approx_data_point_ct"))

    has_files = declares_files(connection.sql_flavor_code)
    headers = ["Table", "Columns", "Approx Rows", "Approx Data Points"]
    if has_files:
        headers.insert(1, "Files")
    if verify_access:
        headers.append("Read Access")

    rows: list[list[object]] = []
    for table_name, info in preview["tables"].items():
        row: list[object] = [
            table_name,
            info.get("column_ct"),
            info.get("approx_record_ct"),
            info.get("approx_data_point_ct"),
        ]
        if has_files:
            row.insert(1, info.get("file_ct"))
        if verify_access:
            access = info.get("can_access")
            row.append("Yes" if access is True else "No" if access is False else "Unknown")
        rows.append(row)
    doc.table(headers, rows, code=[0])

    # A declaration that cannot be read is a row of zeroes above, indistinguishable from an empty
    # table, and a run does not stop for one. Naming it here is the only place it is reported.
    if failures := {
        table_name: info["error"]
        for table_name, info in preview["tables"].items()
        if info.get("error")
    }:
        doc.heading(2, "Tables that could not be read")
        for table_name, reason in sorted(failures.items()):
            doc.field(table_name, target_db_error_text(reason))
    elif preview.get("message"):
        doc.text(target_db_error_text(preview["message"]))

    if include_columns:
        doc.heading(2, "Columns")
        for table_name, info in preview["tables"].items():
            if columns := info.get("columns"):
                doc.heading(3, MdDoc.code(table_name))
                doc.table(
                    ["Column", "Type"],
                    [[column["column_name"], column["column_type"]] for column in columns],
                    code=[0],
                )

    return doc.render()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DIFF_ATTRS: tuple[str, ...] = (
    "table_groups_name",
    "table_group_schema",
    "file_declarations",
    "profiling_table_set",
    "profiling_include_mask",
    "profiling_exclude_mask",
    "profile_id_column_mask",
    "profile_sk_column_mask",
    "profile_use_sampling",
    "profile_sample_percent",
    "profile_sample_min_count",
    "profiling_delay_days",
    "profile_flag_cdes",
    "profile_flag_pii",
    "profile_exclude_xde",
    "profile_table_comparison",
    "include_in_dashboard",
    "description",
    "data_source",
    "source_system",
    "source_process",
    "data_location",
    "business_domain",
    "stakeholder_group",
    "transform_level",
    "data_product",
    "data_classification",
)

_DIFF_LABELS: dict[str, str] = {
    "table_groups_name": "Name",
    "table_group_schema": "Schema",
    "file_declarations": "Declared tables",
    "profiling_table_set": "Table set",
    "profiling_include_mask": "Include mask",
    "profiling_exclude_mask": "Exclude mask",
    "profile_id_column_mask": "ID column mask",
    "profile_sk_column_mask": "SK column mask",
    "profile_use_sampling": "Sampling",
    "profile_sample_percent": "Sample %",
    "profile_sample_min_count": "Sample min rows",
    "profiling_delay_days": "Min profiling age (days)",
    "profile_flag_cdes": "Flag CDEs",
    "profile_flag_pii": "Flag PII",
    "profile_exclude_xde": "Exclude XDE",
    "profile_table_comparison": "Profile for table comparison",
    "include_in_dashboard": "Include in dashboard",
    "description": "Description",
    "data_source": "Data source",
    "source_system": "Source system",
    "source_process": "Source process",
    "data_location": "Data location",
    "business_domain": "Business domain",
    "stakeholder_group": "Stakeholder group",
    "transform_level": "Transform level",
    "data_product": "Data product",
    "data_classification": "Data classification",
}


def _diff_shape(schema_label: str | None) -> tuple[tuple[str, ...], dict[str, str]]:
    """The diff attrs and labels, with the schema row named as the connection names it."""
    if schema_label is None:
        return tuple(attr for attr in _DIFF_ATTRS if attr != "table_group_schema"), _DIFF_LABELS
    return _DIFF_ATTRS, {**_DIFF_LABELS, "table_group_schema": schema_label}


_CATALOG_ATTRS: tuple[str, ...] = (
    "data_source",
    "source_system",
    "source_process",
    "data_location",
    "business_domain",
    "stakeholder_group",
    "transform_level",
    "data_product",
    "data_classification",
)


def _apply_args_to_table_group(
    table_group: TableGroup,
    *,
    table_group_name: str | None = None,
    schema: str | None = None,
    file_declarations: list[FileDeclaration] | None = None,
    description: str | None = None,
    table_set: list[str] | None = None,
    include_mask: str | None = None,
    exclude_mask: str | None = None,
    profile_id_column_mask: str | None = None,
    profile_sk_column_mask: str | None = None,
    profile_use_sampling: bool | None = None,
    profile_sample_percent: int | None = None,
    profile_sample_min_count: int | None = None,
    profiling_delay_days: int | None = None,
    profile_flag_cdes: bool | None = None,
    profile_flag_pii: bool | None = None,
    profile_exclude_xde: bool | None = None,
    profile_table_comparison: bool | None = None,
    include_in_dashboard: bool | None = None,
    data_source: str | None = None,
    source_system: str | None = None,
    source_process: str | None = None,
    data_location: str | None = None,
    business_domain: str | None = None,
    stakeholder_group: str | None = None,
    transform_level: str | None = None,
    data_product: str | None = None,
    data_classification: str | None = None,
) -> None:
    """Apply every non-None arg to its model field.

    Casts ``table_set: list[str]`` to comma-joined string, and casts
    integer args for columns the model stores as strings.
    """
    if table_group_name is not None:
        table_group.table_groups_name = table_group_name
    if schema is not None:
        table_group.table_group_schema = schema
    if file_declarations is not None:
        table_group.file_declarations = [declaration.to_payload() for declaration in file_declarations]
    if description is not None:
        table_group.description = description
    if table_set is not None:
        table_group.profiling_table_set = ",".join(table_set)
    if include_mask is not None:
        table_group.profiling_include_mask = include_mask
    if exclude_mask is not None:
        table_group.profiling_exclude_mask = exclude_mask
    if profile_id_column_mask is not None:
        table_group.profile_id_column_mask = profile_id_column_mask
    if profile_sk_column_mask is not None:
        table_group.profile_sk_column_mask = profile_sk_column_mask
    if profile_use_sampling is not None:
        table_group.profile_use_sampling = profile_use_sampling
    if profile_sample_percent is not None:
        table_group.profile_sample_percent = profile_sample_percent
    if profile_sample_min_count is not None:
        table_group.profile_sample_min_count = profile_sample_min_count
    if profiling_delay_days is not None:
        table_group.profiling_delay_days = profiling_delay_days
    if profile_flag_cdes is not None:
        table_group.profile_flag_cdes = profile_flag_cdes
    if profile_flag_pii is not None:
        table_group.profile_flag_pii = profile_flag_pii
    if profile_exclude_xde is not None:
        table_group.profile_exclude_xde = profile_exclude_xde
    if profile_table_comparison is not None:
        table_group.profile_table_comparison = profile_table_comparison
    if include_in_dashboard is not None:
        table_group.include_in_dashboard = include_in_dashboard
    if data_source is not None:
        table_group.data_source = data_source
    if source_system is not None:
        table_group.source_system = source_system
    if source_process is not None:
        table_group.source_process = source_process
    if data_location is not None:
        table_group.data_location = data_location
    if business_domain is not None:
        table_group.business_domain = business_domain
    if stakeholder_group is not None:
        table_group.stakeholder_group = stakeholder_group
    if transform_level is not None:
        table_group.transform_level = transform_level
    if data_product is not None:
        table_group.data_product = data_product
    if data_classification is not None:
        table_group.data_classification = data_classification


def _raise_validation_error(errors: list[str], header: str) -> None:
    bullets = "\n".join(f"- {err}" for err in errors)
    raise MCPUserError(f"{header}\n\n{bullets}")


def _maybe_raise_duplicate_name(err: IntegrityError) -> None:
    if is_duplicate_name_error(err):
        raise MCPUserError(_DUPLICATE_NAME_MESSAGE) from err


def _snapshot(table_group: TableGroup) -> dict[str, Any]:
    values = {attr: getattr(table_group, attr, None) for attr in _DIFF_ATTRS}
    values["file_declarations"] = _declaration_summary(values["file_declarations"])
    return values


def _render_declared_tables(doc: MdDoc, table_group: TableGroup) -> None:
    """One line per declared table, naming the path it reads and how it is read."""
    for declaration in table_group.file_declarations or []:
        options = declaration.get("options") or {}
        settings = "".join(f", {key}={_render_option(value)}" for key, value in sorted(options.items()))
        doc.field(
            str(declaration.get("name")),
            f"`{declaration.get('uri')}` ({declaration.get('format')}{settings})",
        )


def _render_option(value: object) -> str:
    return format_boolean(value) or str(value)


def _declaration_summary(declarations: list[dict[str, Any]] | None) -> str | None:
    """One line naming every declared table with its path, format and settings.

    Carries every stored field, so two lists that differ anywhere compare unequal.
    """
    if not declarations:
        return None
    lines = []
    for declaration in declarations:
        line = f"{declaration.get('name')} \u2192 {declaration.get('uri')} ({declaration.get('format')})"
        if options := declaration.get("options"):
            line += " " + ", ".join(f"{key}={_render_option(value)}" for key, value in sorted(options.items()))
        lines.append(line)
    return "; ".join(lines)


def _render_created_table_group(
    table_group: TableGroup, connection: Connection, catalog_error: str | None
) -> str:
    doc = MdDoc()
    doc.heading(1, f"Table Group `{table_group.table_groups_name}` created")
    doc.field("ID", str(table_group.id), code=True)
    doc.field("Project", table_group.project_code, code=True)
    doc.field(
        "Connection",
        f"{connection.connection_name} (`{connection.connection_id}`)",
    )
    if declares_files(connection.sql_flavor_code):
        doc.heading(2, "Declared tables")
        _render_declared_tables(doc, table_group)
    if schema_label := table_group_schema_label(connection.sql_flavor_code):
        doc.field(schema_label, table_group.table_group_schema, code=True)
    if table_group.description:
        doc.field("Description", table_group.description)

    if table_group.profiling_table_set:
        doc.field("Table set", table_group.profiling_table_set, code=True)
    if table_group.profiling_include_mask:
        doc.field("Include mask", table_group.profiling_include_mask, code=True)
    if table_group.profiling_exclude_mask:
        doc.field("Exclude mask", table_group.profiling_exclude_mask, code=True)

    doc.field("Profile sampling", "Yes" if table_group.profile_use_sampling else "No")
    if table_group.profile_use_sampling:
        doc.field("Sample %", table_group.profile_sample_percent)
        doc.field("Sample min rows", table_group.profile_sample_min_count)

    profile_flags = []
    if table_group.profile_flag_cdes:
        profile_flags.append("Flag CDEs")
    if table_group.profile_flag_pii:
        profile_flags.append("Flag PII")
    if table_group.profile_exclude_xde:
        profile_flags.append("Exclude XDE")
    if table_group.profile_table_comparison:
        profile_flags.append("Profile for table comparison")
    if profile_flags:
        doc.field("Profiling flags", ", ".join(profile_flags))

    doc.field("Min profiling age (days)", table_group.profiling_delay_days)
    doc.field("Include in dashboard", "Yes" if table_group.include_in_dashboard else "No")

    if any(getattr(table_group, attr, None) for attr in _CATALOG_ATTRS):
        doc.heading(2, "Catalog")
        for attr in _CATALOG_ATTRS:
            value = getattr(table_group, attr, None)
            if value:
                doc.field(_DIFF_LABELS[attr], value)

    if catalog_error:
        doc.text(
            "The data catalog could not be read from the target, so it is empty until the table group "
            f"is profiled or tested. {catalog_error}"
        )

    return doc.render()
