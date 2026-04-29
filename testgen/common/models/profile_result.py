from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, asc
from sqlalchemy.dialects import postgresql

from testgen.common.models.entity import Entity


class ProfileResult(Entity):
    __tablename__ = "profile_results"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("profiling_runs.id"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    schema_name: str = Column(String)
    table_name: str = Column(String)
    column_name: str = Column(String)
    position: int = Column(Integer)

    general_type: str | None = Column(String)
    functional_data_type: str | None = Column(String)
    datatype_suggestion: str | None = Column(String)
    db_data_type: str | None = Column(String)
    pii_flag: str | None = Column(String(50))

    record_ct: int | None = Column(BigInteger)
    value_ct: int | None = Column(BigInteger)
    null_value_ct: int | None = Column(BigInteger)
    distinct_value_ct: int | None = Column(BigInteger)
    filled_value_ct: int | None = Column(BigInteger)

    _default_order_by = (asc(position), asc(column_name))

    # Additional columns exist on this table (type-specific profile stats).
    # They'll be mapped here as new MCP tools need them (L2+).
