from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    and_,
    asc,
    case,
    desc,
    func,
    select,
)
from sqlalchemy.dialects import postgresql

from testgen.common.models import get_current_session
from testgen.common.models.entity import Entity, EntityMinimal
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun


class GeneralType(StrEnum):
    """User-facing word values for the column ``general_type``."""

    ALPHA = "Alpha"
    NUMERIC = "Numeric"
    DATETIME = "Datetime"
    BOOLEAN = "Boolean"
    TIME = "Time"
    OTHER = "Other"


# Translates the user-facing words to the single-letter codes stored on
# ``data_column_chars.general_type`` for WHERE-clause matching.
GENERAL_TYPE_TO_CODE: dict[GeneralType, str] = {
    GeneralType.ALPHA: "A",
    GeneralType.NUMERIC: "N",
    GeneralType.DATETIME: "D",
    GeneralType.BOOLEAN: "B",
    GeneralType.TIME: "T",
    GeneralType.OTHER: "X",
}


class SuggestedDataType(StrEnum):
    """Values accepted for the ``suggested_data_type`` argument."""

    ANY = "Any"
    SMALLINT = "Smallint"
    INTEGER = "Integer"
    BIGINT = "Bigint"
    DECIMAL = "Decimal"
    NUMERIC = "Numeric"
    VARCHAR = "Varchar"
    DATE = "Date"
    TIMESTAMP = "Timestamp"
    BOOLEAN = "Boolean"


# Maps the user-facing word to the SQL-type prefix matched against
# ``datatype_suggestion`` (``Any`` is a sentinel — no prefix, just non-null check).
SUGGESTED_DATA_TYPE_TO_PREFIX: dict[SuggestedDataType, str | None] = {
    SuggestedDataType.ANY: None,
    SuggestedDataType.SMALLINT: "SMALLINT",
    SuggestedDataType.INTEGER: "INTEGER",
    SuggestedDataType.BIGINT: "BIGINT",
    SuggestedDataType.DECIMAL: "DECIMAL",
    SuggestedDataType.NUMERIC: "NUMERIC",
    SuggestedDataType.VARCHAR: "VARCHAR",
    SuggestedDataType.DATE: "DATE",
    SuggestedDataType.TIMESTAMP: "TIMESTAMP",
    SuggestedDataType.BOOLEAN: "BOOLEAN",
}


class ColumnOrderBy(StrEnum):
    """Values accepted for the ``order_by`` argument on column profile listings."""

    NULL_RATIO = "Null Ratio"
    DISTINCT_RATIO = "Distinct Ratio"
    FILLED_RATIO = "Filled Ratio"
    SCORE_PROFILING = "Profiling Score"
    SCORE_TESTING = "Testing Score"
    HYGIENE_COUNT = "Hygiene Count"


class ProfileMetric(StrEnum):
    """Profile-metric vocabulary: linear/arithmetic stats from a profiling run.

    Covers general column ratios (null / distinct / filled), type-specific
    statistics (length, numeric range, date range, true count), table-level
    row count, and table-group rollups (profiling score, hygiene issues).

    Labels align with the field names in ``column_profile_fields_resource``.
    """

    # Apply to any column
    NULL_RATIO = "Null Ratio"
    DISTINCT_RATIO = "Distinct Ratio"
    FILLED_RATIO = "Filled Ratio"
    # Apply to the parent table
    RECORD_COUNT = "Row Count"
    # Apply to the whole table group
    PROFILING_SCORE = "Profiling Score"
    HYGIENE_COUNT = "Hygiene Issues"
    # Alpha-only
    MIN_LENGTH = "Minimum Length"
    MAX_LENGTH = "Maximum Length"
    AVG_LENGTH = "Average Length"
    # Numeric-only
    MIN = "Minimum Value"
    MAX = "Maximum Value"
    AVG = "Average Value"
    STDEV = "Standard Deviation"
    # Date-only
    MIN_DATE = "Minimum Date"
    MAX_DATE = "Maximum Date"
    # Boolean-only
    TRUE_COUNT = "True Count"


@dataclass
class ColumnProfileSummary(EntityMinimal):
    column_name: str
    table_name: str
    general_type: str | None
    functional_data_type: str | None
    datatype_suggestion: str | None
    pii_flag: str | None
    critical_data_element: bool | None
    record_ct: int | None
    null_value_ct: int | None
    distinct_value_ct: int | None
    filled_value_ct: int | None
    dq_score_profiling: float | None
    dq_score_testing: float | None
    hygiene_issue_count: int


@dataclass
class ColumnProfileDetail(EntityMinimal):
    """L2 column profiling detail — header fields plus type-specific stats and run identity."""

    # Identity
    column_name: str
    table_name: str
    schema_name: str | None
    # Types & metadata
    general_type: str | None
    column_type: str | None
    db_data_type: str | None
    functional_data_type: str | None
    datatype_suggestion: str | None
    functional_table_type: str | None
    pii_flag: str | None
    critical_data_element: bool | None
    # Counts
    record_ct: int | None
    value_ct: int | None
    distinct_value_ct: int | None
    null_value_ct: int | None
    filled_value_ct: int | None
    zero_value_ct: int | None
    # Alpha
    min_length: int | None
    max_length: int | None
    avg_length: float | None
    min_text: str | None
    max_text: str | None
    top_freq_values: str | None
    top_patterns: str | None
    distinct_std_value_ct: int | None
    distinct_pattern_ct: int | None
    std_pattern_match: str | None
    mixed_case_ct: int | None
    lower_case_ct: int | None
    upper_case_ct: int | None
    non_alpha_ct: int | None
    includes_digit_ct: int | None
    numeric_ct: int | None
    date_ct: int | None
    quoted_value_ct: int | None
    lead_space_ct: int | None
    embedded_space_ct: int | None
    avg_embedded_spaces: float | None
    zero_length_ct: int | None
    # Numeric
    min_value: float | None
    min_value_over_0: float | None
    max_value: float | None
    avg_value: float | None
    stdev_value: float | None
    percentile_25: float | None
    percentile_50: float | None
    percentile_75: float | None
    # Date
    min_date: datetime | None
    max_date: datetime | None
    before_1yr_date_ct: int | None
    before_5yr_date_ct: int | None
    before_20yr_date_ct: int | None
    within_1yr_date_ct: int | None
    within_1mo_date_ct: int | None
    future_date_ct: int | None
    # Boolean
    boolean_true_ct: int | None
    # Per-column profiling failure
    query_error: str | None
    # Scores & hygiene
    dq_score_profiling: float | None
    dq_score_testing: float | None
    hygiene_issue_count: int
    # Run identity
    profile_run_id: UUID | None
    profile_run_je_id: UUID | None
    profile_run_status: str | None
    profile_run_started_at: datetime | None
    profile_run_ended_at: datetime | None
    profile_run_log_message: str | None


@dataclass
class ColumnSearchHit(EntityMinimal):
    project_code: str
    table_groups_id: UUID
    table_groups_name: str
    schema_name: str | None
    table_name: str
    column_name: str


@dataclass
class CreateScriptColumn:
    column_name: str
    db_data_type: str | None
    datatype_suggestion: str | None


class DataColumnChars(Entity):
    __tablename__ = "data_column_chars"

    id: UUID = Column("column_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    table_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("data_table_chars.table_id"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    schema_name: str = Column(String)
    table_name: str = Column(String)
    column_name: str = Column(String)
    ordinal_position: int | None = Column(Integer)
    general_type: str | None = Column(String)
    column_type: str | None = Column(String)
    db_data_type: str | None = Column(String)
    functional_data_type: str | None = Column(String)
    critical_data_element: bool | None = Column(Boolean)
    excluded_data_element: bool | None = Column(Boolean, nullable=True)
    pii_flag: str | None = Column(String(50), nullable=True)
    description: str | None = Column(String(1000))
    data_source: str | None = Column(String(40))
    source_system: str | None = Column(String(40))
    source_process: str | None = Column(String(40))
    business_domain: str | None = Column(String(40))
    stakeholder_group: str | None = Column(String(40))
    transform_level: str | None = Column(String(40))
    aggregation_level: str | None = Column(String(40))
    data_product: str | None = Column(String(40))
    drop_date: datetime | None = Column(postgresql.TIMESTAMP)
    last_complete_profile_run_id: UUID | None = Column(postgresql.UUID(as_uuid=True))
    dq_score_profiling: float | None = Column(Float)
    dq_score_testing: float | None = Column(Float)

    _default_order_by = (asc(ordinal_position), asc(column_name))

    # Unmapped columns: add_date, last_mod_date, test_ct, last_test_date,
    # tests_last_run, tests_7_days_prior, tests_30_days_prior, fails_last_run,
    # fails_7_days_prior, fails_30_days_prior, warnings_last_run,
    # warnings_7_days_prior, warnings_30_days_prior, valid_profile_issue_ct,
    # valid_test_issue_ct

    @classmethod
    def list_for_create_script(
        cls, table_groups_id: UUID, table_name: str,
    ) -> tuple[str | None, list[CreateScriptColumn]]:
        """Return ``(schema_name, columns)`` for a table's CREATE TABLE script.

        Columns are ordered by ordinal position and carry the profiling-derived type
        suggestion from their latest complete profiling run. Returns ``(None, [])`` when
        the table is not in the table group's profiled catalog.
        """
        query = (
            select(
                cls.schema_name,
                cls.column_name,
                cls.db_data_type,
                ProfileResult.datatype_suggestion,
            )
            .outerjoin(
                ProfileResult,
                and_(
                    ProfileResult.profile_run_id == cls.last_complete_profile_run_id,
                    ProfileResult.schema_name == cls.schema_name,
                    ProfileResult.table_name == cls.table_name,
                    ProfileResult.column_name == cls.column_name,
                ),
            )
            .where(
                cls.table_groups_id == table_groups_id,
                cls.table_name == table_name,
                cls.drop_date.is_(None),
            )
            .order_by(asc(cls.ordinal_position), asc(cls.column_name))
        )
        rows = get_current_session().execute(query).mappings().all()
        if not rows:
            return None, []
        columns = [
            CreateScriptColumn(
                column_name=row["column_name"],
                db_data_type=row["db_data_type"],
                datatype_suggestion=row["datatype_suggestion"],
            )
            for row in rows
        ]
        return rows[0]["schema_name"], columns

    @classmethod
    def list_for_table_group(
        cls,
        *clauses,
        table_groups_id: UUID,
        profiling_run_id: UUID | None = None,
        order_by: ColumnOrderBy | None = None,
        page: int,
        limit: int,
    ) -> tuple[list[ColumnProfileSummary], int]:
        # Local import: data_table imports DataColumnChars at module top.
        from testgen.common.models.data_table import DataTable

        profile_run_filter = (
            ProfileResult.profile_run_id == profiling_run_id
            if profiling_run_id is not None
            else ProfileResult.profile_run_id == cls.last_complete_profile_run_id
        )

        hygiene_subq_clauses = [
            HygieneIssue.table_groups_id == table_groups_id,
            func.coalesce(HygieneIssue.disposition, "Confirmed") == "Confirmed",
        ]
        if profiling_run_id is not None:
            hygiene_subq_clauses.append(HygieneIssue.profile_run_id == profiling_run_id)

        hygiene_subq = (
            select(
                HygieneIssue.profile_run_id.label("profile_run_id"),
                HygieneIssue.schema_name.label("schema_name"),
                HygieneIssue.table_name.label("table_name"),
                HygieneIssue.column_name.label("column_name"),
                func.count().label("hygiene_issue_count"),
            )
            .where(*hygiene_subq_clauses)
            .group_by(
                HygieneIssue.profile_run_id,
                HygieneIssue.schema_name,
                HygieneIssue.table_name,
                HygieneIssue.column_name,
            )
            .subquery()
        )

        cde_coalesced = case(
            (cls.critical_data_element.is_(True), True),
            (DataTable.critical_data_element.is_(True), True),
            else_=False,
        ).label("critical_data_element")

        query = (
            select(
                cls.column_name,
                cls.table_name,
                cls.general_type,
                cls.functional_data_type,
                ProfileResult.datatype_suggestion,
                cls.pii_flag,
                cde_coalesced,
                ProfileResult.record_ct,
                ProfileResult.null_value_ct,
                ProfileResult.distinct_value_ct,
                ProfileResult.filled_value_ct,
                cls.dq_score_profiling,
                cls.dq_score_testing,
                func.coalesce(hygiene_subq.c.hygiene_issue_count, 0).label("hygiene_issue_count"),
            )
            .outerjoin(DataTable, DataTable.id == cls.table_id)
            .outerjoin(
                ProfileResult,
                and_(
                    profile_run_filter,
                    ProfileResult.schema_name == cls.schema_name,
                    ProfileResult.table_name == cls.table_name,
                    ProfileResult.column_name == cls.column_name,
                ),
            )
            .outerjoin(
                hygiene_subq,
                and_(
                    hygiene_subq.c.profile_run_id == ProfileResult.profile_run_id,
                    hygiene_subq.c.schema_name == cls.schema_name,
                    hygiene_subq.c.table_name == cls.table_name,
                    hygiene_subq.c.column_name == cls.column_name,
                ),
            )
            .where(
                cls.table_groups_id == table_groups_id,
                cls.drop_date.is_(None),
                *clauses,
            )
        )

        null_ratio_expr = ProfileResult.null_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0)
        distinct_ratio_expr = ProfileResult.distinct_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0)
        filled_ratio_expr = ProfileResult.filled_value_ct * 1.0 / func.nullif(ProfileResult.record_ct, 0)
        # Deterministic tiebreaker so paginated callers don't see rows skip or duplicate
        # across pages when the primary sort has ties.
        tiebreaker = (asc(cls.table_name), asc(cls.ordinal_position), asc(cls.column_name))
        order_exprs: tuple
        if order_by is ColumnOrderBy.NULL_RATIO:
            order_exprs = (desc(null_ratio_expr).nulls_last(), *tiebreaker)
        elif order_by is ColumnOrderBy.DISTINCT_RATIO:
            order_exprs = (asc(distinct_ratio_expr).nulls_last(), *tiebreaker)
        elif order_by is ColumnOrderBy.FILLED_RATIO:
            order_exprs = (desc(filled_ratio_expr).nulls_last(), *tiebreaker)
        elif order_by is ColumnOrderBy.SCORE_PROFILING:
            order_exprs = (asc(cls.dq_score_profiling).nulls_last(), *tiebreaker)
        elif order_by is ColumnOrderBy.SCORE_TESTING:
            order_exprs = (asc(cls.dq_score_testing).nulls_last(), *tiebreaker)
        elif order_by is ColumnOrderBy.HYGIENE_COUNT:
            order_exprs = (desc(func.coalesce(hygiene_subq.c.hygiene_issue_count, 0)), *tiebreaker)
        else:
            order_exprs = tiebreaker

        query = query.order_by(*order_exprs)

        return cls._paginate(query, page=page, limit=limit, data_class=ColumnProfileSummary)

    @classmethod
    def get_column_detail(
        cls,
        table_groups_id: UUID,
        table_name: str,
        column_name: str,
        profiling_run_id: UUID | None = None,
    ) -> ColumnProfileDetail | None:
        """Fetch the L2 profile detail for a single column.

        When ``profiling_run_id`` is None, joins on the column's
        ``last_complete_profile_run_id`` so the caller gets the latest run.
        Returns None when the column does not exist in the table group.
        """
        from testgen.common.models.data_table import DataTable

        profile_run_filter = (
            ProfileResult.profile_run_id == profiling_run_id
            if profiling_run_id is not None
            else ProfileResult.profile_run_id == cls.last_complete_profile_run_id
        )

        hygiene_subq = (
            select(
                HygieneIssue.profile_run_id.label("profile_run_id"),
                HygieneIssue.schema_name.label("schema_name"),
                HygieneIssue.table_name.label("table_name"),
                HygieneIssue.column_name.label("column_name"),
                func.count().label("hygiene_issue_count"),
            )
            .where(
                HygieneIssue.table_groups_id == table_groups_id,
                func.coalesce(HygieneIssue.disposition, "Confirmed") == "Confirmed",
            )
            .group_by(
                HygieneIssue.profile_run_id,
                HygieneIssue.schema_name,
                HygieneIssue.table_name,
                HygieneIssue.column_name,
            )
            .subquery()
        )

        cde_coalesced = case(
            (cls.critical_data_element.is_(True), True),
            (DataTable.critical_data_element.is_(True), True),
            else_=False,
        ).label("critical_data_element")

        query = (
            select(
                cls.column_name,
                cls.table_name,
                cls.schema_name,
                cls.general_type,
                ProfileResult.column_type,
                cls.db_data_type,
                cls.functional_data_type,
                ProfileResult.datatype_suggestion,
                ProfileResult.functional_table_type,
                cls.pii_flag,
                cde_coalesced,
                ProfileResult.record_ct,
                ProfileResult.value_ct,
                ProfileResult.distinct_value_ct,
                ProfileResult.null_value_ct,
                ProfileResult.filled_value_ct,
                ProfileResult.zero_value_ct,
                ProfileResult.min_length,
                ProfileResult.max_length,
                ProfileResult.avg_length,
                ProfileResult.min_text,
                ProfileResult.max_text,
                ProfileResult.top_freq_values,
                ProfileResult.top_patterns,
                ProfileResult.distinct_std_value_ct,
                ProfileResult.distinct_pattern_ct,
                ProfileResult.std_pattern_match,
                ProfileResult.mixed_case_ct,
                ProfileResult.lower_case_ct,
                ProfileResult.upper_case_ct,
                ProfileResult.non_alpha_ct,
                ProfileResult.includes_digit_ct,
                ProfileResult.numeric_ct,
                ProfileResult.date_ct,
                ProfileResult.quoted_value_ct,
                ProfileResult.lead_space_ct,
                ProfileResult.embedded_space_ct,
                ProfileResult.avg_embedded_spaces,
                ProfileResult.zero_length_ct,
                ProfileResult.min_value,
                ProfileResult.min_value_over_0,
                ProfileResult.max_value,
                ProfileResult.avg_value,
                ProfileResult.stdev_value,
                ProfileResult.percentile_25,
                ProfileResult.percentile_50,
                ProfileResult.percentile_75,
                ProfileResult.min_date,
                ProfileResult.max_date,
                ProfileResult.before_1yr_date_ct,
                ProfileResult.before_5yr_date_ct,
                ProfileResult.before_20yr_date_ct,
                ProfileResult.within_1yr_date_ct,
                ProfileResult.within_1mo_date_ct,
                ProfileResult.future_date_ct,
                ProfileResult.boolean_true_ct,
                ProfileResult.query_error,
                cls.dq_score_profiling,
                cls.dq_score_testing,
                func.coalesce(hygiene_subq.c.hygiene_issue_count, 0).label("hygiene_issue_count"),
                ProfilingRun.id.label("profile_run_id"),
                ProfilingRun.job_execution_id.label("profile_run_je_id"),
                ProfilingRun.status.label("profile_run_status"),
                ProfilingRun.profiling_starttime.label("profile_run_started_at"),
                ProfilingRun.profiling_endtime.label("profile_run_ended_at"),
                ProfilingRun.log_message.label("profile_run_log_message"),
            )
            .outerjoin(DataTable, DataTable.id == cls.table_id)
            .outerjoin(
                ProfileResult,
                and_(
                    profile_run_filter,
                    ProfileResult.schema_name == cls.schema_name,
                    ProfileResult.table_name == cls.table_name,
                    ProfileResult.column_name == cls.column_name,
                ),
            )
            .outerjoin(
                hygiene_subq,
                and_(
                    hygiene_subq.c.profile_run_id == ProfileResult.profile_run_id,
                    hygiene_subq.c.schema_name == cls.schema_name,
                    hygiene_subq.c.table_name == cls.table_name,
                    hygiene_subq.c.column_name == cls.column_name,
                ),
            )
            .outerjoin(ProfilingRun, ProfilingRun.id == ProfileResult.profile_run_id)
            .where(
                cls.table_groups_id == table_groups_id,
                cls.table_name == table_name,
                cls.column_name == column_name,
                cls.drop_date.is_(None),
            )
            .limit(1)
        )

        row = get_current_session().execute(query).mappings().first()
        return ColumnProfileDetail(**row) if row else None

    @classmethod
    def search_by_name(
        cls,
        *clauses,
        pattern: str,
        page: int,
        limit: int,
    ) -> tuple[list[ColumnSearchHit], int]:
        """Cross-table-group column-name search. Scoping clauses are passed in by the caller.

        ``pattern`` is matched with ``ILIKE``. Callers are expected to pre-wrap bare
        tokens with ``%`` if substring search is desired; literal ``%`` / ``_`` from
        the caller are honored as wildcards.
        """
        # Local import: avoid circular dependency with TableGroup.
        from testgen.common.models.table_group import TableGroup

        query = (
            select(
                TableGroup.project_code,
                TableGroup.id.label("table_groups_id"),
                TableGroup.table_groups_name,
                cls.schema_name,
                cls.table_name,
                cls.column_name,
            )
            .join(TableGroup, TableGroup.id == cls.table_groups_id)
            .where(
                cls.column_name.ilike(pattern, escape="\\"),
                cls.drop_date.is_(None),
                *clauses,
            )
            .order_by(
                asc(TableGroup.project_code),
                asc(TableGroup.table_groups_name),
                asc(cls.table_name),
                asc(cls.column_name),
            )
        )

        return cls._paginate(query, page=page, limit=limit, data_class=ColumnSearchHit)

    @classmethod
    def summarize_matches_by_project(
        cls,
        *clauses,
        pattern: str,
    ) -> list[tuple[str, int]]:
        """Per-project match counts for a column-name search — same WHERE shape as :meth:`search_by_name`."""
        # Local import: avoid circular dependency with TableGroup.
        from testgen.common.models.table_group import TableGroup

        query = (
            select(TableGroup.project_code, func.count().label("match_count"))
            .select_from(cls)
            .join(TableGroup, TableGroup.id == cls.table_groups_id)
            .where(
                cls.column_name.ilike(pattern, escape="\\"),
                cls.drop_date.is_(None),
                *clauses,
            )
            .group_by(TableGroup.project_code)
            .order_by(TableGroup.project_code)
        )
        return [(row.project_code, row.match_count) for row in get_current_session().execute(query).all()]
