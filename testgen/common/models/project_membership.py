from datetime import datetime
from typing import Literal, Self
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import Column, ForeignKey, String, asc, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.models import get_current_session
from testgen.common.models.entity import Entity

RoleType = Literal["admin", "data_quality", "analyst", "business", "catalog"]


class ProjectMembership(Entity):
    __tablename__ = "project_memberships"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: UUID = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_code: str = Column(
        String,
        ForeignKey("projects.project_code", ondelete="CASCADE"),
        nullable=False,
    )
    role: "RoleType" = Column(String, nullable=False)
    created_at: datetime = Column(postgresql.TIMESTAMP, default=datetime.utcnow)

    _get_by = "id"
    _default_order_by = (asc(project_code),)

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_by_user_and_project(cls, user_id: UUID, project_code: str) -> Self | None:
        """Get a specific membership for a user in a project."""
        query = select(cls).where(
            cls.user_id == user_id,
            cls.project_code == project_code,
        )
        return get_current_session().scalars(query).first()

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_projects_for_user(cls, user_id: UUID) -> list[str]:
        """Get all project codes a user has access to."""
        query = select(cls.project_code).where(cls.user_id == user_id)
        return list(get_current_session().scalars(query).all())

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_memberships_for_user(cls, user_id: UUID) -> list[Self]:
        """Get all memberships for a user."""
        return list(cls.select_where(cls.user_id == user_id))

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_memberships_for_project(cls, project_code: str) -> list[Self]:
        """Get all memberships for a project."""
        return list(cls.select_where(cls.project_code == project_code))

    @classmethod
    def user_has_project_access(cls, user_id: UUID, project_code: str) -> bool:
        """Check if a user has any access to a project."""
        membership = cls.get_by_user_and_project(user_id, project_code)
        return membership is not None

    @classmethod
    def get_user_role_in_project(cls, user_id: UUID, project_code: str) -> "RoleType | None":
        """Get the user's role within a specific project."""
        membership = cls.get_by_user_and_project(user_id, project_code)
        return membership.role if membership else None

    @classmethod
    def clear_cache(cls) -> None:
        super().clear_cache()
        cls.get_by_user_and_project.clear()
        cls.get_projects_for_user.clear()
        cls.get_memberships_for_user.clear()
        cls.get_memberships_for_project.clear()
