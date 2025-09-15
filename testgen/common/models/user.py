from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import Column, String, asc, func, select, update
from sqlalchemy.dialects import postgresql

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import NullIfEmptyString
from testgen.common.models.entity import Entity

RoleType = Literal["admin", "data_quality", "analyst", "business", "catalog"]


class User(Entity):
    __tablename__ = "auth_users"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    username: str = Column(String)
    email: str = Column(NullIfEmptyString)
    name: str = Column(NullIfEmptyString)
    password: str = Column(String)
    role: RoleType = Column(String)
    latest_login: datetime = Column(postgresql.TIMESTAMP)

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
            db_session.commit()
            User.clear_cache()
        else:
            if update_latest_login:
                self.latest_login = datetime.now(UTC)
            super().save()

    @classmethod
    @st.cache_data(show_spinner=False)
    def get(cls, identifier: str) -> Self | None:
        query = select(cls).where(func.lower(User.username) == func.lower(identifier))
        return get_current_session().scalars(query).first()
