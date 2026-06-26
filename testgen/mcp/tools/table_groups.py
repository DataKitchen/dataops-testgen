"""MCP tools for table groups — create, update, append tables, preview.

Each tool gates on the ``edit`` permission. Validation and target-DB
introspection are delegated to ``testgen.common.database.table_group_service``
so the rules and SQL paths stay in one place.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from testgen.common.database.table_group_service import (
    preview_table_group as preview_table_group_service,
)
from testgen.common.database.table_group_service import validate_table_group_fields
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import (
    DocGroup,
    format_flavor_label,
    format_page_footer,
    format_page_info,
    render_diff_table,
    resolve_connection,
    resolve_table_group,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc
from testgen.utils import friendly_score

_DOC_GROUP = DocGroup.MANAGE

_DUPLICATE_NAME_MESSAGE = "A Table Group with the same name already exists."
_PII_FLAG_DENIED_MESSAGE = (
    "Changing PII detection requires permission to view PII. "
    "Leave this setting unchanged or contact your administrator."
)
_SCHEMA_LOCKED_MESSAGE = (
    "Schema cannot be changed once the table group has been used. "
    "Delete and recreate the table group to use a different schema."
)


@with_database_session
@mcp_permission("view")
def list_table_groups(
    project_code: str | None = None,
    connection_id: int | None = None,
    page: int = 1,
    limit: int = 20,
) -> str:
    """List table groups in a project or on a specific connection.

    Pass exactly one of `project_code` or `connection_id`. Returns each group's
    table count, last profile / test timestamps, and current quality score.

    Args:
        project_code: List groups in a project.
        connection_id: List groups on a specific connection.
        page: Page number starting at 1 (default 1).
        limit: Page size (default 20, max 100).
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
    table_rows: list[list[object]] = []
    for row in rows:
        table_rows.append(
            [
                str(row.id),
                row.table_groups_name,
                row.connection_name,
                row.table_group_schema,
                row.table_count,
                row.column_count,
                row.row_count,
                row.last_profiled_date,
                row.last_tested_date,
                friendly_score(row.quality_score),
            ]
        )
    doc.table(
        ["ID", "Name", "Connection", "Schema", "Tables", "Columns", "Rows", "Last profiled", "Last tested", "Quality Score"],
        table_rows,
        code=[0, 3],
    )
    if footer := format_page_footer(total, page, limit):
        doc.text(footer)
    return doc.render()


@with_database_session
@mcp_permission("view")
def get_table_group(table_group_id: str) -> str:
    """Get a table group's full configuration: filters, sampling, profiling flags, catalog tags, and recent activity.

    Use this before editing a table group or generating tests.

    Args:
        table_group_id: The table group UUID, e.g. from `list_table_groups` or `get_data_inventory`.
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
    doc.field("Schema", table_group.table_group_schema, code=True)
    if table_group.description:
        doc.field("Description", table_group.description)

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
    connection_id: int,
    table_group_name: str,
    schema: str,
    *,
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
    include_in_dashboard: bool | None = None,
    add_scorecard: bool = True,
    data_source: str | None = None,
    source_system: str | None = None,
    source_process: str | None = None,
    data_location: str | None = None,
    business_domain: str | None = None,
    stakeholder_group: str | None = None,
    transform_level: str | None = None,
    data_product: str | None = None,
) -> str:
    """Create a table group on an existing connection.

    The table group inherits its project from the connection. ``include_mask``
    and ``exclude_mask`` are SQL ``LIKE`` patterns (e.g. ``fact_%,dim_%``);
    ``table_set`` is an explicit list. All filters compose with ``AND``.

    Args:
        connection_id: Bigint connection ID, e.g. from ``get_data_inventory``.
        table_group_name: 3-40 character display name. Must be unique within the project.
        schema: Schema name on the target database, e.g. ``public``. For Salesforce Data 360
            connections, use the data space name.
        description: Optional free-text description.
        table_set: Explicit list of table names. Combined with masks if also set.
        include_mask: Comma-separated SQL LIKE patterns to include (e.g. ``fact_%,dim_%``).
        exclude_mask: Comma-separated SQL LIKE patterns to exclude.
        profile_id_column_mask: SQL LIKE pattern marking ID columns. Default ``%id``.
        profile_sk_column_mask: SQL LIKE pattern marking surrogate-key columns. Default ``%_sk``.
        profile_use_sampling: Whether to sample large tables during profiling.
        profile_sample_percent: Sample size as a percent (1-100).
        profile_sample_min_count: Minimum row count when sampling.
        profiling_delay_days: Number of days to wait before new profiling will be available
            to generate tests.
        profile_flag_cdes: Whether profiling flags Critical Data Elements.
        profile_flag_pii: Whether profiling flags Personally Identifiable Information.
        profile_exclude_xde: Whether profiling excludes columns flagged as excluded data elements.
        include_in_dashboard: Whether the table group appears on the project dashboard.
        add_scorecard: Whether to add a scorecard for the table group to the Quality Dashboard.
        data_source: Catalog tag — original source of the dataset.
        source_system: Catalog tag — enterprise system source for the dataset.
        source_process: Catalog tag — process, program, or data flow that produced the dataset.
        data_location: Catalog tag — physical or virtual location of the dataset
            (e.g. ``Headquarters``, ``Cloud``).
        business_domain: Catalog tag — business division responsible for the dataset
            (e.g. ``Finance``, ``Sales``, ``Manufacturing``).
        stakeholder_group: Catalog tag — data owners or stakeholders responsible for the dataset.
        transform_level: Catalog tag — data warehouse processing stage (e.g. ``Raw``,
            ``Conformed``, ``Processed``, ``Reporting``) or Medallion level
            (``bronze``, ``silver``, ``gold``).
        data_product: Catalog tag — data domain that comprises the dataset.
    """
    connection = resolve_connection(connection_id)

    table_group = TableGroup(
        project_code=connection.project_code,
        connection_id=connection.connection_id,
        table_groups_name=table_group_name,
        table_group_schema=schema,
        **_model_defaults(),
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
        include_in_dashboard=include_in_dashboard,
        data_source=data_source,
        source_system=source_system,
        source_process=source_process,
        data_location=data_location,
        business_domain=business_domain,
        stakeholder_group=stakeholder_group,
        transform_level=transform_level,
        data_product=data_product,
    )

    errors = validate_table_group_fields(table_group)
    if errors:
        _raise_validation_error(errors, "Table group creation rejected. No changes saved.")

    try:
        table_group.save(add_scorecard_definition=add_scorecard)
    except IntegrityError as err:
        _maybe_raise_duplicate_name(err)
        raise

    return _render_created_table_group(table_group, connection)


@with_database_session
@mcp_permission("edit")
def update_table_group(
    table_group_id: str,
    *,
    table_group_name: str | None = None,
    schema: str | None = None,
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
    include_in_dashboard: bool | None = None,
    data_source: str | None = None,
    source_system: str | None = None,
    source_process: str | None = None,
    data_location: str | None = None,
    business_domain: str | None = None,
    stakeholder_group: str | None = None,
    transform_level: str | None = None,
    data_product: str | None = None,
) -> str:
    """Update fields on an existing table group. Atomic — no partial save.

    Connection and project are immutable — delete and recreate the table group
    to re-parent it. ``schema`` is also immutable once the table group has been
    used (profiled or has test suites); supply a different ``schema`` only on
    unused table groups.

    Args:
        table_group_id: UUID of the table group to update.
        table_group_name: New display name (3-40 chars). Must be unique within the project.
        schema: New target-DB schema. Rejected if the table group has been used.
        description: Free-text description.
        table_set: Replacement explicit table list (full replacement of the current list).
        include_mask: Comma-separated SQL LIKE patterns to include.
        exclude_mask: Comma-separated SQL LIKE patterns to exclude.
        profile_id_column_mask: SQL LIKE pattern marking ID columns.
        profile_sk_column_mask: SQL LIKE pattern marking surrogate-key columns.
        profile_use_sampling: Whether to sample large tables during profiling.
        profile_sample_percent: Sample size as a percent (1-100).
        profile_sample_min_count: Minimum row count when sampling.
        profiling_delay_days: Number of days to wait before new profiling will be available
            to generate tests.
        profile_flag_cdes: Whether profiling flags CDEs.
        profile_flag_pii: Whether profiling flags PII.
        profile_exclude_xde: Whether profiling excludes XDE columns.
        include_in_dashboard: Whether the table group appears on the project dashboard.
        data_source: Catalog tag — original source of the dataset.
        source_system: Catalog tag — enterprise system source for the dataset.
        source_process: Catalog tag — process, program, or data flow that produced the dataset.
        data_location: Catalog tag — physical or virtual location of the dataset
            (e.g. ``Headquarters``, ``Cloud``).
        business_domain: Catalog tag — business division responsible for the dataset
            (e.g. ``Finance``, ``Sales``, ``Manufacturing``).
        stakeholder_group: Catalog tag — data owners or stakeholders responsible for the dataset.
        transform_level: Catalog tag — data warehouse processing stage (e.g. ``Raw``,
            ``Conformed``, ``Processed``, ``Reporting``) or Medallion level
            (``bronze``, ``silver``, ``gold``).
        data_product: Catalog tag — data domain that comprises the dataset.
    """
    supplied = {
        "table_group_name": table_group_name,
        "schema": schema,
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
        "include_in_dashboard": include_in_dashboard,
        "data_source": data_source,
        "source_system": source_system,
        "source_process": source_process,
        "data_location": data_location,
        "business_domain": business_domain,
        "stakeholder_group": stakeholder_group,
        "transform_level": transform_level,
        "data_product": data_product,
    }
    if all(value is None for value in supplied.values()):
        raise MCPUserError("No fields supplied to update.")

    table_group = resolve_table_group(table_group_id)

    if (
        schema is not None
        and schema != table_group.table_group_schema
        and TableGroup.is_in_use([table_group.id])
    ):
        raise MCPUserError(_SCHEMA_LOCKED_MESSAGE)

    if (
        profile_flag_pii is not None
        and profile_flag_pii != table_group.profile_flag_pii
        and not get_project_permissions().has_permission("view_pii", table_group.project_code)
    ):
        raise MCPPermissionDenied(_PII_FLAG_DENIED_MESSAGE)

    before = _snapshot(table_group)
    _apply_args_to_table_group(table_group, **supplied)

    errors = validate_table_group_fields(table_group)
    if errors:
        _raise_validation_error(errors, "Update rejected. No changes saved.")

    after = _snapshot(table_group)

    doc = MdDoc()
    doc.heading(1, f"Table Group `{table_group.table_groups_name}` updated")
    doc.field("ID", str(table_group.id), code=True)

    rendered = render_diff_table(doc, before, after, attrs=_DIFF_ATTRS, labels=_DIFF_LABELS)
    if not rendered:
        doc.text("No fields changed — supplied values matched the current state.")
        return doc.render()

    try:
        table_group.save()
    except IntegrityError as err:
        _maybe_raise_duplicate_name(err)
        raise

    return doc.render()


@with_database_session
@mcp_permission("edit")
def preview_table_group(
    table_group_id: str,
    verify_access: bool = False,
) -> str:
    """Probe the target database for tables matching a table group's filters.

    Returns counts plus a per-table breakdown. Does not save anything to the
    application database.

    Args:
        table_group_id: UUID of the table group.
        verify_access: When True, probe read access on every matched table.
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
            doc.text(preview.get("message") or "Preview failed for an unknown reason.")
        return doc.render()

    doc.heading(1, f"Preview for table group `{name}`")
    doc.field("Table Group ID", str(table_group.id), code=True)
    doc.field("Schema", stats.get("table_group_schema"), code=True)
    doc.field("Tables matched", stats.get("table_ct") or 0)
    doc.field("Total columns", stats.get("column_ct") or 0)
    if stats.get("approx_record_ct") is not None:
        doc.field("Approx rows", stats.get("approx_record_ct"))
    if stats.get("approx_data_point_ct") is not None:
        doc.field("Approx data points", stats.get("approx_data_point_ct"))

    headers = ["Table", "Columns", "Approx Rows", "Approx Data Points"]
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
        if verify_access:
            access = info.get("can_access")
            row.append("Yes" if access is True else "No" if access is False else "Unknown")
        rows.append(row)
    doc.table(headers, rows, code=[0])

    if verify_access and preview.get("message"):
        doc.text(preview["message"])

    return doc.render()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DIFF_ATTRS: tuple[str, ...] = (
    "table_groups_name",
    "table_group_schema",
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
)

_DIFF_LABELS: dict[str, str] = {
    "table_groups_name": "Name",
    "table_group_schema": "Schema",
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
}

_CATALOG_ATTRS: tuple[str, ...] = (
    "data_source",
    "source_system",
    "source_process",
    "data_location",
    "business_domain",
    "stakeholder_group",
    "transform_level",
    "data_product",
)


# Mirror SQLAlchemy ``Column(default=...)`` values into the constructor kwargs.
# Column defaults only fire at flush time, but ``validate_table_group_fields``
# runs *before* flush. Without seeding these, every create call that omits
# e.g. ``profile_sample_percent`` would fail validation. Computing once at
# import time keeps the values in sync with the model and survives tests that
# patch the ``TableGroup`` class itself.
#
# ``YNString`` columns store raw "Y"/"N" strings as their default but expose
# the attribute as ``bool``; normalize so the in-memory render path doesn't
# treat "N" as truthy before the row is reloaded.
def _normalize_default(column, raw: Any) -> Any:
    from testgen.common.models.custom_types import YNString

    if isinstance(column.type, YNString) and isinstance(raw, str):
        return raw == "Y"
    return raw


_MODEL_DEFAULTS: dict[str, Any] = {
    column.name: _normalize_default(column, column.default.arg)
    for column in TableGroup.__table__.columns
    if (
        column.default is not None
        and not column.primary_key
        and getattr(column.default, "is_scalar", False)
    )
}


def _model_defaults() -> dict[str, Any]:
    return dict(_MODEL_DEFAULTS)


def _apply_args_to_table_group(
    table_group: TableGroup,
    *,
    table_group_name: str | None = None,
    schema: str | None = None,
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
    include_in_dashboard: bool | None = None,
    data_source: str | None = None,
    source_system: str | None = None,
    source_process: str | None = None,
    data_location: str | None = None,
    business_domain: str | None = None,
    stakeholder_group: str | None = None,
    transform_level: str | None = None,
    data_product: str | None = None,
) -> None:
    """Apply every non-None arg to its model field.

    Casts ``table_set: list[str]`` to comma-joined string, and casts
    integer args for columns the model stores as strings.
    """
    if table_group_name is not None:
        table_group.table_groups_name = table_group_name
    if schema is not None:
        table_group.table_group_schema = schema
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
        table_group.profile_sample_percent = str(profile_sample_percent)
    if profile_sample_min_count is not None:
        table_group.profile_sample_min_count = profile_sample_min_count
    if profiling_delay_days is not None:
        table_group.profiling_delay_days = str(profiling_delay_days)
    if profile_flag_cdes is not None:
        table_group.profile_flag_cdes = profile_flag_cdes
    if profile_flag_pii is not None:
        table_group.profile_flag_pii = profile_flag_pii
    if profile_exclude_xde is not None:
        table_group.profile_exclude_xde = profile_exclude_xde
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


def _raise_validation_error(errors: list[str], header: str) -> None:
    bullets = "\n".join(f"- {err}" for err in errors)
    raise MCPUserError(f"{header}\n\n{bullets}")


def _maybe_raise_duplicate_name(err: IntegrityError) -> None:
    if "table_groups_name_unique" in str(err.orig):
        raise MCPUserError(_DUPLICATE_NAME_MESSAGE) from err


def _snapshot(table_group: TableGroup) -> dict[str, Any]:
    return {attr: getattr(table_group, attr, None) for attr in _DIFF_ATTRS}


def _render_created_table_group(table_group: TableGroup, connection: Connection) -> str:
    doc = MdDoc()
    doc.heading(1, f"Table Group `{table_group.table_groups_name}` created")
    doc.field("ID", str(table_group.id), code=True)
    doc.field("Project", table_group.project_code, code=True)
    doc.field(
        "Connection",
        f"{connection.connection_name} (`{connection.connection_id}`)",
    )
    doc.field("Schema", table_group.table_group_schema, code=True)
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

    return doc.render()
