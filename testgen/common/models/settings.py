from typing import Any

from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import JSONB

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
        get_current_session().query(cls).all()

        if ps := get_current_session().query(cls).filter_by(key=key).first():
            return ps.value
        elif default is NO_DEFAULT:
            raise SettingNotFound(f"Setting '{key}' not found")
        else:
            return default

    @classmethod
    def set(cls, key: str, value: Any):
        session = get_current_session()
        if ps := session.query(cls).filter_by(key=key).first():
            ps.value = value
        else:
            session.add(cls(key=key, value=value))
        session.commit()

    def __repr__(self):
        return f"{self.__class__.__name__}(key={self.key!r} value={self.value!r})"
