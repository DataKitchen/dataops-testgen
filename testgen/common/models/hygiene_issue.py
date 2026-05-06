import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, ForeignKey, String, and_, case, null, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import aliased, relationship
from sqlalchemy.sql.functions import func

from testgen.common.models import Base, get_current_session
from testgen.common.models.entity import Entity
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup

PII_RISK_RE = re.compile(r"Risk: (MODERATE|HIGH),")


class Disposition(StrEnum):
    """Stored disposition values for ``profile_anomaly_results.disposition`` and
    ``test_results.disposition``. The user-facing label for ``INACTIVE`` is "Muted"."""
    CONFIRMED = "Confirmed"
    DISMISSED = "Dismissed"
    INACTIVE = "Inactive"


class IssueLikelihood(StrEnum):
    """Stored ``profile_anomaly_types.issue_likelihood`` values."""
    DEFINITE = "Definite"
    LIKELY = "Likely"
    POSSIBLE = "Possible"
    POTENTIAL_PII = "Potential PII"


class PiiRisk(StrEnum):
    """Risk level extracted from PII issue ``detail`` strings via ``priority`` hybrid."""
    HIGH = "High"
    MODERATE = "Moderate"


@dataclass
class IssueLikelihoodCounts:
    """Counts of hygiene issues by likelihood category, with dismissed/inactive separated."""

    definite: int = 0
    likely: int = 0
    possible: int = 0
    dismissed: int = 0


@dataclass
class IssueCount:
    total: int = 0
    inactive: int = 0

    @property
    def active(self):
        return self.total - self.inactive


@dataclass
class HygieneIssueListRow:
    """Row shape for ``list_hygiene_issues``."""

    id: UUID
    project_code: str
    issue_type_name: str
    schema_name: str
    table_name: str
    column_name: str
    impact_dimension: str | None
    dq_dimension: str | None
    disposition: str
    priority: str | None
    detail: str
    detail_redactable: bool | None
    pii_flag: str | None


@dataclass
class HygieneIssueSearchRow:
    """Row shape for ``search_hygiene_issues``. Adds run + table-group context vs the list row."""

    id: UUID
    project_code: str
    issue_type_name: str
    table_groups_name: str
    job_execution_id: UUID | None
    started_at: datetime | None
    schema_name: str
    table_name: str
    column_name: str
    impact_dimension: str | None
    dq_dimension: str | None
    disposition: str
    priority: str | None
    detail: str
    detail_redactable: bool | None
    pii_flag: str | None


@dataclass
class HygieneIssueDetail:
    """Full row + type definition + column-profile context for ``get_hygiene_issue``."""

    id: UUID
    project_code: str
    issue_type_name: str
    type_description: str | None
    suggested_action: str | None
    schema_name: str
    table_name: str
    column_name: str
    dq_dimension: str | None
    impact_dimension: str | None
    disposition: str
    priority: str | None
    detail: str
    detail_redactable: bool | None
    pii_flag: str | None
    job_execution_id: UUID | None
    started_at: datetime | None
    column_general_type: str | None
    column_db_data_type: str | None
    column_record_ct: int | None
    column_null_value_ct: int | None
    column_distinct_value_ct: int | None


class HygieneIssueType(Base):
    __tablename__ = "profile_anomaly_types"

    id: str = Column(String, primary_key=True)
    likelihood: str = Column("issue_likelihood", String)
    name: str = Column("anomaly_name", String)
    description: str = Column("anomaly_description", String)
    suggested_action: str = Column(String)
    dq_dimension: str = Column(String)
    impact_dimension: str = Column(String)
    data_object: str = Column(String)
    detail_redactable: bool = Column(Boolean)

    # Unmapped: anomaly_type, anomaly_criteria, detail_expression,
    # dq_score_prevalence_formula, dq_score_risk_factor.

    @classmethod
    def select_where(cls, *clauses, order_by=None) -> list[Self]:
        query = select(cls).where(*clauses)
        if order_by is not None:
            query = query.order_by(*order_by)
        return list(get_current_session().scalars(query))


class HygieneIssue(Entity):
    __tablename__ = "profile_anomaly_results"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4)

    project_code: str = Column(String, ForeignKey("projects.project_code"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"), nullable=False)
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("profiling_runs.id"), nullable=False)

    type_id: str = Column("anomaly_id", String, ForeignKey("profile_anomaly_types.id"), nullable=False)
    type_ = relationship(HygieneIssueType)

    column_id: UUID = Column(postgresql.UUID(as_uuid=True))

    schema_name: str = Column(String, nullable=False)
    table_name: str = Column(String, nullable=False)
    column_name: str = Column(String, nullable=False)

    detail: str = Column(String, nullable=False)
    disposition: str = Column(String)
    impact_dimension: str = Column(String)

    # Unmapped: column_type, db_data_type, dq_prevalence.

    @hybrid_property
    def priority(self):
        if self.type_.likelihood != "Potential PII":
            return self.type_.likelihood
        elif self.detail and (match := PII_RISK_RE.search(self.detail)):
            return match.group(1).capitalize()
        else:
            return None

    @priority.expression
    def priority(cls):
        return case(
            (
                HygieneIssueType.likelihood != "Potential PII",
                HygieneIssueType.likelihood,
            ),
            else_=func.initcap(
                func.substring(cls.detail, PII_RISK_RE.pattern)
            ),
        )

    @classmethod
    def select_count_by_priority(cls, profiling_run_id: UUID) -> dict[str, IssueCount]:
        count_query = (
            select(
                cls.priority,
                func.count(),
                func.count(cls.disposition.in_(("Dismissed", "Inactive"))),
            )
            .select_from(cls)
            .join(HygieneIssueType)
            .where(cls.profile_run_id == profiling_run_id)
            .group_by(cls.priority)
        )
        result = {
            priority: IssueCount(total, inactive)
            for priority, total, inactive in get_current_session().execute(count_query)
        }
        for p in ("Definite", "Likely", "Possible", "High", "Moderate"):
            result.setdefault(p, IssueCount())
        return result

    @classmethod
    def count_by_likelihood(cls, profile_run_id: UUID) -> IssueLikelihoodCounts:
        """Count hygiene issues by likelihood category for a single profiling run."""
        dismissed = func.coalesce(cls.disposition, "Confirmed").in_(("Dismissed", "Inactive"))

        def _count_active(likelihood_values: tuple[str, ...]):
            return func.sum(case((~dismissed & HygieneIssueType.likelihood.in_(likelihood_values), 1), else_=0))

        query = (
            select(
                _count_active(("Definite",)).label("definite"),
                _count_active(("Likely",)).label("likely"),
                _count_active(("Possible", "Potential PII")).label("possible"),
                func.sum(case((dismissed, 1), else_=0)).label("dismissed"),
            )
            .select_from(cls)
            .join(HygieneIssueType, HygieneIssueType.id == cls.type_id)
            .where(cls.profile_run_id == profile_run_id)
        )

        row = get_current_session().execute(query).first()
        return IssueLikelihoodCounts(**{k: v for k, v in row._mapping.items() if v is not None})

    @classmethod
    def _priority_order(cls):
        return case(
            (cls.priority == "Definite", 1),
            (cls.priority == "Likely", 2),
            (cls.priority == "Possible", 3),
            (cls.priority == "High", 4),
            (cls.priority == "Moderate", 5),
            else_=6,
        )

    @classmethod
    def list_for_run(
        cls,
        job_execution_id: UUID,
        *clauses,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[HygieneIssueListRow], int]:
        """Paginated hygiene issues for a single profiling run, scoped by its job_execution_id.

        Caller-supplied ``*clauses`` carry every WHERE filter (project scoping, disposition,
        likelihood / pii_risk, table / column / dq_dimension / issue_type filters).
        """
        query = (
            select(
                cls.id.label("id"),
                cls.project_code.label("project_code"),
                HygieneIssueType.name.label("issue_type_name"),
                cls.schema_name.label("schema_name"),
                cls.table_name.label("table_name"),
                cls.column_name.label("column_name"),
                cls.impact_dimension.label("impact_dimension"),
                HygieneIssueType.dq_dimension.label("dq_dimension"),
                func.coalesce(cls.disposition, Disposition.CONFIRMED).label("disposition"),
                cls.priority.label("priority"),
                cls.detail.label("detail"),
                HygieneIssueType.detail_redactable.label("detail_redactable"),
                ProfileResult.pii_flag.label("pii_flag"),
            )
            .join(HygieneIssueType, HygieneIssueType.id == cls.type_id)
            .join(ProfilingRun, ProfilingRun.id == cls.profile_run_id)
            .outerjoin(
                ProfileResult,
                and_(
                    ProfileResult.profile_run_id == cls.profile_run_id,
                    ProfileResult.schema_name == cls.schema_name,
                    ProfileResult.table_name == cls.table_name,
                    ProfileResult.column_name == cls.column_name,
                ),
            )
            .where(ProfilingRun.job_execution_id == job_execution_id, *clauses)
            .order_by(cls._priority_order(), cls.table_name, cls.column_name, cls.id)
        )
        return cls._paginate(query, page=page, limit=limit, data_class=HygieneIssueListRow)

    @classmethod
    def search(
        cls,
        *clauses,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[HygieneIssueSearchRow], int]:
        """Cross-run paginated search over hygiene issues.

        Always JOINs ``ProfilingRun`` + ``JobExecution`` (for ``started_at`` + ``job_execution_id``)
        and ``TableGroup`` (for ``table_groups_name``). Caller-supplied ``*clauses`` carry every
        WHERE filter (project scoping, ``JobExecution.started_at`` window, all user filters).
        """
        query = (
            select(
                cls.id.label("id"),
                cls.project_code.label("project_code"),
                HygieneIssueType.name.label("issue_type_name"),
                TableGroup.table_groups_name.label("table_groups_name"),
                ProfilingRun.job_execution_id.label("job_execution_id"),
                JobExecution.started_at.label("started_at"),
                cls.schema_name.label("schema_name"),
                cls.table_name.label("table_name"),
                cls.column_name.label("column_name"),
                cls.impact_dimension.label("impact_dimension"),
                HygieneIssueType.dq_dimension.label("dq_dimension"),
                func.coalesce(cls.disposition, Disposition.CONFIRMED).label("disposition"),
                cls.priority.label("priority"),
                cls.detail.label("detail"),
                HygieneIssueType.detail_redactable.label("detail_redactable"),
                ProfileResult.pii_flag.label("pii_flag"),
            )
            .join(HygieneIssueType, HygieneIssueType.id == cls.type_id)
            .join(ProfilingRun, ProfilingRun.id == cls.profile_run_id)
            .outerjoin(JobExecution, JobExecution.id == ProfilingRun.job_execution_id)
            .join(TableGroup, TableGroup.id == cls.table_groups_id)
            .outerjoin(
                ProfileResult,
                and_(
                    ProfileResult.profile_run_id == cls.profile_run_id,
                    ProfileResult.schema_name == cls.schema_name,
                    ProfileResult.table_name == cls.table_name,
                    ProfileResult.column_name == cls.column_name,
                ),
            )
            .where(*clauses)
            .order_by(JobExecution.started_at.desc(), cls._priority_order(), cls.id)
        )
        return cls._paginate(query, page=page, limit=limit, data_class=HygieneIssueSearchRow)

    @classmethod
    def get_with_context(cls, issue_id: UUID, *clauses) -> HygieneIssueDetail | None:
        """Fetch one hygiene issue with type definition + column-profile context.

        Returns ``None`` when no row matches the id and ``*clauses`` together — the
        caller decides whether that's "missing", "not accessible", or both collapsed
        into one error.

        Joins ``ProfileResult`` outer-style: table-level issues may have no matching
        column profile row, in which case the column_* fields stay ``None``.
        """
        query = (
            select(
                cls.id.label("id"),
                cls.project_code.label("project_code"),
                HygieneIssueType.name.label("issue_type_name"),
                HygieneIssueType.description.label("type_description"),
                HygieneIssueType.suggested_action.label("suggested_action"),
                cls.schema_name.label("schema_name"),
                cls.table_name.label("table_name"),
                cls.column_name.label("column_name"),
                HygieneIssueType.dq_dimension.label("dq_dimension"),
                cls.impact_dimension.label("impact_dimension"),
                func.coalesce(cls.disposition, Disposition.CONFIRMED).label("disposition"),
                cls.priority.label("priority"),
                cls.detail.label("detail"),
                HygieneIssueType.detail_redactable.label("detail_redactable"),
                ProfileResult.pii_flag.label("pii_flag"),
                ProfilingRun.job_execution_id.label("job_execution_id"),
                JobExecution.started_at.label("started_at"),
                ProfileResult.general_type.label("column_general_type"),
                ProfileResult.db_data_type.label("column_db_data_type"),
                ProfileResult.record_ct.label("column_record_ct"),
                ProfileResult.null_value_ct.label("column_null_value_ct"),
                ProfileResult.distinct_value_ct.label("column_distinct_value_ct"),
            )
            .join(HygieneIssueType, HygieneIssueType.id == cls.type_id)
            .join(ProfilingRun, ProfilingRun.id == cls.profile_run_id)
            .outerjoin(JobExecution, JobExecution.id == ProfilingRun.job_execution_id)
            .outerjoin(
                ProfileResult,
                and_(
                    ProfileResult.profile_run_id == cls.profile_run_id,
                    ProfileResult.schema_name == cls.schema_name,
                    ProfileResult.table_name == cls.table_name,
                    ProfileResult.column_name == cls.column_name,
                ),
            )
            .where(cls.id == issue_id, *clauses)
        )
        row = get_current_session().execute(query).mappings().first()
        return HygieneIssueDetail(**row) if row else None

    @classmethod
    def update_disposition(cls, issue_id: UUID, disposition: str, *clauses) -> bool:
        """Update disposition on a single hygiene issue, scoped by caller-supplied clauses.

        Returns ``True`` if a row was updated, ``False`` if no row matched the id and
        ``*clauses`` together.
        """
        stmt = update(cls).where(cls.id == issue_id, *clauses).values(disposition=disposition)
        result = get_current_session().execute(stmt)
        return result.rowcount > 0

    @classmethod
    def select_with_diff(
        cls, profiling_run_id: UUID, other_profiling_run_id: UUID | None, *where_clauses, limit: int | None = None
    ) -> Iterable[tuple[Self,bool,str]]:
        other = aliased(cls)
        order_weight = case(
            (cls.priority == "Definite", 1),
            (cls.priority == "Likely", 2),
            (cls.priority == "Possible", 3),
            (cls.priority == "High", 4),
            (cls.priority == "Moderate", 5),
            else_=6,
        )
        is_new_col = (other.id.is_(None) if other_profiling_run_id else null()).label("is_new")
        query = (
            select(
                cls,
                is_new_col,
            )
            .outerjoin(
                other,
                and_(
                    other.table_groups_id == cls.table_groups_id,
                    other.schema_name == cls.schema_name,
                    other.table_name == cls.table_name,
                    other.column_name == cls.column_name,
                    other.type_id == cls.type_id,
                    other.profile_run_id == other_profiling_run_id,
                ),
            ).join(
                HygieneIssueType,
                HygieneIssueType.id == cls.type_id,
            ).where(
                cls.profile_run_id == profiling_run_id,
                *where_clauses
            ).order_by(
                is_new_col.desc(),
                order_weight,
            ).limit(
                limit,
            )
        )

        return get_current_session().execute(query)
