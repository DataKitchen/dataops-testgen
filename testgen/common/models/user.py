from datetime import UTC, datetime
from typing import Self
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import Boolean, Column, String, asc, func, select, text, update
from sqlalchemy.dialects import postgresql

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import NullIfEmptyString
from testgen.common.models.entity import Entity
from testgen.common.models.project_membership import RoleType


class User(Entity):
    __tablename__ = "auth_users"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    username: str = Column(String)
    email: str = Column(NullIfEmptyString)
    name: str = Column(NullIfEmptyString)
    password: str = Column(String)
    is_global_admin: bool = Column(Boolean, nullable=False, default=False)
    latest_login: datetime = Column(postgresql.TIMESTAMP)
    preferences: dict = Column(postgresql.JSONB, nullable=False, server_default=text("'{}'"))

    _get_by = "username"
    _default_order_by = (asc(func.lower(username)),)

    def save(self, update_latest_login: bool = False) -> None:
        if self.id and not update_latest_login:
            values = {
                column.key: getattr(self, column.key, None)
                for column in self.__table__.columns
                if column != User.latest_login
            }
            query = update(User).where(User.id == self.id).values(**values)
            db_session = get_current_session()
            db_session.execute(query)
        else:
            if update_latest_login:
                self.latest_login = datetime.now(UTC)
            super().save()

    def update_preferences(self) -> None:
        query = update(User).where(User.id == self.id).values(preferences=self.preferences)
        get_current_session().execute(query)

    @classmethod
    @st.cache_data(show_spinner=False)
    def get(cls, identifier: str) -> Self | None:
        query = select(cls).where(func.lower(User.username) == func.lower(identifier))
        return get_current_session().scalars(query).first()

    def get_accessible_projects(self) -> list[str]:
        """Get all projects this user can access."""
        from testgen.common.models.project_membership import ProjectMembership
        return ProjectMembership.get_projects_for_user(self.id)

    def get_role_in_project(self, project_code: str) -> RoleType | None:
        """Get this user's role in a specific project."""
        from testgen.common.models.project_membership import ProjectMembership
        return ProjectMembership.get_user_role_in_project(self.id, project_code)

    def has_project_access(self, project_code: str) -> bool:
        """Check if user has access to a project."""
        from testgen.common.models.project_membership import ProjectMembership
        return ProjectMembership.user_has_project_access(self.id, project_code)
