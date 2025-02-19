import enum
import uuid
from collections import defaultdict
from collections.abc import Iterable
from typing import Literal, Self, TypedDict

import pandas as pd
from sqlalchemy import Boolean, Column, Enum, Float, ForeignKey, Integer, String, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from testgen.common import read_template_sql_file
from testgen.common.models import Base, Session, engine
from testgen.utils import is_uuid4


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
    data_product = "data_product"


class ScoreDefinition(Base):
    __tablename__ = "score_definitions"

    id: str = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_code: str = Column(String)
    name: str = Column(String, nullable=False)
    total_score: bool = Column(Boolean, default=True, nullable=False)
    cde_score: bool = Column(Boolean, default=False, nullable=False)
    category: ScoreCategory | None = Column(Enum(ScoreCategory), nullable=True)

    results: Iterable["ScoreDefinitionResult"] = relationship(
        "ScoreDefinitionResult",
        cascade="all, delete-orphan",
        order_by="ScoreDefinitionResult.category",
        lazy="joined",
    )
    filters: Iterable["ScoreDefinitionFilter"] = relationship(
        "ScoreDefinitionFilter",
        cascade="all, delete-orphan",
        lazy="joined",
    )
    breakdown: Iterable["ScoreDefinitionBreakdownItem"] = relationship(
        "ScoreDefinitionBreakdownItem",
        cascade="all, delete-orphan",
        order_by="ScoreDefinitionBreakdownItem.impact.desc()",
        lazy="joined",
    )

    @classmethod
    def from_table_group(cls, table_group: dict) -> Self:
        definition = cls()
        definition.project_code = table_group["project_code"]
        definition.name = table_group["table_groups_name"]
        definition.total_score = True
        definition.cde_score = True
        definition.category = ScoreCategory.dq_dimension
        definition.filters = [
            ScoreDefinitionFilter(field="table_groups_name", value=table_group["table_groups_name"]),
        ]
        return definition

    @classmethod
    def get(cls, id_: str) -> "Self | None":
        if not is_uuid4(id_):
            return None
    
        definition = None
        with Session() as db_session:
            query = select(ScoreDefinition).where(ScoreDefinition.id == id_)
            definition = db_session.scalars(query).first()
        return definition

    @classmethod
    def all(
        cls,
        project_code: str | None = None,
        name_filter: str | None = None,
        sorted_by: str | None = "name",
    ) -> "Iterable[Self]":
        definitions = []
        with Session() as db_session:
            query = select(ScoreDefinition)
            if name_filter:
                query = query.where(ScoreDefinition.name.ilike(f"%{name_filter}%"))
            if project_code:
                query = query.where(ScoreDefinition.project_code == project_code)
            query = query.order_by(text(sorted_by))
            definitions = db_session.scalars(query).unique().all()
        return definitions

    def save(self) -> None:
        with Session() as db_session:
            db_session.add(self)
            db_session.flush([self])
            db_session.commit()
            db_session.refresh(self, ["id"])

    def delete(self) -> None:
        with Session() as db_session:
            db_session.add(self)
            db_session.delete(self)
            db_session.commit()

    def as_score_card(self) -> "ScoreCard":
        """
        Executes and combines two raw queries to build a fresh score
        card from this definition.

        Query templates:
        score_cards/get_overall_scores_by_column.sql
        score_cards/get_category_scores_by_column.sql
        score_cards/get_category_scores_by_dimension.sql
        """
        if len(self.filters) <= 0:
            return {
                "id": self.id,
                "project_code": self.project_code,
                "name": self.name,
                "score": None,
                "cde_score": None,
                "profiling_score": None,
                "testing_score": None,
                "categories": [],
                "definition": self,
            }

        overall_score_query_template_file = "get_overall_scores_by_column.sql"
        categories_query_template_file = "get_category_scores_by_column.sql"
        if self.category == ScoreCategory.dq_dimension:
            categories_query_template_file = "get_category_scores_by_dimension.sql"

        filters = " AND ".join(self._get_raw_query_filters())
        overall_scores = pd.read_sql_query(
            read_template_sql_file(
                overall_score_query_template_file,
                sub_directory="score_cards",
            ).replace("{filters}", filters),
            engine,
        )
        overall_scores = overall_scores.iloc[0].to_dict() if not overall_scores.empty else {}

        categories_scores = []
        if (category := self.category):
            categories_scores = pd.read_sql_query(
                read_template_sql_file(
                    categories_query_template_file,
                    sub_directory="score_cards",
                ).replace("{category}", category.value).replace("{filters}", filters),
                engine,
            )
            categories_scores = [category.to_dict() for _, category in categories_scores.iterrows()]

        return {
            "id": self.id,
            "project_code": self.project_code,
            "name": self.name,
            "score": overall_scores.get("score") if self.total_score else None,
            "cde_score": overall_scores.get("cde_score") if self.cde_score else None,
            "profiling_score": overall_scores.get("profiling_score") if self.total_score else None,
            "testing_score": overall_scores.get("testing_score") if self.total_score else None,
            "categories": categories_scores,
            "definition": self,
        }

    def get_score_card_breakdown(
        self,
        score_type: Literal["score", "cde_score"],
        group_by: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
    ) -> list[dict]:
        """
        Executes a raw query to filter and aggregate the score details
        associated to this definition.

        Query templates:
        get_score_card_breakdown_by_column.sql
        get_score_card_breakdown_by_dimension.sql
        """

        query_template_file = "get_score_card_breakdown_by_column.sql"
        if group_by == "dq_dimension":
            query_template_file = "get_score_card_breakdown_by_dimension.sql"

        columns = {
            "table_name": ["table_groups_id", "table_name"],
            "column_name": ["table_groups_id", "table_name", "column_name"],
        }.get(group_by, [group_by])
        filters = " AND ".join(self._get_raw_query_filters(cde_only=score_type == "cde_score"))
        join_condition = " AND ".join([f"test_records.{column} = profiling_records.{column}" for column in columns])

        profile_records_filters = self._get_raw_query_filters(
            cde_only=score_type == "cde_score",
            prefix="profiling_records.",
        )
        test_records_filters = self._get_raw_query_filters(cde_only=score_type == "cde_score", prefix="test_records.")
        records_count_filters = " AND ".join([
            f"({profile_filter} OR {test_filter})"
            for profile_filter, test_filter in zip(profile_records_filters, test_records_filters, strict=False)
        ])

        non_null_columns = [f"COALESCE(profiling_records.{col}, test_records.{col}) AS {col}" for col in columns]

        # ruff: noqa: RUF027
        query = (
            read_template_sql_file(query_template_file, sub_directory="score_cards")
            .replace("{columns}", ", ".join(columns))
            .replace("{group_by}", group_by)
            .replace("{filters}", filters)
            .replace("{join_condition}", join_condition)
            .replace("{records_count_filters}", records_count_filters)
            .replace("{non_null_columns}", ", ".join(non_null_columns))
        )
        results = pd.read_sql_query(query, engine)

        return [row.to_dict() for _, row in results.iterrows()]

    def get_score_card_issues(
        self,
        score_type: Literal["score", "cde_score"],
        group_by: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
        value: str,
    ):
        """
        Executes a raw query to get the list of issues associated to the
        specified breakdown item.

        Query templates:
        get_score_card_issues_by_column.sql
        get_score_card_issues_by_dimension.sql
        """
        query_template_file = "get_score_card_issues_by_column.sql"
        if group_by == "dq_dimension":
            query_template_file = "get_score_card_issues_by_dimension.sql"

        value_ = value
        filters = self._get_raw_query_filters(cde_only=score_type == "cde_score")
        if group_by == "table_name":
            table_group_id, value_ = value.split(".")
            filters.append(f"table_groups_id = '{table_group_id}'")
        elif group_by == "column_name":
            table_group_id, table_name, value_ = value.split(".")
            filters.append(f"table_groups_id = '{table_group_id}'")
            filters.append(f"table_name = '{table_name}'")
        filters = " AND ".join(filters)

        dq_dimension_filter = ""
        if group_by == "dq_dimension":
            dq_dimension_filter = f" AND dq_dimension = '{value_}'"

        query = (
            read_template_sql_file(query_template_file, sub_directory="score_cards")
            .replace("{filters}", filters)
            .replace("{group_by}", group_by)
            .replace("{value}", value_)
            .replace("{dq_dimension_filter}", dq_dimension_filter)
        )
        results = pd.read_sql_query(query, engine)
        return [row.to_dict() for _, row in results.iterrows()]

    def _get_raw_query_filters(self, cde_only: bool = False, prefix: str | None = None) -> list[str]:
        values_by_field = defaultdict(list)
        for filter_ in self.filters:
            values_by_field[filter_.field].append(f"'{filter_.value}'")
        values_by_field["project_code"].append(f"'{self.project_code}'")
        if cde_only:
            values_by_field["critical_data_element"].append("true")

        return [
            f"{prefix or ''}{field} IN ({', '.join(values)})" for field, values in values_by_field.items()
        ]

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


class ScoreDefinitionBreakdownItem(Base):
    __tablename__ = "score_definition_results_breakdown"

    id: str = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    definition_id: str = Column(
        UUID(as_uuid=True),
        ForeignKey("score_definitions.id", ondelete="CASCADE"),
    )
    category: str = Column(String, nullable=False)
    score_type: str = Column(String, nullable=False)
    table_groups_id: str = Column(String, nullable=True)
    table_name: str = Column(String, nullable=True)
    column_name: str = Column(String, nullable=True)
    dq_dimension: str = Column(String, nullable=True)
    semantic_data_type: str = Column(String, nullable=True)
    impact: float = Column(Float)
    score: float = Column(Float)
    issue_ct: int = Column(Integer)

    @classmethod
    def filter(
        cls,
        *,
        definition_id: str,
        category: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
        score_type: Literal["score", "cde_score"],
    ) -> "Iterable[Self]":
        items = []
        with Session() as db_session:
            query = select(ScoreDefinitionBreakdownItem).where(
                ScoreDefinitionBreakdownItem.definition_id == definition_id,
                ScoreDefinitionBreakdownItem.category == category,
                ScoreDefinitionBreakdownItem.score_type == score_type,
            ).order_by(ScoreDefinitionBreakdownItem.impact.desc())
            items = db_session.scalars(query).unique().all()
        return items

    def to_dict(self) -> dict:
        category_fields = {
            "table_name": ["table_groups_id", "table_name"],
            "column_name": ["table_groups_id", "table_name", "column_name"],
        }.get(self.category, [self.category])
        return {
            **{field_name: getattr(self, field_name) for field_name in category_fields},
            "impact": self.impact,
            "score": self.score,
            "issue_ct": self.issue_ct,
        }


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
