"""API v1 — table groups."""

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.exc import IntegrityError

from testgen.api.deps import (
    api_error,
    api_error_entries,
    api_errors,
    db_session,
    fields_to_change,
    get_authorized_user,
    has_project_permission,
    resolve_connection,
    resolve_project_code,
    resolve_table_group,
)
from testgen.api.schemas import (
    CatalogTags,
    ErrorResponse,
    FileDeclaration,
    TableGroupCreate,
    TableGroupCreateResponse,
    TableGroupItem,
    TableGroupListResponse,
    TableGroupResponse,
    TableGroupSchemaChange,
    TableGroupUpdateRequest,
    TableGroupUpdateResponse,
)
from testgen.common.database.table_group_service import (
    SchemaMoveRefused,
    apply_table_group_flavor_rules,
    cascade_delete_table_group,
    catalog_membership,
    is_duplicate_name_error,
    move_table_group_schema,
    update_catalog_for_edit,
    validate_table_group_fields,
    validate_table_naming,
    write_table_group_catalog,
)
from testgen.common.file_declaration_schema import declarations_from_payload
from testgen.common.flavors import declares_files, reports_table_group_schema
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup, split_criteria, table_group_defaults
from testgen.common.models.user import User

_error_responses = {404: {"model": ErrorResponse, "description": "Not found"}}

router = APIRouter(tags=["Table Groups"], dependencies=[Depends(db_session, scope="function")], responses=_error_responses)

_LIST_COLUMNS = {
    "table_set": "profiling_table_set",
    "include_masks": "profiling_include_mask",
    "exclude_masks": "profiling_exclude_mask",
}


@router.get(
    "/projects/{project_code}/table-groups",
    response_model=TableGroupListResponse,
    summary="List table groups",
)
def list_table_groups(
    project_code: str = resolve_project_code("view"),
    connection_id: int | None = Query(default=None, description="Only table groups on this connection."),
    schema_name: str | None = Query(default=None, description="Only table groups on this schema."),
    table_group_name: str | None = Query(default=None, description="Only the table group with this name."),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Table groups in a project, each with its table count and latest profiling and test activity.

    The filters match exactly and combine, so ``schema_name`` and ``table_group_name``
    together answer "is this dataset already set up?" in one call, without paging
    through the project.
    """
    rows, total = TableGroup.list_for_project(
        project_code,
        connection_id=connection_id,
        schema_name=schema_name,
        table_group_name=table_group_name,
        page=page,
        limit=limit,
    )
    return TableGroupListResponse(
        items=[
            TableGroupItem(
                table_group_id=row.id,
                table_group_name=row.table_groups_name,
                schema_name=row.table_group_schema if reports_table_group_schema(row.sql_flavor_code) else None,
                project_code=row.project_code,
                connection_id=row.connection_id,
                connection_name=row.connection_name,
                table_count=row.table_count,
                column_count=row.column_count,
                row_count=row.row_count,
                last_profiled_at=row.last_profiled_date,
                last_tested_at=row.last_tested_date,
                profiling_score=row.profiling_score,
                testing_score=row.testing_score,
                quality_score=row.quality_score,
            )
            for row in rows
        ],
        page=page,
        limit=limit,
        total=total,
    )


@router.get(
    "/table-groups/{table_group_id}",
    response_model=TableGroupResponse,
    summary="Read a table group",
)
def get_table_group(table_group: TableGroup = resolve_table_group("view")):  # noqa: B008
    """A table group's full configuration: which tables it covers, how profiling treats
    them, and the catalog tags the Quality Score can be sliced by.
    """
    return _to_response(table_group)


@router.post(
    "/connections/{connection_id}/table-groups",
    response_model=TableGroupCreateResponse,
    status_code=201,
    summary="Create a table group",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "One entry per field or file declaration that failed validation",
        },
        409: {"model": ErrorResponse, "description": "A table group with this name already exists in the project"},
    },
)
def create_table_group(
    connection: Connection = resolve_connection("edit"),  # noqa: B008
    body: TableGroupCreate = Body(...),  # noqa: B008
) -> TableGroupCreateResponse:
    """Create a table group on a connection. It belongs to the connection's project.

    The response carries the new ``table_group_id``, which profiling, test generation
    and test runs take as input.

    The request names the table group's tables the way its connection holds them: by
    ``schema_name`` on a database connection, optionally narrowed by ``table_set`` and the
    masks, or by ``file_declarations`` on a file connection.

    The table group's data catalog is read from the target before the response returns, so tests
    can be imported into it right away. ``catalog_error`` says why when the target could not be read.
    """
    if errors := validate_table_naming(
        connection,
        schema=body.schema_name,
        file_declarations=body.file_declarations,
        criteria=(body.table_set, body.include_masks, body.exclude_masks),
    ):
        raise api_errors(400, "invalid_table_group", errors)

    table_group = TableGroup(
        project_code=connection.project_code,
        connection_id=connection.connection_id,
        table_groups_name=body.table_group_name,
        table_group_schema=body.schema_name,
        file_declarations=(
            [declaration.to_payload() for declaration in body.file_declarations] if body.file_declarations else None
        ),
        **table_group_defaults(),
    )
    fields = body.model_dump(
        exclude_none=True,
        exclude={"table_group_name", "schema_name", "file_declarations", "catalog_tags", "add_scorecard"},
    )
    for name, value in fields.items():
        if name in _LIST_COLUMNS:
            setattr(table_group, _LIST_COLUMNS[name], ",".join(value))
        else:
            setattr(table_group, name, value)
    if body.catalog_tags:
        for name, value in body.catalog_tags.model_dump(exclude_none=True).items():
            setattr(table_group, name, value)

    apply_table_group_flavor_rules(table_group, connection)
    if errors := validate_table_group_fields(table_group, connection):
        raise api_errors(400, "invalid_table_group", errors)

    try:
        table_group.save(add_scorecard_definition=body.add_scorecard)
    except IntegrityError as err:
        if is_duplicate_name_error(err):
            raise api_error(
                409, "duplicate_table_group_name", "A table group with this name already exists in the project."
            ) from err
        raise

    catalog_error = write_table_group_catalog(table_group, connection)
    get_current_session().refresh(table_group)
    return TableGroupCreateResponse(**_to_response(table_group, connection).model_dump(), catalog_error=catalog_error)


def _to_response(table_group: TableGroup, connection: Connection | None = None) -> TableGroupResponse:
    connection = connection or Connection.get_by_table_group(table_group.id)
    flavor_code = connection.sql_flavor_code if connection else None
    return TableGroupResponse(
        table_group_id=table_group.id,
        table_group_name=table_group.table_groups_name,
        schema_name=table_group.table_group_schema if reports_table_group_schema(flavor_code) else None,
        project_code=table_group.project_code,
        connection_id=table_group.connection_id,
        default_test_suite_id=table_group.default_test_suite_id,
        description=table_group.description,
        table_set=split_criteria(table_group.profiling_table_set),
        include_masks=split_criteria(table_group.profiling_include_mask),
        exclude_masks=split_criteria(table_group.profiling_exclude_mask),
        file_declarations=(
            declarations_from_payload(table_group.file_declarations, FileDeclaration)
            if declares_files(flavor_code)
            else None
        ),
        profile_id_column_mask=table_group.profile_id_column_mask,
        profile_sk_column_mask=table_group.profile_sk_column_mask,
        profile_use_sampling=table_group.profile_use_sampling,
        profile_sample_percent=table_group.profile_sample_percent,
        profile_sample_min_count=table_group.profile_sample_min_count,
        profiling_delay_days=table_group.profiling_delay_days,
        profile_flag_cdes=table_group.profile_flag_cdes,
        profile_flag_pii=table_group.profile_flag_pii,
        profile_exclude_xde=table_group.profile_exclude_xde,
        profile_table_comparison=table_group.profile_table_comparison,
        include_in_dashboard=table_group.include_in_dashboard,
        catalog_tags=CatalogTags.model_validate(table_group, from_attributes=True),
    )


_PII_FLAG_DENIED = (
    "Changing PII detection requires permission to view PII. "
    "Leave this setting unchanged or contact your administrator."
)

_REFUSAL_STATUS = {
    "job_in_flight": 409,
    "invalid_schema_name": 422,
    "schema_empty": 422,
    "schema_unreadable": 422,
    "schema_unsupported": 422,
}


@router.patch(
    "/table-groups/{table_group_id}",
    response_model=TableGroupUpdateResponse,
    summary="Update a table group",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "One entry per field or file declaration that failed validation, and one "
            "`pii_permission_required` entry when the request changes PII detection without permission to "
            "view PII",
        },
        409: {
            "model": ErrorResponse,
            "description": "A job for this table group is still running, or another table group in the project "
            "has this name",
        },
        422: {"model": ErrorResponse, "description": "A supplied field cannot be applied"},
    },
)
def update_table_group(
    table_group: TableGroup = resolve_table_group("edit"),  # noqa: B008
    body: TableGroupUpdateRequest = Body(...),  # noqa: B008
    user: User = Depends(get_authorized_user),  # noqa: B008
) -> TableGroupUpdateResponse:
    """Change a table group's configuration. Omitted fields are left as they are, and nothing is saved
    when any field is refused.

    `table_set`, the masks and `file_declarations` replace the stored list. Catalog tags are merged:
    a tag the request does not name is left as it is.

    Changing `profile_flag_pii` requires permission to view PII. Without it, the 400 carries a
    `pii_permission_required` entry alongside any `invalid_table_group` entries.

    When `schema_name` changes, profiling, test generation, monitors, and test runs read the new
    schema, and tests keep their history. Referential tests keep the schema of their second table.
    The change is refused with `schema_unreadable` when the schema cannot be read, and with
    `schema_empty` when no table in it matches the table group's table filters, as edited by the same
    request. Tables the table group no longer selects after the move are listed under
    `schema_change.missing_tables`.

    When the update changes which tables belong to the table group, its data catalog is rewritten from
    the target before the response returns. `catalog_error` says why when the catalog could not be
    rewritten, including when a filter change without a schema move matches no table. The update is
    saved in that case.
    """
    sent = fields_to_change(body)
    tags = body.catalog_tags.model_dump(exclude_unset=True) if body.catalog_tags else {}
    if nulled := sorted(f"catalog_tags.{name}" for name, value in tags.items() if value is None):
        raise api_error(
            422,
            "null_field",
            f"{', '.join(nulled)} cannot be null. Omit a field to leave it unchanged.",
        )
    if sent.keys() == {"catalog_tags"} and not tags:
        raise api_error(422, "no_fields", "No fields supplied to update.")

    connection = Connection.get_by_table_group(table_group.id)
    errors = []
    if connection is not None:
        errors = validate_table_naming(
            connection,
            schema=body.schema_name,
            file_declarations=body.file_declarations,
            criteria=(body.table_set, body.include_masks, body.exclude_masks),
            require=False,
        )
    pii_denied = (
        body.profile_flag_pii is not None
        and body.profile_flag_pii != table_group.profile_flag_pii
        and not has_project_permission(user, table_group.project_code, "view_pii")
    )

    membership_before = catalog_membership(table_group)
    for name, value in sent.items():
        if name == "table_group_name":
            table_group.table_groups_name = value
        elif name in _LIST_COLUMNS:
            setattr(table_group, _LIST_COLUMNS[name], ",".join(value))
        elif name == "file_declarations":
            table_group.file_declarations = [declaration.to_payload() for declaration in value]
        elif name not in ("schema_name", "catalog_tags"):
            setattr(table_group, name, value)
    for name, value in tags.items():
        setattr(table_group, name, value)

    apply_table_group_flavor_rules(table_group, connection)
    errors.extend(validate_table_group_fields(table_group, connection))
    if errors or pii_denied:
        entries = [("invalid_table_group", error) for error in errors]
        if pii_denied:
            entries.append(("pii_permission_required", _PII_FLAG_DENIED))
        raise api_error_entries(400, entries)

    move = None
    # The move's queries autoflush the edited name, so a duplicate can surface there as well as on save.
    try:
        if body.schema_name is not None and body.schema_name != table_group.table_group_schema:
            try:
                move = move_table_group_schema(table_group, body.schema_name, connection=connection)
            except SchemaMoveRefused as refusal:
                raise api_error(
                    _REFUSAL_STATUS.get(refusal.reason, 422), refusal.reason, refusal.message
                ) from refusal
        table_group.save()
    except IntegrityError as err:
        if is_duplicate_name_error(err):
            raise api_error(
                409, "duplicate_table_group_name", "A table group with this name already exists in the project."
            ) from err
        raise

    catalog_error = update_catalog_for_edit(table_group, membership_before, move, connection)
    get_current_session().refresh(table_group)

    return TableGroupUpdateResponse(
        **_to_response(table_group, connection).model_dump(),
        schema_change=TableGroupSchemaChange(
            previous_schema_name=move.previous_schema,
            schema_name=move.schema,
            definitions_repointed=move.definitions_repointed,
            missing_tables=move.missing_tables,
        )
        if move
        else None,
        catalog_error=catalog_error,
    )


@router.delete(
    "/table-groups/{table_group_id}",
    status_code=204,
    summary="Delete a table group",
    responses={409: {"model": ErrorResponse, "description": "A job for this table group is still running"}},
)
def delete_table_group(table_group: TableGroup = resolve_table_group("edit")) -> None:  # noqa: B008
    """Delete a table group together with everything recorded against it: its test suites with their
    test definitions, test runs, results, and schedules; its monitors; its profiling runs and results,
    hygiene issues, and data catalog; and the notification rules scoped to it or to its test suites.
    Scorecards are kept.

    The delete is refused while a job for the table group or its test suites is queued or running:
    profiling, test generation, a test run, or monitor generation or a monitor run. Queued data
    catalog refreshes are canceled, and a refresh that has already started refuses the delete too.
    """
    if cascade_delete_table_group(table_group):
        raise api_error(
            409,
            "job_in_flight",
            "A job for this table group is still running. Wait for it to finish, then try again.",
        )
