from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Column, String, asc
from sqlalchemy.dialects import postgresql

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

    _default_order_by = (asc(username),)
