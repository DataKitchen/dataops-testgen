import enum
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Literal, Self, TypedDict

import pandas as pd
from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from testgen.common import read_template_sql_file
from testgen.common.models import Base, engine, get_current_session
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
    history: Iterable["ScoreDefinitionResultHistoryEntry"] = relationship(
        "ScoreDefinitionResultHistoryEntry",
        order_by="ScoreDefinitionResultHistoryEntry.last_run_time.asc()",
        cascade="all, delete-orphan",
        lazy="select",
        back_populates="definition",
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
        db_session = get_current_session()
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
        db_session = get_current_session()
        query = select(ScoreDefinition)
        if name_filter:
            query = query.where(ScoreDefinition.name.ilike(f"%{name_filter}%"))
        if project_code:
            query = query.where(ScoreDefinition.project_code == project_code)
        query = query.order_by(text(sorted_by))
        definitions = db_session.scalars(query).unique().all()
        return definitions

    def save(self) -> None:
        db_session = get_current_session()
        db_session.add(self)
        db_session.flush([self])
        db_session.commit()
        db_session.refresh(self, ["id"])

    def delete(self) -> None:
        db_session = get_current_session()
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
                "history": [],
                "definition": self,
            }

        overall_score_query_template_file = "get_overall_scores_by_column.sql"
        categories_query_template_file = "get_category_scores_by_column.sql"
        if self.category == ScoreCategory.dq_dimension:
            categories_query_template_file = "get_category_scores_by_dimension.sql"

        filters = " AND ".join(self._get_raw_query_filters())
        overall_scores = get_current_session().execute(
            read_template_sql_file(
                overall_score_query_template_file,
                sub_directory="score_cards",
            ).replace("{filters}", filters)
        ).mappings().first() or {}

        categories_scores = []
        if (category := self.category):
            categories_scores = [
                dict(result)
                for result in get_current_session().execute(
                    read_template_sql_file(
                        categories_query_template_file,
                        sub_directory="score_cards",
                    ).replace("{category}", category.value).replace("{filters}", filters)
                ).mappings().all()
            ]

        return {
            "id": self.id,
            "project_code": self.project_code,
            "name": self.name,
            "score": overall_scores.get("score") if self.total_score else None,
            "cde_score": overall_scores.get("cde_score") if self.cde_score else None,
            "profiling_score": overall_scores.get("profiling_score") if self.total_score else None,
            "testing_score": overall_scores.get("testing_score") if self.total_score else None,
            "categories": categories_scores,
            "history": [],
            "definition": self,
        }

    def as_cached_score_card(self) -> "ScoreCard":
        """Reads the cached values to build a scorecard"""
        root_keys: list[str] = ["score", "profiling_score", "testing_score", "cde_score"]
        score_card: ScoreCard = {
            "id": self.id,
            "project_code": self.project_code,
            "name": self.name,
            "categories": [],
            "history": [],
            "definition": self,
        }

        for result in sorted(self.results, key=lambda r: r.category):
            if result.category in root_keys:
                score_card[result.category] = result.score
                continue
            score_card["categories"].append({"label": result.category, "score": result.score})

        history_categories: list[str] = []
        if self.total_score:
            history_categories.append("score")
        if self.cde_score:
            history_categories.append("cde_score")

        for entry in self.history[-50:]:
            if entry.category in history_categories:
                score_card["history"].append({"score": entry.score, "category": entry.category, "time": entry.last_run_time})

        return score_card

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

    def recalculate_scores_history(self) -> None:
        """
        Executes a raw query to get the total score and cde score for
        each history entry of this definition.

        Query templates:
        get_historical_overall_scores_by_column.sql
        """
        template = "get_historical_overall_scores_by_column.sql"
        query = (
            read_template_sql_file(template, sub_directory="score_cards")
            .replace("{filters}", " AND ".join(self._get_raw_query_filters()))
            .replace("{definition_id}", str(self.id))
        )
        overall_scores = get_current_session().execute(query).mappings().all()
        current_history: dict[tuple[datetime, str, str], ScoreDefinitionResultHistoryEntry] = {}
        for entry in self.history:
            current_history[(entry.last_run_time, entry.category,)] = entry

        renewed_history: dict[tuple[datetime, str, str], float] = {}
        for scores in overall_scores:
            renewed_history[(scores["last_run_time"], "score",)] = scores["score"]
            renewed_history[(scores["last_run_time"], "cde_score",)] = scores["cde_score"]

        for key, entry in current_history.items():
            entry.score = renewed_history[key]

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
        db_session = get_current_session()
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


class ScoreDefinitionResultHistoryEntry(Base):
    __tablename__ = "score_definition_results_history"

    definition_id: str = Column(
        UUID(as_uuid=True),
        ForeignKey("score_definitions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    category: str = Column(String, nullable=False, primary_key=True)
    score: float = Column(Float, nullable=True)
    last_run_time: datetime = Column(DateTime(timezone=False), nullable=False, primary_key=True)

    definition: ScoreDefinition = relationship("ScoreDefinition", back_populates="history")

    def add_as_cutoff(self):
        """
        Insert new records into table 'score_history_latest_runs'
        corresponding to the latest profiling and test runs as of
        `self.last_run_time`.

        Query templates:
        add_latest_runs.sql
        """
        # ruff: noqa: RUF027
        query = (
            read_template_sql_file("add_latest_runs.sql", sub_directory="score_cards")
            .replace("{project_code}", self.definition.project_code)
            .replace("{definition_id}", str(self.definition_id))
            .replace("{score_history_cutoff_time}", self.last_run_time.isoformat())
        )
        session = get_current_session()
        session.execute(query)


class ScoreCard(TypedDict):
    id: str
    project_code: str
    name: str
    score: float
    cde_score: float
    profiling_score: float
    testing_score: float
    categories: list["CategoryScore"]
    history: list["HistoryEntry"]
    definition: ScoreDefinition | None


class CategoryScore(TypedDict):
    label: str
    score: float


class SelectedIssue(TypedDict):
    id: str
    issue_type: Literal["hygiene", "test"]


class HistoryEntry(TypedDict):
    score: float
    category: Literal["score", "cde_score"]
    time: datetime
