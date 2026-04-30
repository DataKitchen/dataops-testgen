from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import zip_longest
from typing import ClassVar, Literal
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    String,
    Text,
    TypeDecorator,
    asc,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.expression import case, literal

from testgen.common.models import Base, get_current_session
from testgen.common.models.custom_types import NullIfEmptyString, YNString, ZeroIfEmptyInteger
from testgen.common.models.entity import ENTITY_HASH_FUNCS, Entity, EntityMinimal
from testgen.utils import is_uuid4

TestRunType = Literal["QUERY", "CAT", "METADATA"]
TestScope = Literal["column", "referential", "table", "tablegroup", "custom"]
TestRunStatus = Literal["Running", "Complete", "Error", "Cancelled"]


class ParamFieldsMixin:
    """Parsed access to default_parm_columns/prompts/help metadata.

    Mixed into both TestTypeSummary (dataclass) and TestType (ORM model).
    """

    @property
    def param_columns(self) -> set[str]:
        """Column names declared as editable parameters for this test type."""
        return {column for column, _, _ in self.param_fields}

    @property
    def param_fields(self) -> list[tuple[str, str, str]]:
        """Parsed parameter metadata as (column, prompt, help) tuples, preserving order."""
        if not self.default_parm_columns:
            return []
        columns = [c.strip() for c in self.default_parm_columns.split(",")]
        prompts = [p.strip() for p in self.default_parm_prompts.split(",")] if self.default_parm_prompts else []
        helps = [h.strip() for h in self.default_parm_help.split("|")] if self.default_parm_help else []
        # Pad prompts with column names (sensible fallback) and helps with ""
        prompts.extend(columns[len(prompts):])
        return list(zip_longest(columns, prompts, helps, fillvalue=""))


@dataclass
class TestTypeSummary(ParamFieldsMixin, EntityMinimal):
    test_name_short: str
    default_test_description: str
    measure_uom: str
    measure_uom_description: str
    default_parm_columns: str
    default_parm_prompts: str
    default_parm_help: str
    default_parm_required: str
    default_severity: str
    test_scope: TestScope
    dq_dimension: str
    default_impact_dimension: str
    usage_notes: str


@dataclass
class TestDefinitionSummary(TestTypeSummary):
    id: UUID
    table_groups_id: UUID
    profile_run_id: UUID
    test_type: str
    test_suite_id: UUID
    test_description: str
    schema_name: str
    table_name: str
    column_name: str
    skip_errors: int
    baseline_ct: str
    baseline_unique_ct: str
    baseline_value: str
    baseline_value_ct: str
    threshold_value: str
    baseline_sum: str
    baseline_avg: str
    baseline_sd: str
    lower_tolerance: str
    upper_tolerance: str
    subset_condition: str
    groupby_names: str
    having_condition: str
    window_date_column: str
    window_days: int
    match_schema_name: str
    match_table_name: str
    match_column_names: str
    match_subset_condition: str
    match_groupby_names: str
    match_having_condition: str
    custom_query: str
    history_calculation: str
    history_calculation_upper: str
    history_lookback: int
    test_active: bool
    test_definition_status: str
    severity: str
    lock_refresh: bool
    last_auto_gen_date: datetime
    profiling_as_of_date: datetime
    last_manual_update: datetime
    export_to_observability: bool
    prediction: dict[str, dict[str, float]] | None
    flagged: bool
    impact_dimension: str | None

    @property
    def display_name(self) -> str:
        """Human-readable test type name, falling back to the internal code."""
        return self.test_name_short or self.test_type


@dataclass
class TestDefinitionMinimal(EntityMinimal):
    id: UUID
    table_groups_id: UUID
    test_type: str
    test_suite_id: UUID
    schema_name: str
    table_name: str
    column_name: str
    test_active: bool
    lock_refresh: bool
    test_name_short: str


class QueryString(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, _dialect) -> str | None:
        if value and isinstance(value, str):
            value = value.strip()
            if value.endswith(";"):
                value = value[:-1]
        return value or None


class TestType(ParamFieldsMixin, Entity):
    __tablename__ = "test_types"

    _get_by = "test_type"

    id: str = Column(String)
    test_type: str = Column(String, primary_key=True, nullable=False)
    test_name_short: str = Column(String)
    test_name_long: str = Column(String)
    test_description: str = Column(String)
    except_message: str = Column(String)
    measure_uom: str = Column(String)
    measure_uom_description: str = Column(String)
    selection_criteria: str = Column(Text)
    dq_score_prevalence_formula: str = Column(Text)
    dq_score_risk_factor: str = Column(Text)
    column_name_prompt: str = Column(Text)
    column_name_help: str = Column(Text)
    default_parm_columns: str = Column(Text)
    default_parm_values: str = Column(Text)
    default_parm_prompts: str = Column(Text)
    default_parm_help: str = Column(Text)
    default_parm_required: str = Column(Text)
    default_severity: str = Column(String)
    run_type: TestRunType = Column(String)
    test_scope: TestScope = Column(String)
    dq_dimension: str = Column(String)
    impact_dimension: str = Column(String)
    health_dimension: str = Column(String)
    threshold_description: str = Column(String)
    usage_notes: str = Column(String)
    active: str = Column(String)

    # Unmapped columns: generation_template, result_visualization, result_visualization_params

    _summary_columns = (
        *[key for key in TestTypeSummary.__annotations__.keys() if key != "default_test_description"],
        test_description.label("default_test_description"),
    )

    @classmethod
    def select_summary_where(cls, *clauses) -> Iterable[TestTypeSummary]:
        results = cls._select_columns_where(cls._summary_columns, *clauses)
        return [TestTypeSummary(**row) for row in results]


class TestDefinition(Entity):
    __tablename__ = "test_definitions"

    # default=uuid4: Python-side ID for ORM inserts (enables batch flush without per-row round-trips).
    # server_default: fallback for raw SQL inserts in test generation templates that omit the id column.
    id: UUID = Column(postgresql.UUID(as_uuid=True), default=uuid4, server_default=text("gen_random_uuid()"), primary_key=True)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True))
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True))
    test_type: str = Column(String)
    test_suite_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_suites.id"), nullable=False)
    test_description: str = Column(NullIfEmptyString)
    schema_name: str = Column(String)
    table_name: str = Column(NullIfEmptyString)
    column_name: str = Column(NullIfEmptyString)
    skip_errors: int = Column(ZeroIfEmptyInteger)
    baseline_ct: str = Column(NullIfEmptyString)
    baseline_unique_ct: str = Column(NullIfEmptyString)
    baseline_value: str = Column(NullIfEmptyString)
    baseline_value_ct: str = Column(NullIfEmptyString)
    threshold_value: str = Column(NullIfEmptyString)
    baseline_sum: str = Column(NullIfEmptyString)
    baseline_avg: str = Column(NullIfEmptyString)
    baseline_sd: str = Column(NullIfEmptyString)
    lower_tolerance: str = Column(NullIfEmptyString)
    upper_tolerance: str = Column(NullIfEmptyString)
    subset_condition: str = Column(NullIfEmptyString)
    groupby_names: str = Column(NullIfEmptyString)
    having_condition: str = Column(NullIfEmptyString)
    window_date_column: str = Column(NullIfEmptyString)
    window_days: int = Column(ZeroIfEmptyInteger)
    match_schema_name: str = Column(NullIfEmptyString)
    match_table_name: str = Column(NullIfEmptyString)
    match_column_names: str = Column(NullIfEmptyString)
    match_subset_condition: str = Column(NullIfEmptyString)
    match_groupby_names: str = Column(NullIfEmptyString)
    match_having_condition: str = Column(NullIfEmptyString)
    history_calculation: str = Column(NullIfEmptyString)
    history_calculation_upper: str = Column(NullIfEmptyString)
    history_lookback: int = Column(ZeroIfEmptyInteger, default=0)
    test_mode: str = Column(String)
    custom_query: str = Column(QueryString)
    test_active: bool = Column(YNString, default="Y")
    test_definition_status: str = Column(NullIfEmptyString)
    severity: str = Column(NullIfEmptyString)
    watch_level: str = Column(String, default="WARN")
    check_result: str = Column(String)
    lock_refresh: bool = Column(YNString, default="N", nullable=False)
    last_auto_gen_date: datetime = Column(postgresql.TIMESTAMP)
    profiling_as_of_date: datetime = Column(postgresql.TIMESTAMP)
    last_manual_update: datetime = Column(postgresql.TIMESTAMP)
    export_to_observability: bool = Column(YNString)
    prediction: dict[str, dict[str, float]] | None = Column(postgresql.JSONB)
    flagged: bool = Column(Boolean, default=False, nullable=False)
    external_id: UUID | None = Column(postgresql.UUID(as_uuid=True))
    impact_dimension: str | None = Column(String, nullable=True)

    _default_order_by = (
        asc(func.lower(schema_name)),
        asc(func.lower(table_name)),
        asc(func.lower(column_name)),
        asc(test_type),
    )
    _summary_columns = (
        *TestDefinitionSummary.__annotations__.keys(),
        *[key for key in TestTypeSummary.__annotations__.keys() if key not in ("default_test_description", "default_impact_dimension")],
        TestType.test_description.label("default_test_description"),
        TestType.impact_dimension.label("default_impact_dimension"),
    )
    _minimal_columns = TestDefinitionMinimal.__annotations__.keys()
    _update_exclude_columns = (
        id,
        table_groups_id,
        profile_run_id,
        test_type,
        test_suite_id,
        schema_name,
        test_mode,
        watch_level,
        check_result,
        last_auto_gen_date,
        profiling_as_of_date,
        prediction,
        external_id,
    )

    @classmethod
    @st.cache_data(show_spinner=False)
    def get(cls, identifier: str | UUID) -> TestDefinitionSummary | None:
        if not is_uuid4(identifier):
            return None

        result = cls._get_columns(
            identifier,
            cls._summary_columns,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
        )
        return TestDefinitionSummary(**result) if result else None

    @classmethod
    def get_for_project(
        cls, identifier: UUID, project_codes: list[str] | None = None,
    ) -> TestDefinitionSummary | None:
        """Fetch a test definition with project-level access check.

        Returns None if the definition doesn't exist, belongs to a monitor suite, or the user lacks access.
        """
        from testgen.common.models.test_suite import TestSuite

        select_columns = [
            getattr(cls, col, None) or getattr(TestType, col) if isinstance(col, str) else col
            for col in cls._summary_columns
        ]
        query = (
            select(*select_columns)
            .join(TestType, cls.test_type == TestType.test_type)
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(cls.id == identifier, TestSuite.is_monitor.isnot(True))
        )
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        result = get_current_session().execute(query).mappings().first()
        return TestDefinitionSummary(**result) if result else None

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def select_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[TestDefinitionSummary]:
        results = cls._select_columns_where(
            cls._summary_columns,
            *clauses,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            order_by=order_by,
        )
        return [TestDefinitionSummary(**row) for row in results]

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[TestDefinitionMinimal]:
        results = cls._select_columns_where(
            cls._minimal_columns,
            *clauses,
            join_target=TestType,
            join_clause=cls.test_type == TestType.test_type,
            order_by=order_by,
        )
        return [TestDefinitionMinimal(**row) for row in results]

    @classmethod
    def list_for_suite(
        cls,
        test_suite_id: UUID,
        project_codes: list[str] | None = None,
        table_name: str | None = None,
        test_type: str | None = None,
        test_active: bool | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[TestDefinitionSummary], int]:
        """Paginated test definitions for a suite, with optional filters.

        Monitor suites are always filtered out — callers requesting a monitor suite get an empty page.
        Project-level access is enforced when ``project_codes`` is set.
        """
        from testgen.common.models.test_suite import TestSuite

        select_columns = [
            getattr(cls, col, None) or getattr(TestType, col) if isinstance(col, str) else col
            for col in cls._summary_columns
        ]
        query = (
            select(*select_columns)
            .join(TestType, cls.test_type == TestType.test_type)
            .join(TestSuite, cls.test_suite_id == TestSuite.id)
            .where(cls.test_suite_id == test_suite_id, TestSuite.is_monitor.isnot(True))
        )
        if project_codes is not None:
            query = query.where(TestSuite.project_code.in_(project_codes))
        if table_name:
            query = query.where(cls.table_name == table_name)
        if test_type:
            query = query.where(cls.test_type == test_type)
        if test_active is not None:
            query = query.where(cls.test_active == test_active)
        query = query.order_by(*cls._default_order_by)
        return cls._paginate(query, page=page, limit=limit, data_class=TestDefinitionSummary)

    _yn_columns: ClassVar = {"test_active", "lock_refresh"}

    @classmethod
    def set_status_attribute(
        cls,
        status_type: Literal["test_active", "lock_refresh", "flagged"],
        test_definition_ids: list[str | UUID],
        value: bool,
    ) -> None:
        query = f"""
        WITH selected AS (
            SELECT UNNEST(ARRAY [:test_definition_ids]) AS id
        )
        UPDATE test_definitions
        SET {status_type} = :value
            {", test_definition_status = NULL" if status_type == "test_active" and value else ""}
        FROM test_definitions td
            INNER JOIN selected ON (td.id = selected.id::UUID)
        WHERE td.id = test_definitions.id;
        """
        params = {
            "test_definition_ids": test_definition_ids,
            "value": YNString().process_bind_param(value, None) if status_type in cls._yn_columns else value,
        }

        db_session = get_current_session()
        db_session.execute(text(query), params)

    @classmethod
    def move(
        cls,
        test_definition_ids: list[str | UUID],
        target_table_group_id: str | UUID,
        target_test_suite_id: str | UUID,
        target_table_name: str | None = None,
        target_column_name: str | None = None,
    ) -> None:
        query = f"""
        WITH selected AS (
            SELECT UNNEST(ARRAY [:test_definition_ids]) AS id
        )
        UPDATE test_definitions
        SET
            {"table_name = :target_table_name," if target_table_name else ""}
            {"column_name = :target_column_name," if target_column_name else ""}
            table_groups_id = :target_table_group,
            test_suite_id = :target_test_suite
        FROM test_definitions td
            INNER JOIN selected ON (td.id = selected.id::UUID)
        WHERE td.id = test_definitions.id;
        """
        params = {
            "test_definition_ids": test_definition_ids,
            "target_table_group": target_table_group_id,
            "target_test_suite": target_test_suite_id,
            "target_table_name": target_table_name,
            "target_column_name": target_column_name,
        }

        db_session = get_current_session()
        db_session.execute(text(query), params)

    @classmethod
    def copy(
        cls,
        test_definition_ids: list[str | UUID],
        target_table_group_id: str | UUID,
        target_test_suite_id: str | UUID,
        target_table_name: str | None = None,
        target_column_name: str | None = None,
    ) -> None:
        modified_columns = [cls.id, cls.table_groups_id, cls.profile_run_id, cls.test_suite_id, cls.last_auto_gen_date]

        select_columns = [
            func.gen_random_uuid().label("id"),
            literal(target_table_group_id).label("table_groups_id"),
            case(
                (cls.table_groups_id == target_table_group_id, cls.profile_run_id),
                else_=None,
            ).label("profile_run_id"),
            literal(target_test_suite_id).label("test_suite_id"),
            literal(None).label("last_auto_gen_date"),
        ]

        if target_table_name:
            modified_columns.append(cls.table_name)
            select_columns.append(literal(target_table_name).label("table_name"))

        if target_column_name:
            modified_columns.append(cls.column_name)
            select_columns.append(literal(target_column_name).label("column_name"))

        other_columns = [
            column for column in cls.__table__.columns if column not in modified_columns and column != cls.id
        ]
        select_columns.extend(other_columns)

        query = insert(cls).from_select(
            [*modified_columns, *other_columns], select(*select_columns).where(cls.id.in_(test_definition_ids))
        )
        db_session = get_current_session()
        db_session.execute(query)

    @classmethod
    def get_source_data_context(cls, test_definition_id: UUID, project_codes: list[str] | None = None) -> dict | None:
        """Get the fields needed by the source data service for a given test definition."""
        session = get_current_session()

        sql = """
            SELECT
                d.table_groups_id,
                tt.id AS test_type_id,
                d.id AS test_definition_id,
                d.test_type,
                d.schema_name,
                d.table_name,
                d.column_name AS column_names,
                dcc.column_type,
                ts.project_code
            FROM test_definitions d
            INNER JOIN test_types tt ON d.test_type = tt.test_type
            INNER JOIN test_suites ts ON d.test_suite_id = ts.id
            LEFT JOIN data_column_chars dcc
                ON d.table_groups_id = dcc.table_groups_id
                AND d.schema_name = dcc.schema_name
                AND d.table_name = dcc.table_name
                AND d.column_name = dcc.column_name
            WHERE d.id = :test_definition_id
        """
        params: dict = {"test_definition_id": str(test_definition_id)}

        if project_codes is not None:
            sql += " AND ts.project_code = ANY(:project_codes)"
            params["project_codes"] = project_codes

        result = session.execute(text(sql), params).first()
        return dict(result._mapping) if result else None

    def save(self) -> None:
        if self.id:
            values = {
                column.key: getattr(self, column.key, None)
                for column in self.__table__.columns
                if column not in self._update_exclude_columns
            }
            query = update(TestDefinition).where(TestDefinition.id == self.id).values(**values)
            db_session = get_current_session()
            db_session.execute(query)
        else:
            super().save()


class TestDefinitionNote(Base):
    __tablename__ = "test_definition_notes"

    id: UUID = Column(postgresql.UUID(as_uuid=True), default=uuid4, primary_key=True)
    test_definition_id: UUID = Column(
        postgresql.UUID(as_uuid=True), ForeignKey("test_definitions.id", ondelete="CASCADE"), nullable=False
    )
    detail: str = Column(Text, nullable=False)
    created_by: str = Column(String(100), nullable=False)
    created_at: datetime = Column(postgresql.TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: datetime = Column(postgresql.TIMESTAMP)

    @classmethod
    def add_note(cls, test_definition_id: str | UUID, detail: str, username: str) -> None:
        db_session = get_current_session()
        db_session.execute(
            insert(cls).values(test_definition_id=test_definition_id, detail=detail, created_by=username)
        )

    @classmethod
    def update_note(cls, note_id: str | UUID, detail: str) -> None:
        db_session = get_current_session()
        db_session.execute(update(cls).where(cls.id == note_id).values(detail=detail, updated_at=func.now()))

    @classmethod
    def delete_note(cls, note_id: str | UUID) -> None:
        db_session = get_current_session()
        db_session.execute(delete(cls).where(cls.id == note_id))

    @classmethod
    def get_notes_count_by_ids(cls, test_definition_ids: list[str]) -> dict[str, int]:
        """Returns {test_definition_id: count} for all given IDs."""
        db_session = get_current_session()
        rows = db_session.execute(
            text("""
                SELECT test_definition_id::VARCHAR, COUNT(*) as cnt
                FROM test_definition_notes
                WHERE test_definition_id = ANY(:ids)
                GROUP BY test_definition_id
            """),
            {"ids": [UUID(td_id) for td_id in test_definition_ids]},
        ).all()
        return {str(row[0]): row[1] for row in rows}

    @classmethod
    def get_notes(cls, test_definition_id: str | UUID) -> list[dict]:
        db_session = get_current_session()
        results = (
            db_session.execute(
                select(cls).where(cls.test_definition_id == test_definition_id).order_by(cls.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": str(note.id),
                "detail": note.detail,
                "created_by": note.created_by,
                "created_at": note.created_at.isoformat() if note.created_at else None,
                "updated_at": note.updated_at.isoformat() if note.updated_at else None,
            }
            for note in results
        ]
