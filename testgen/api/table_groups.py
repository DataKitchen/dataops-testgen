"""API v1 — table groups."""

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.exc import IntegrityError

from testgen.api.deps import (
    api_error,
    api_errors,
    db_session,
    resolve_connection,
    resolve_project_code,
    resolve_table_group,
)
from testgen.api.schemas import (
    CatalogTags,
    ErrorResponse,
    TableGroupCreate,
    TableGroupItem,
    TableGroupListResponse,
    TableGroupResponse,
)
from testgen.common.database.table_group_service import (
    is_duplicate_name_error,
    table_group_defaults,
    validate_table_group_fields,
)
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup, split_criteria

_error_responses = {404: {"model": ErrorResponse, "description": "Not found"}}

router = APIRouter(tags=["Table Groups"], dependencies=[Depends(db_session)], responses=_error_responses)

_FIELD_NAMES = {"table_groups_name": "table_group_name", "table_group_schema": "schema_name"}
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
                schema_name=row.table_group_schema,
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
    response_model=TableGroupResponse,
    status_code=201,
    summary="Create a table group",
    responses={
        400: {"model": ErrorResponse, "description": "One entry per field that failed validation"},
        409: {"model": ErrorResponse, "description": "A table group with this name already exists in the project"},
    },
)
def create_table_group(
    connection: Connection = resolve_connection("edit"),  # noqa: B008
    body: TableGroupCreate = Body(...),  # noqa: B008
) -> TableGroupResponse:
    """Create a table group on a connection. It belongs to the connection's project.

    The response carries the new ``table_group_id``, which profiling, test generation
    and test runs take as input.
    """
    table_group = TableGroup(
        project_code=connection.project_code,
        connection_id=connection.connection_id,
        table_groups_name=body.table_group_name,
        table_group_schema=body.schema_name,
        **table_group_defaults(),
    )
    fields = body.model_dump(
        exclude_none=True,
        exclude={"table_group_name", "schema_name", "catalog_tags", "add_scorecard"},
    )
    for name, value in fields.items():
        if name in _LIST_COLUMNS:
            setattr(table_group, _LIST_COLUMNS[name], ",".join(value))
        else:
            setattr(table_group, name, value)
    if body.catalog_tags:
        for name, value in body.catalog_tags.model_dump(exclude_none=True).items():
            setattr(table_group, name, value)

    if errors := validate_table_group_fields(table_group, _FIELD_NAMES):
        raise api_errors(400, "invalid_table_group", errors)

    try:
        table_group.save(add_scorecard_definition=body.add_scorecard)
    except IntegrityError as err:
        if is_duplicate_name_error(err):
            raise api_error(
                409, "duplicate_table_group_name", "A table group with this name already exists in the project."
            ) from err
        raise

    return _to_response(table_group)


def _to_response(table_group: TableGroup) -> TableGroupResponse:
    return TableGroupResponse(
        table_group_id=table_group.id,
        table_group_name=table_group.table_groups_name,
        schema_name=table_group.table_group_schema,
        project_code=table_group.project_code,
        connection_id=table_group.connection_id,
        default_test_suite_id=table_group.default_test_suite_id,
        description=table_group.description,
        table_set=split_criteria(table_group.profiling_table_set),
        include_masks=split_criteria(table_group.profiling_include_mask),
        exclude_masks=split_criteria(table_group.profiling_exclude_mask),
        profile_id_column_mask=table_group.profile_id_column_mask,
        profile_sk_column_mask=table_group.profile_sk_column_mask,
        profile_use_sampling=table_group.profile_use_sampling,
        profile_sample_percent=table_group.profile_sample_percent,
        profile_sample_min_count=table_group.profile_sample_min_count,
        profiling_delay_days=table_group.profiling_delay_days,
        profile_flag_cdes=table_group.profile_flag_cdes,
        profile_flag_pii=table_group.profile_flag_pii,
        profile_exclude_xde=table_group.profile_exclude_xde,
        include_in_dashboard=table_group.include_in_dashboard,
        catalog_tags=CatalogTags.model_validate(table_group, from_attributes=True),
    )
