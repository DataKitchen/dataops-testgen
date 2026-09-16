import re
from datetime import datetime
from typing import Any, Self
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    ColumnElement,
    ForeignKey,
    Integer,
    String,
    func,
    literal_column,
    select,
    text,
)
from sqlalchemy.dialects import postgresql

from testgen.common.models.custom_types import NullIfEmptyString
from testgen.common.models.entity import Entity

_QUALIFIED_COLUMN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*\Z")


class SuiteVersion(Entity):
    __tablename__ = "suite_versions"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    test_suite_id: UUID = Column(
        postgresql.UUID(as_uuid=True), ForeignKey("test_suites.id", ondelete="CASCADE")
    )
    version: int = Column(Integer, nullable=False)
    metadata_document: dict[str, Any] | None = Column(postgresql.JSONB(none_as_null=True))
    frozen_document: str | None = Column(String)
    frozen_at: datetime | None = Column(postgresql.TIMESTAMP(timezone=True))
    odcs_api_version: str | None = Column(String)
    label: str | None = Column(NullIfEmptyString)
    created_by: str | None = Column(String)
    created_at: datetime = Column(
        postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: datetime = Column(
        postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    @classmethod
    def get(cls, identifier: str | int | UUID, *clauses) -> Self | None:
        """Fetch a version by id, accepting any UUID rather than only version 4.

        The placeholder version's id is the nil UUID, which ``Entity.get`` rejects when it
        arrives as a string. Returns ``None`` when the identifier is not a UUID at all.
        """
        if not isinstance(identifier, UUID):
            try:
                identifier = UUID(str(identifier))
            except (ValueError, TypeError):
                return None
        return super().get(identifier, *clauses)

    @classmethod
    def resolved_for(cls, suite_id) -> ColumnElement[UUID]:
        """The version a read of the given suite's rows scopes to.

        The suite's draft where one exists, otherwise its highest frozen version, otherwise the
        placeholder. Accepts a literal id or a column expression and returns a correlated scalar
        subquery, so a caller that does not know the suite until the query runs can still scope
        by it.
        """
        draft = (
            select(cls.id)
            .where(cls.test_suite_id == suite_id, cls.frozen_at.is_(None))
            .scalar_subquery()
        )
        latest_frozen = (
            select(cls.id)
            .where(cls.test_suite_id == suite_id)
            .order_by(cls.version.desc())
            .limit(1)
            .scalar_subquery()
        )
        placeholder = select(cls.id).where(cls.test_suite_id.is_(None)).scalar_subquery()
        return func.coalesce(draft, latest_frozen, placeholder)

    @classmethod
    def resolved_for_sql(cls, suite_column: str) -> str:
        """``resolved_for`` as SQL text, for hand-written queries that cannot hold an expression.

        The result is a scalar expression, not a join: three correlated subqueries over
        ``suite_versions`` wrapped in ``coalesce``, each comparing that table's own
        ``test_suite_id`` to ``suite_column``. It goes on the right of ``version_id = ...``, and
        ``suite_column`` is a free reference resolved in the surrounding query's scope.

        The qualifier is required, and may not be ``suite_versions``. Either way the name would
        bind to the subqueries' own table instead of the outer row, making the comparison a
        tautology: every suite resolves to whichever draft the database happens to hold, and rows
        belonging to other versions disappear with no error.
        """
        qualified = _QUALIFIED_COLUMN.match(suite_column or "")
        if not qualified:
            raise ValueError(f"not a table-qualified column reference: {suite_column!r}")
        if qualified.group(1).lower() == cls.__tablename__:
            raise ValueError(
                f"{suite_column!r} is shadowed by the subqueries' own {cls.__tablename__}"
            )

        expression = cls.resolved_for(literal_column(suite_column))
        compiled = expression.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        return " ".join(str(compiled).split())
