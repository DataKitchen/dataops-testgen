from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Self
from uuid import UUID

import streamlit as st
from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import BinaryExpression

from testgen.common.models import Base, get_current_session
from testgen.utils import is_uuid4, make_json_safe

ENTITY_HASH_FUNCS = {
    BinaryExpression: lambda x: str(x.compile(compile_kwargs={"literal_binds": True})),
    tuple: lambda x: [str(y) for y in x],
}


@dataclass
class EntityMinimal:
    @classmethod
    def columns(cls) -> list[str]:
        return list(cls.__annotations__.keys())

    def to_dict(self, json_safe: bool = False) -> dict[str, Any]:
        result = asdict(self)
        if json_safe:
            return {key: make_json_safe(value) for key, value in result.items()}
        return result


class Entity(Base):
    __abstract__ = True

    _get_by: str = "id"
    _default_order_by: tuple[str | InstrumentedAttribute] = ("id",)

    @classmethod
    @st.cache_data(show_spinner=False)
    def get(cls, identifier: str | int | UUID) -> Self | None:
        get_by_column = getattr(cls, cls._get_by)
        if isinstance(get_by_column.property.columns[0].type, postgresql.UUID) and not is_uuid4(identifier):
            return None

        query = select(cls).where(get_by_column == identifier)
        return get_current_session().scalars(query).first()

    @classmethod
    def get_minimal(cls, identifier: str | int | UUID) -> Any:
        raise NotImplementedError

    @classmethod
    def _get_columns(
        cls,
        identifier: str | int | UUID,
        columns: list[str | InstrumentedAttribute],
        join_target: Self | None = None,
        join_clause: BinaryExpression | None = None,
    ) -> Self | None:
        get_by_column = getattr(cls, cls._get_by)
        if isinstance(get_by_column.property.columns[0].type, postgresql.UUID) and not is_uuid4(identifier):
            return None

        if join_target:
            select_columns = [
                getattr(cls, col, None) or getattr(join_target, col) if isinstance(col, str) else col for col in columns
            ]
            query = select(select_columns).join(join_target, join_clause)
        else:
            select_columns = [getattr(cls, col) if isinstance(col, str) else col for col in columns]
            query = select(select_columns)

        query = query.where(get_by_column == identifier)
        return get_current_session().execute(query).first()

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def select_where(cls, *clauses, order_by: tuple[str | InstrumentedAttribute] | None = None) -> Iterable[Self]:
        order_by = order_by or cls._default_order_by
        query = select(cls).where(*clauses).order_by(*order_by)
        return get_current_session().scalars(query).all()

    @classmethod
    def select_minimal_where(cls, *clauses, order_by: tuple[str | InstrumentedAttribute]) -> Iterable[Any]:
        raise NotImplementedError

    @classmethod
    def _select_columns_where(
        cls,
        columns: list[str | InstrumentedAttribute],
        *clauses,
        join_target: Self | None = None,
        join_clause: BinaryExpression | None = None,
        order_by: tuple[str | InstrumentedAttribute] | None = None,
    ) -> Self | None:
        if join_target:
            select_columns = [
                getattr(cls, col, None) or getattr(join_target, col) if isinstance(col, str) else col for col in columns
            ]
            query = select(select_columns).join(join_target, join_clause)
        else:
            select_columns = [getattr(cls, col) if isinstance(col, str) else col for col in columns]
            query = select(select_columns)

        order_by = order_by or cls._default_order_by
        query = query.where(*clauses).order_by(*order_by)
        return get_current_session().execute(query).all()

    @classmethod
    def has_running_process(cls, ids: list[str]) -> bool:
        raise NotImplementedError

    @classmethod
    def delete_where(cls, *clauses) -> None:
        query = delete(cls).where(*clauses)
        db_session = get_current_session()
        db_session.execute(query)
        db_session.commit()
        # We clear all because cached data like Project.select_summary will be affected
        st.cache_data.clear()

    @classmethod
    def is_in_use(cls, ids: list[str]) -> bool:
        raise NotImplementedError

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> None:
        raise NotImplementedError

    @classmethod
    def clear_cache(cls) -> None:
        cls.get.clear()
        cls.select_where.clear()

    @classmethod
    def columns(cls) -> list[str]:
        return list(cls.__annotations__.keys())

    def save(self) -> None:
        is_new = self.id is None
        db_session = get_current_session()
        db_session.add(self)
        db_session.flush([self])
        db_session.commit()
        db_session.refresh(self, ["id"])
        if is_new:
            # We clear all because cached data like Project.select_summary will be affected
            st.cache_data.clear()
        else:
            self.__class__.clear_cache()

    def delete(self) -> None:
        db_session = get_current_session()
        db_session.add(self)
        db_session.delete(self)
        db_session.commit()
        self.__class__.clear_cache()

    def to_dict(self, json_safe: bool = False):
        result = {col.name: getattr(self, col.name) for col in self.__table__.columns}
        if json_safe:
            return {key: make_json_safe(value) for key, value in result.items()}
        return result
