from dataclasses import dataclass
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import Column, String, asc, text
from sqlalchemy.dialects import postgresql

from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.custom_types import NullIfEmptyString
from testgen.common.models.entity import Entity, EntityMinimal


@dataclass
class ProjectSummary(EntityMinimal):
    project_code: str
    connection_count: int
    default_connection_id: int
    table_group_count: int
    profiling_run_count: int
    test_suite_count: int
    test_definition_count: int
    test_run_count: int
    can_export_to_observability: bool


class Project(Entity):
    __tablename__ = "projects"

    id: UUID = Column(postgresql.UUID(as_uuid=True), default=uuid4)
    project_code: str = Column(String, primary_key=True, nullable=False)
    project_name: str = Column(String)
    observability_api_url: str = Column(NullIfEmptyString)
    observability_api_key: str = Column(NullIfEmptyString)

    _get_by = "project_code"
    _default_order_by = (asc(project_name),)

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_summary(cls, project_code: str) -> ProjectSummary | None:
        query = """
        SELECT
            (
                SELECT COUNT(*) AS count FROM connections WHERE connections.project_code = :project_code
            ) AS connection_count,
            (
                SELECT connection_id FROM connections WHERE connections.project_code = :project_code LIMIT 1
            ) AS default_connection_id,
            (
                SELECT COUNT(*) FROM table_groups WHERE table_groups.project_code = :project_code
            ) AS table_group_count,
            (
                SELECT COUNT(*)
                FROM profiling_runs
                    LEFT JOIN table_groups ON profiling_runs.table_groups_id = table_groups.id
                WHERE table_groups.project_code = :project_code
            ) AS profiling_run_count,
            (
                SELECT COUNT(*) FROM test_suites WHERE test_suites.project_code = :project_code
            ) AS test_suite_count,
            (
                SELECT COUNT(*)
                FROM test_definitions
                    LEFT JOIN test_suites ON test_definitions.test_suite_id = test_suites.id
                WHERE test_suites.project_code = :project_code
            ) AS test_definition_count,
            (
                SELECT COUNT(*)
                FROM test_runs
                    LEFT JOIN test_suites ON test_runs.test_suite_id = test_suites.id
                WHERE test_suites.project_code = :project_code
            ) AS test_run_count,
            (
                SELECT COALESCE(observability_api_key, '') <> ''
                    AND COALESCE(observability_api_url, '') <> ''
                FROM projects
                WHERE project_code = :project_code
            ) AS can_export_to_observability;
        """

        db_session = get_current_session()
        result = db_session.execute(text(query), {"project_code": project_code}).first()
        return ProjectSummary(**result, project_code=project_code) if result else None

    @classmethod
    def is_in_use(cls, ids: list[str]) -> bool:
        connections = Connection.select_minimal_where(Connection.project_code.in_(ids))
        return len(connections) > 0

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> bool:
        connections = Connection.select_minimal_where(Connection.project_code.in_(ids))
        if connections:
            Connection.cascade_delete([item.connection_id for item in connections])
        cls.delete_where(cls.project_code.in_(ids))

    @classmethod
    def clear_cache(cls) -> bool:
        super().clear_cache()
        cls.get_summary.clear()
