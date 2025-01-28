import uuid
import enum
from typing import Iterable, Literal, Self, TypedDict

from sqlalchemy import select, text
from sqlalchemy import Boolean, Column, Float, Enum, ForeignKey, String
from sqlalchemy.orm import relationship, joinedload
from sqlalchemy.dialects.postgresql import UUID

from testgen.common.models import Base, Session


class ScoreCategory(enum.Enum):
    table_groups_name = "table_groups_name"
    data_location = "data_location"
    data_source = "data_source"
    source_system = "source_system"
    source_process = "source_process"
    business_domain = "business_domain"
    stakeholder_group = "stakeholder_group"
    transform_level = "transform_level"
    dq_dimension = "dq_dimension"


class ScoreDefinition(Base):
    __tablename__ = "score_definitions"

    id: str = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_code: str = Column(String)
    name: str = Column(String, nullable=False)
    total_score: float = Column(Boolean, default=True, nullable=False)
    cde_score: float = Column(Boolean, default=False, nullable=False)
    category: ScoreCategory | None = Column(Enum(ScoreCategory), nullable=True)

    results: Iterable["ScoreDefinitionResult"] = relationship(
        "ScoreDefinitionResult",
        cascade="all, delete-orphan",
        order_by="ScoreDefinitionResult.category",
    )
    filters: Iterable["ScoreDefinitionFilter"] = relationship("ScoreDefinitionFilter", cascade="all, delete-orphan")

    def should_use_dimension_scores(self) -> bool:
        return (
            self.category == ScoreCategory.dq_dimension
            or any([f.field == "dq_dimension" for f in self.filters])
        )

    @classmethod
    def get(cls, id: str) -> "Self | None":
        definition = None
        with Session() as db_session:
            query = select(ScoreDefinition).options(joinedload(ScoreDefinition.filters)).where(ScoreDefinition.id == id)
            definition = db_session.scalars(query).first()
        return definition

    @classmethod
    def all(
        cls,
        project_code: str,
        name_filter: str | None = None,
        sorted_by: str | None = "name",
        fetch_filters: bool = False,
        fetch_results: bool = True,
    ) -> "Iterable[Self]":
        definitions = []
        with Session() as db_session:
            query = select(ScoreDefinition)
            if fetch_filters:
                query = query.options(joinedload(ScoreDefinition.filters))
            if fetch_results:
                query = query.options(joinedload(ScoreDefinition.results))
            if name_filter:
                query = query.where(ScoreDefinition.name.ilike(f"%{name_filter}%"))
            query = query.where(ScoreDefinition.project_code == project_code).order_by(text(sorted_by))
            print(query)
            definitions = db_session.scalars(query).unique().all()
        return definitions

    def save(self) -> None:
        with Session() as db_session:
            db_session.add(self)
            db_session.flush()
            db_session.commit()
            db_session.refresh(self, ["id"])

    def delete(self) -> None:
        with Session() as db_session:
            db_session.add(self)
            db_session.delete(self)
            db_session.commit()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id) if self.id else None,
            "project_code": self.project_code,
            "name": self.name,
            "total_score": self.total_score,
            "cde_score": self.cde_score,
            "category": self.category.value if self.category else None,
            "filters": [{"field": f.field, "value": f.value} for f in self.filters],
        }


class ScoreDefinitionFilter(Base):
    __tablename__ = "score_definition_filters"

    id: str = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: str = Column(UUID(as_uuid=True), ForeignKey("score_definitions.id", ondelete="CASCADE"))
    field: str = Column(String, nullable=False)
    value: str = Column(String, nullable=False)


class ScoreDefinitionResult(Base):
    __tablename__ = "score_definition_results"

    definition_id: str = Column(
        UUID(as_uuid=True),
        ForeignKey("score_definitions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    category: str = Column(String, nullable=False, primary_key=True)
    score: float = Column(Float, nullable=True)


class ScoreCard(TypedDict):
    id: str
    project_code: str
    name: str
    score: float
    cde_score: float
    profiling_score: float
    testing_score: float
    categories: list["CategoryScore"]
    definition: ScoreDefinition | None


class CategoryScore(TypedDict):
    label: str
    score: float


class SelectedIssue(TypedDict):
    id: str
    issue_type: Literal["hygiene", "test"]
