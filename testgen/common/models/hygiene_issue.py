import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, String, and_, case, null, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import aliased, relationship
from sqlalchemy.sql.functions import func

from testgen.common.models import Base, get_current_session
from testgen.common.models.entity import Entity

PII_RISK_RE = re.compile(r"Risk: (MODERATE|HIGH),")


@dataclass
class IssueCount:
    total: int = 0
    inactive: int = 0

    @property
    def active(self):
        return self.total - self.inactive


class HygieneIssueType(Base):
    __tablename__ = "profile_anomaly_types"

    id: str = Column(String, primary_key=True)
    likelihood: str = Column("issue_likelihood", String)
    name: str = Column("anomaly_name", String)

    # Note: not all table columns are implemented by this entity


class HygieneIssue(Entity):
    __tablename__ = "profile_anomaly_results"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4)

    project_code: str = Column(String, ForeignKey("projects.project_code"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"), nullable=False)
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("profiling_runs.id"), nullable=False)

    type_id: str = Column("anomaly_id", String, ForeignKey("profile_anomaly_types.id"), nullable=False)
    type_ = relationship(HygieneIssueType)

    schema_name: str = Column(String, nullable=False)
    table_name: str = Column(String, nullable=False)
    column_name: str = Column(String, nullable=False)

    detail: str = Column(String, nullable=False)
    disposition: str = Column(String)

    # Note: not all table columns are implemented by this entity

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
