from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    and_,
    asc,
    case,
    cast,
    func,
    literal,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ColumnElement

from testgen.common.database.column_chars import ColumnChars, ObjectType
from testgen.common.models import get_current_session
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.entity import Entity
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup

CATALOG_TAG_LABELS: dict[str, str] = {
    "data_source": "Data source",
    "source_system": "Source system",
    "source_process": "Source process",
    "business_domain": "Business domain",
    "stakeholder_group": "Stakeholder group",
    "transform_level": "Transform level",
    "aggregation_level": "Aggregation level",
    "data_product": "Data product",
    "data_classification": "Data classification",
}

# Table groups have no aggregation level of their own.
TABLE_GROUP_TAGS = tuple(tag for tag in CATALOG_TAG_LABELS if tag != "aggregation_level")


class CatalogLevel(StrEnum):
    """The catalog entity whose effective metadata is read."""

    COLUMN = "column"
    TABLE = "table"


class CatalogSource(StrEnum):
    """Where an inherited catalog value comes from."""

    TABLE = "table"
    TABLE_GROUP = "table group"


@dataclass(frozen=True)
class CatalogTag:
    tag: str
    label: str
    value: str
    inherited_from: CatalogSource | None


def parse_catalog_tags(raw: dict | None) -> list[CatalogTag]:
    """Turn a ``catalog_tags`` column (see :func:`catalog_tags_column`) into tags in display order."""
    raw = raw or {}
    return [
        CatalogTag(
            tag=tag,
            label=label,
            value=raw[tag][0],
            inherited_from=CatalogSource(raw[tag][1]) if raw[tag][1] else None,
        )
        for tag, label in CATALOG_TAG_LABELS.items()
        if tag in raw
    ]


@dataclass
class TableColumnSummary:
    column_name: str
    general_type: str | None
    functional_data_type: str | None
    db_data_type: str | None
    has_nulls: bool | None


@dataclass
class TableProfilingOverview:
    id: UUID
    table_groups_id: UUID
    schema_name: str | None
    table_name: str
    object_type: ObjectType | None
    record_ct: int | None
    column_ct: int | None
    file_ct: int | None
    functional_table_type: str | None
    dq_score_profiling: float | None
    dq_score_testing: float | None
    description: str | None
    critical_data_element: bool
    catalog_tags: dict | None
    cde_count: int
    hygiene_issue_count: int
    latest_profile_id: UUID | None
    latest_profile_started_at: datetime | None
    latest_profile_job_execution_id: UUID | None
    columns: list[TableColumnSummary] = field(default_factory=list)


@dataclass
class TableCatalogSummary:
    table_name: str
    functional_table_type: str | None
    record_ct: int | None
    critical_data_element: bool
    catalog_tags: dict | None


class DataTable(Entity):
    __tablename__ = "data_table_chars"

    id: UUID = Column("table_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    schema_name: str | None = Column(String)
    table_name: str = Column(String)
    object_type: ObjectType | None = Column(String)
    column_ct: int | None = Column(BigInteger)
    record_ct: int | None = Column(BigInteger)
    approx_record_ct: int | None = Column(BigInteger)
    file_ct: int | None = Column(Integer)
    critical_data_element: bool | None = Column(Boolean)
    description: str | None = Column(String(1000))
    data_source: str | None = Column(String(40))
    source_system: str | None = Column(String(40))
    source_process: str | None = Column(String(40))
    business_domain: str | None = Column(String(40))
    stakeholder_group: str | None = Column(String(40))
    transform_level: str | None = Column(String(40))
    aggregation_level: str | None = Column(String(40))
    data_product: str | None = Column(String(40))
    data_classification: str | None = Column(String(40))
    functional_table_type: str | None = Column(String(50))
    drop_date: datetime | None = Column(postgresql.TIMESTAMP)
    last_complete_profile_run_id: UUID | None = Column(postgresql.UUID(as_uuid=True))
    dq_score_profiling: float | None = Column(Float)
    dq_score_testing: float | None = Column(Float)

    # The inherited Entity default orders by the textual label "id", but this model's
    # primary key column is "table_id" — order by a real column instead.
    _default_order_by = (asc(table_name),)

    # Unmapped columns: add_date, last_refresh_date, last_profile_record_ct

    @classmethod
    def select_table_names(
        cls, table_groups_id: UUID, project_codes: list[str] | None = None, limit: int | None = 100, offset: int = 0,
    ) -> list[str]:
        query = select(cls.table_name).where(cls.table_groups_id == table_groups_id, cls.drop_date.is_(None))
        if project_codes is not None:
            query = query.join(TableGroup, cls.table_groups_id == TableGroup.id).where(
                TableGroup.project_code.in_(project_codes)
            )
        query = query.order_by(asc(func.lower(cls.table_name))).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list(get_current_session().scalars(query).all())

    @classmethod
    def list_for_table_group(
        cls, *clauses, table_groups_id: UUID, page: int, limit: int,
    ) -> tuple[list[TableCatalogSummary], int]:
        """List a table group's tables with their semantic table type, CDE flag, and effective catalog tags."""
        query = (
            select(
                cls.table_name,
                cls.functional_table_type,
                cls.record_ct,
                table_cde().label("critical_data_element"),
                catalog_tags_column(CatalogLevel.TABLE),
            )
            .join(TableGroup, TableGroup.id == cls.table_groups_id)
            .where(cls.table_groups_id == table_groups_id, cls.drop_date.is_(None), *clauses)
            .order_by(asc(func.lower(cls.table_name)), asc(cls.table_name))
        )
        return cls._paginate(query, page=page, limit=limit, data_class=TableCatalogSummary)

    @classmethod
    def list_column_chars(cls, table_groups_id: UUID, *clauses) -> list[ColumnChars]:
        """Read back the catalog a profiling run recorded, in place of querying the target.

        Row counts live here rather than on the column, and they are what a run's sampling was
        decided from, so a run that continues has to see the ones it started with rather than
        whatever the target holds now.
        """
        query = (
            select(
                DataColumnChars.schema_name,
                DataColumnChars.table_name,
                DataColumnChars.column_name,
                DataColumnChars.ordinal_position,
                DataColumnChars.general_type,
                DataColumnChars.column_type,
                DataColumnChars.db_data_type,
                DataColumnChars.logical_type,
                DataColumnChars.is_decimal,
                cls.object_type,
                cls.approx_record_ct,
                cls.record_ct,
                cls.file_ct,
            )
            .join(DataColumnChars, DataColumnChars.table_id == cls.id)
            .where(
                cls.table_groups_id == table_groups_id,
                cls.drop_date.is_(None),
                DataColumnChars.drop_date.is_(None),
                *clauses,
            )
            .order_by(DataColumnChars.table_name, DataColumnChars.ordinal_position, DataColumnChars.column_name)
        )
        return [ColumnChars(**row) for row in get_current_session().execute(query).mappings().all()]

    @classmethod
    def get_profiling_overview(
        cls, table_groups_id: UUID, table_name: str,
    ) -> TableProfilingOverview | None:
        session = get_current_session()

        header_query = (
            select(
                cls.id,
                cls.table_groups_id,
                cls.schema_name,
                cls.table_name,
                cls.object_type,
                cls.record_ct,
                cls.column_ct,
                cls.file_ct,
                cls.functional_table_type,
                cls.dq_score_profiling,
                cls.dq_score_testing,
                cls.description,
                table_cde().label("critical_data_element"),
                catalog_tags_column(CatalogLevel.TABLE),
                cls.last_complete_profile_run_id.label("latest_profile_id"),
                JobExecution.started_at.label("latest_profile_started_at"),
                JobExecution.id.label("latest_profile_job_execution_id"),
            )
            .join(TableGroup, TableGroup.id == cls.table_groups_id)
            .outerjoin(ProfilingRun, ProfilingRun.id == cls.last_complete_profile_run_id)
            .outerjoin(JobExecution, JobExecution.id == ProfilingRun.id)
            .where(
                cls.table_groups_id == table_groups_id,
                cls.table_name == table_name,
                cls.drop_date.is_(None),
            )
        )
        header = session.execute(header_query).mappings().first()
        if not header:
            return None

        columns_query = (
            select(
                DataColumnChars.column_name,
                DataColumnChars.general_type,
                DataColumnChars.functional_data_type,
                DataColumnChars.db_data_type,
                case(
                    (ProfileResult.null_value_ct.is_(None), None),
                    (ProfileResult.null_value_ct > 0, True),
                    else_=False,
                ).label("has_nulls"),
            )
            .outerjoin(
                ProfileResult,
                and_(
                    ProfileResult.profile_run_id == DataColumnChars.last_complete_profile_run_id,
                    ProfileResult.table_name == DataColumnChars.table_name,
                    ProfileResult.column_name == DataColumnChars.column_name,
                ),
            )
            .where(
                DataColumnChars.table_id == header["id"],
                DataColumnChars.drop_date.is_(None),
            )
            .order_by(asc(DataColumnChars.ordinal_position), asc(DataColumnChars.column_name))
        )
        columns = [TableColumnSummary(**row) for row in session.execute(columns_query).mappings().all()]

        cde_count = session.scalar(
            select(func.count())
            .select_from(DataColumnChars)
            .join(cls, cls.id == DataColumnChars.table_id)
            .where(
                DataColumnChars.table_id == header["id"],
                column_cde().is_(True),
                DataColumnChars.drop_date.is_(None),
            )
        ) or 0

        hygiene_issue_count = 0
        if header["latest_profile_id"]:
            hygiene_issue_count = session.scalar(
                select(func.count())
                .select_from(HygieneIssue)
                .where(
                    HygieneIssue.profile_run_id == header["latest_profile_id"],
                    HygieneIssue.table_name == table_name,
                    func.coalesce(HygieneIssue.disposition, "Confirmed") == "Confirmed",
                )
            ) or 0

        return TableProfilingOverview(
            **header,
            cde_count=cde_count,
            hygiene_issue_count=hygiene_issue_count,
            columns=columns,
        )


def table_cde() -> ColumnElement[bool]:
    """A table's critical data element flag, with no value read as ``False``."""
    return func.coalesce(DataTable.critical_data_element, False)


def column_cde() -> ColumnElement[bool]:
    """A column's critical data element flag: its own value or, when it has none, its table's.

    The query must join :class:`DataTable`.
    """
    return func.coalesce(DataColumnChars.critical_data_element, DataTable.critical_data_element, False)


def _tag_sources(tag: str, level: CatalogLevel) -> list[tuple[CatalogSource | None, ColumnElement]]:
    sources: list[tuple[CatalogSource | None, ColumnElement]] = []
    if level == CatalogLevel.COLUMN:
        sources.append((None, getattr(DataColumnChars, tag)))
    sources.append((CatalogSource.TABLE if level == CatalogLevel.COLUMN else None, getattr(DataTable, tag)))
    if tag in TABLE_GROUP_TAGS:
        sources.append((CatalogSource.TABLE_GROUP, getattr(TableGroup, tag)))
    return sources


def effective_tag(tag: str, level: CatalogLevel) -> ColumnElement[str]:
    """A tag's value on a column or table, falling back to its table's and then its table group's.

    The query must join :class:`DataTable` and :class:`TableGroup`.
    """
    return func.coalesce(*(column for _, column in _tag_sources(tag, level)))


def catalog_tags_column(level: CatalogLevel) -> ColumnElement[dict]:
    """Every tag that has an effective value, as ``{tag: [value, source]}``.

    ``source`` is null for the column's or table's own value. The query must join
    :class:`DataTable` and :class:`TableGroup`.
    """
    pairs: list = []
    for tag in CATALOG_TAG_LABELS:
        pairs.append(tag)
        pairs.append(case(*(
            (column.isnot(None), func.jsonb_build_array(column, cast(literal(source and source.value), String)))
            for source, column in _tag_sources(tag, level)
        )))
    return func.jsonb_strip_nulls(func.jsonb_build_object(*pairs)).label("catalog_tags")
