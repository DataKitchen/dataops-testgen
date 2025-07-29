from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Identity,
    Integer,
    String,
    asc,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.database.flavor.flavor_service import SQLFlavor
from testgen.common.models import get_current_session
from testgen.common.models.custom_types import EncryptedBytea
from testgen.common.models.entity import ENTITY_HASH_FUNCS, Entity, EntityMinimal
from testgen.common.models.table_group import TableGroup
from testgen.utils import is_uuid4

SQLFlavorCode = Literal["redshift", "snowflake", "mssql", "azure_mssql", "synapse_mssql", "postgresql", "databricks"]


@dataclass
class ConnectionMinimal(EntityMinimal):
    project_code: str
    connection_id: int
    sql_flavor_code: SQLFlavorCode
    connection_name: str


class Connection(Entity):
    __tablename__ = "connections"

    id: UUID = Column(postgresql.UUID(as_uuid=True), default=uuid4)
    project_code: str = Column(String, ForeignKey("projects.project_code"))
    connection_id: int = Column(BigInteger, Identity(always=True), primary_key=True)
    sql_flavor: SQLFlavor = Column(String)
    sql_flavor_code: SQLFlavorCode = Column(String)
    project_host: str = Column(String)
    project_port: str = Column(String)
    project_user: str = Column(String)
    project_db: str = Column(String)
    connection_name: str = Column(String)
    project_pw_encrypted: str = Column(EncryptedBytea)
    max_threads: int = Column(Integer, default=4)
    max_query_chars: int = Column(Integer)
    url: str = Column(String, default="")
    connect_by_url: bool = Column(Boolean, default=False)
    connect_by_key: bool = Column(Boolean, default=False)
    private_key: str = Column(EncryptedBytea)
    private_key_passphrase: str = Column(EncryptedBytea)
    http_path: str = Column(String)

    _get_by = "connection_id"
    _default_order_by = (asc(connection_name),)
    _minimal_columns = ConnectionMinimal.__annotations__.keys()

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_minimal(cls, identifier: int) -> ConnectionMinimal | None:
        result = cls._get_columns(identifier, cls._minimal_columns)
        return ConnectionMinimal(**result) if result else None

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_by_table_group(cls, table_group_id: str | UUID) -> Self | None:
        if not is_uuid4(table_group_id):
            return None

        query = select(cls).join(TableGroup).where(TableGroup.id == table_group_id)
        return get_current_session().scalars(query).first()

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[ConnectionMinimal]:
        results = cls._select_columns_where(cls._minimal_columns, *clauses, order_by=order_by)
        return [ConnectionMinimal(**row) for row in results]

    @classmethod
    def has_running_process(cls, ids: list[str]) -> bool:
        table_groups = TableGroup.select_minimal_where(TableGroup.connection_id.in_(ids))
        if table_groups:
            return TableGroup.has_running_process([item.id for item in table_groups])
        return False

    @classmethod
    def is_in_use(cls, ids: list[str]) -> bool:
        table_groups = TableGroup.select_minimal_where(TableGroup.connection_id.in_(ids))
        return len(table_groups) > 0

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> bool:
        table_groups = TableGroup.select_minimal_where(TableGroup.connection_id.in_(ids))
        if table_groups:
            TableGroup.cascade_delete([item.id for item in table_groups])
        cls.delete_where(cls.connection_id.in_(ids))

    @classmethod
    def clear_cache(cls) -> bool:
        super().clear_cache()
        cls.get_minimal.clear()
        cls.get_by_table_group.clear()
        cls.select_minimal_where.clear()

    def save(self) -> None:
        if self.connect_by_url and self.url:
            url_sections = self.url.split("/")
            if url_sections:
                host_port = url_sections[0]
                host_port_sections = host_port.split(":")
                self.project_host = host_port_sections[0] if host_port_sections else host_port
                self.project_port = "".join(host_port_sections[1:]) if host_port_sections else ""
            if len(url_sections) > 1:
                self.project_db = url_sections[1]

        super().save()
