from typing import Any

from sqlalchemy import Column, String, select
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert

from testgen.common.models import Base, get_current_session

NO_DEFAULT = type("NoDefaultSentinel", (), {})()


class SettingNotFound(ValueError):
    pass


class PersistedSetting(Base):
    __tablename__ = "settings"

    key: str = Column(String, primary_key=True)
    value: Any = Column(JSONB, nullable=False)

    @classmethod
    def get(cls, key: str, default=NO_DEFAULT) -> Any:
        # This caches all the settings in the session, so it hits the database only once
        get_current_session().execute(select(cls)).scalars().all()

        if ps := get_current_session().execute(select(cls).filter_by(key=key)).scalars().first():
            return ps.value
        elif default is NO_DEFAULT:
            raise SettingNotFound(f"Setting '{key}' not found")
        else:
            return default

    @classmethod
    def set(cls, key: str, value: Any):
        # Atomic upsert: avoids the check-then-insert race that bites when multiple
        # Streamlit reruns or sibling processes (UI + scheduler) touch the same key.
        session = get_current_session()
        stmt = pg_insert(cls).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
        session.execute(stmt)
        session.flush()

    def __repr__(self):
        return f"{self.__class__.__name__}(key={self.key!r} value={self.value!r})"
