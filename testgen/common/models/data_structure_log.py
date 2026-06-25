from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, String, asc, desc, select
from sqlalchemy.dialects import postgresql

from testgen.common.models import get_current_session
from testgen.common.models.entity import Entity, EntityMinimal

# Schema-change codes stored in ``data_structure_log.change``. ``M`` only ever
# appears on column-level rows (column-name set, old/new data type populated).
SCHEMA_CHANGE_ADDED = "A"
SCHEMA_CHANGE_DROPPED = "D"
SCHEMA_CHANGE_MODIFIED = "M"


@dataclass
class DataStructureLogEntry(EntityMinimal):
    """One schema-change event for a table or column in a table group.

    ``column_name`` is ``None`` for table-level events (add / drop of an entire
    table); set for column-level events. ``change`` is the stored single-letter
    code (``A`` / ``D`` / ``M``); callers translate to user-facing words.
    """
    log_id: UUID
    table_groups_id: UUID
    table_name: str
    column_name: str | None
    change_date: datetime
    change: str
    old_data_type: str | None
    new_data_type: str | None


class DataStructureLog(Entity):
    __tablename__ = "data_structure_log"

    log_id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True))
    table_id: UUID = Column(postgresql.UUID(as_uuid=True))
    column_id: UUID = Column(postgresql.UUID(as_uuid=True))
    table_name: str = Column(String)
    column_name: str = Column(String)
    change_date: datetime = Column(postgresql.TIMESTAMP)
    change: str = Column(String)
    old_data_type: str = Column(String)
    new_data_type: str = Column(String)

    _get_by = "log_id"
    _default_order_by = (desc(change_date), asc(table_name), asc(column_name))

    @classmethod
    def list_for_table_group(
        cls,
        table_group_id: str | UUID,
        *,
        table_name: str | None = None,
        since: date | datetime | None = None,
        until: date | datetime | None = None,
        page: int = 1,
        limit: int | None = 20,
    ) -> tuple[list[DataStructureLogEntry], int]:
        """Paginated schema-change audit log for one table group, newest first.

        Filters by ``table_name`` (exact match; the audit log stores names
        case-sensitively as the source emitted them), ``since`` (lower-bound on
        ``change_date``), and ``until`` (upper-bound). ``limit=None`` skips
        pagination — the caller gets every matching row in one shot.
        """
        query = select(
            cls.log_id,
            cls.table_groups_id,
            cls.table_name,
            cls.column_name,
            cls.change_date,
            cls.change,
            cls.old_data_type,
            cls.new_data_type,
        ).where(cls.table_groups_id == table_group_id)
        if table_name is not None:
            query = query.where(cls.table_name == table_name)
        if since is not None:
            query = query.where(cls.change_date >= since)
        if until is not None:
            query = query.where(cls.change_date <= until)
        query = query.order_by(*cls._default_order_by)

        if limit is None:
            rows = get_current_session().execute(query).mappings().all()
            entries = [DataStructureLogEntry(**row) for row in rows]
            return entries, len(entries)
        return cls._paginate(query, page=page, limit=limit, data_class=DataStructureLogEntry)
