from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import streamlit as st
from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Identity,
    String,
    Text,
    TypeDecorator,
    asc,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.expression import case, literal

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import NullIfEmptyString, UpdateTimestamp, YNString, ZeroIfEmptyInteger
from testgen.common.models.entity import ENTITY_HASH_FUNCS, Entity, EntityMinimal
from testgen.utils import is_uuid4

TestRunStatus = Literal["Running", "Complete", "Error", "Cancelled"]


@dataclass
class TestDefinitionSummary(EntityMinimal):
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
    test_active: str
    test_definition_status: str
    severity: str
    lock_refresh: str
    last_auto_gen_date: datetime
    profiling_as_of_date: datetime
    last_manual_update: datetime
    export_to_observability: str
    test_name_short: str
    default_test_description: str
    measure_uom: str
    measure_uom_description: str
    default_parm_columns: str
    default_parm_prompts: str
    default_parm_help: str
    default_severity: str
    test_scope: str
    usage_notes: str


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


class TestType(Entity):
    __tablename__ = "test_types"

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
    default_severity: str = Column(String)
    run_type: str = Column(String)
    test_scope: str = Column(String)
    dq_dimension: str = Column(String)
    health_dimension: str = Column(String)
    threshold_description: str = Column(String)
    usage_notes: str = Column(String)
    active: str = Column(String)


class TestDefinition(Entity):
    __tablename__ = "test_definitions"

    id: UUID = Column(postgresql.UUID(as_uuid=True))
    cat_test_id: int = Column(BigInteger, Identity(), primary_key=True)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True))
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True))
    test_type: str = Column(String)
    test_suite_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_suites.id"), nullable=False)
    test_description: str = Column(NullIfEmptyString)
    test_action: str = Column(String)
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
    last_manual_update: datetime = Column(UpdateTimestamp, nullable=False)
    export_to_observability: bool = Column(YNString)

    _default_order_by = (asc(schema_name), asc(table_name), asc(column_name), asc(test_type))
    _summary_columns = (
        *[key for key in TestDefinitionSummary.__annotations__.keys() if key != "default_test_description"],
        TestType.test_description.label("default_test_description"),
    )
    _minimal_columns = TestDefinitionMinimal.__annotations__.keys()
    _update_exclude_columns = (
        id,
        cat_test_id,
        table_groups_id,
        profile_run_id,
        test_type,
        test_suite_id,
        test_action,
        schema_name,
        test_mode,
        watch_level,
        check_result,
        last_auto_gen_date,
        profiling_as_of_date,
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
    def set_status_attribute(
        cls,
        status_type: Literal["test_active", "lock_refresh"],
        test_definition_ids: list[str | UUID],
        value: bool,
    ) -> None:
        query = f"""
        WITH selected AS (
            SELECT UNNEST(ARRAY [:test_definition_ids]) AS id
        )
        UPDATE test_definitions
        SET {status_type} = :value
        FROM test_definitions td
            INNER JOIN selected ON (td.id = selected.id::UUID)
        WHERE td.id = test_definitions.id;
        """
        params = {
            "test_definition_ids": test_definition_ids,
            "value": YNString().process_bind_param(value, None),
        }

        db_session = get_current_session()
        db_session.execute(text(query), params)
        db_session.commit()
        cls.clear_cache()

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
        db_session.commit()
        cls.clear_cache()

    @classmethod
    def copy(
        cls,
        test_definition_ids: list[str | UUID],
        target_table_group_id: str | UUID,
        target_test_suite_id: str | UUID,
        target_table_name: str | None = None,
        target_column_name: str | None = None,
    ) -> None:
        id_columns = (cls.id, cls.cat_test_id)
        modified_columns = [cls.table_groups_id, cls.profile_run_id, cls.test_suite_id]

        select_columns = [
            literal(target_table_group_id).label("table_groups_id"),
            case(
                (cls.table_groups_id == target_table_group_id, cls.profile_run_id),
                else_=None,
            ).label("profile_run_id"),
            literal(target_test_suite_id).label("test_suite_id"),
        ]

        if target_table_name:
            modified_columns.append(cls.table_name)
            select_columns.append(literal(target_table_name).label("table_name"))

        if target_column_name:
            modified_columns.append(cls.column_name)
            select_columns.append(literal(target_column_name).label("column_name"))

        other_columns = [
            column for column in cls.__table__.columns if column not in modified_columns and column not in id_columns
        ]
        select_columns.extend(other_columns)

        query = insert(cls).from_select(
            [*modified_columns, *other_columns], select(select_columns).where(cls.id.in_(test_definition_ids))
        )
        db_session = get_current_session()
        db_session.execute(query)
        db_session.commit()
        cls.clear_cache()

    @classmethod
    def clear_cache(cls) -> bool:
        super().clear_cache()
        cls.select_minimal_where.clear()

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
            db_session.commit()
        else:
            super().save()

        TestDefinition.clear_cache()
