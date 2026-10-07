import copy
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

from testgen.common.models import get_current_session
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
    def _draft_branch(cls, suite_id):
        return (
            select(cls.id)
            .where(cls.test_suite_id == suite_id, cls.frozen_at.is_(None))
            .scalar_subquery()
        )

    @classmethod
    def _frozen_branch(cls, suite_id):
        return (
            select(cls.id)
            .where(cls.test_suite_id == suite_id, cls.frozen_at.is_not(None))
            .order_by(cls.version.desc())
            .limit(1)
            .scalar_subquery()
        )

    @classmethod
    def _placeholder_branch(cls):
        return select(cls.id).where(cls.test_suite_id.is_(None)).scalar_subquery()

    @classmethod
    def resolved_for(cls, suite_id) -> ColumnElement[UUID]:
        """The version a read or write of the given suite's terms scopes to.

        The suite's draft where one exists, otherwise its highest frozen version, otherwise the
        placeholder. Accepts a literal id or a column expression and returns a correlated scalar
        subquery, so a caller that does not know the suite until the query runs can still scope
        by it.
        """
        return func.coalesce(
            cls._draft_branch(suite_id), cls._frozen_branch(suite_id), cls._placeholder_branch()
        )

    @classmethod
    def active_for(cls, suite_id) -> ColumnElement[UUID]:
        """The agreement in force for the given suite: its highest frozen version.

        A suite with no frozen version resolves to the placeholder, which is what a suite that
        keeps no versions is stamped with.
        """
        return func.coalesce(cls._frozen_branch(suite_id), cls._placeholder_branch())

    @classmethod
    def for_run(cls, suite_id) -> ColumnElement[UUID]:
        """The version a run of the given suite is stamped with.

        The agreement in force where there is one, otherwise the draft the run previews,
        otherwise the placeholder. A suite with no frozen version has nothing in force, and
        stamping the placeholder there would execute none of the draft's terms while still
        reading as a run of the agreement.
        """
        return func.coalesce(
            cls._frozen_branch(suite_id), cls._draft_branch(suite_id), cls._placeholder_branch()
        )

    @classmethod
    def _compile_for_sql(cls, expression, suite_column: str) -> str:
        qualified = _QUALIFIED_COLUMN.match(suite_column or "")
        if not qualified:
            raise ValueError(f"not a table-qualified column reference: {suite_column!r}")
        if qualified.group(1).lower() == cls.__tablename__:
            raise ValueError(
                f"{suite_column!r} is shadowed by the subqueries' own {cls.__tablename__}"
            )

        compiled = expression.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        return " ".join(str(compiled).split())

    @classmethod
    def resolved_for_sql(cls, suite_column: str) -> str:
        """``resolved_for`` as SQL text, for hand-written queries that cannot hold an expression.

        The result is a scalar expression, not a join: correlated subqueries over
        ``suite_versions`` wrapped in ``coalesce``, each comparing that table's own
        ``test_suite_id`` to ``suite_column``. It goes on the right of ``version_id = ...``, and
        ``suite_column`` is a free reference resolved in the surrounding query's scope.

        The qualifier is required, and may not be ``suite_versions``. Either way the name would
        bind to the subqueries' own table instead of the outer row, making the comparison a
        tautology: every suite resolves to whichever draft the database happens to hold, and rows
        belonging to other versions disappear with no error.
        """
        return cls._compile_for_sql(cls.resolved_for(literal_column(suite_column)), suite_column)

    @classmethod
    def is_draft(cls, version_id: UUID | str | None) -> bool:
        """Whether the id names a suite's open draft.

        False for the placeholder, for a version that no longer exists, and for no id at all.
        """
        if version_id is None:
            return False
        return get_current_session().scalar(
            select(cls.id).where(
                cls.id == version_id,
                cls.test_suite_id.is_not(None),
                cls.frozen_at.is_(None),
            )
        ) is not None

    @classmethod
    def is_frozen_agreement(cls, version_id: UUID | str | None) -> bool:
        """Whether the id names a frozen version a suite owns.

        False for the placeholder, which is stored frozen but belongs to no suite, so a suite
        that keeps no versions never reads as holding a frozen agreement.
        """
        if version_id is None:
            return False
        return get_current_session().scalar(
            select(cls.id).where(
                cls.id == version_id,
                cls.test_suite_id.is_not(None),
                cls.frozen_at.is_not(None),
            )
        ) is not None

    @classmethod
    def is_suite_owned(cls, version_id: UUID | str | None) -> bool:
        """Whether the id names a version a suite owns rather than the shared placeholder."""
        if version_id is None:
            return False
        return get_current_session().scalar(
            select(cls.id).where(cls.id == version_id, cls.test_suite_id.is_not(None))
        ) is not None

    @classmethod
    def is_active(cls, version_id: UUID | str | None, suite_id: UUID | str) -> bool:
        """Whether the id names the suite's agreement in force."""
        if version_id is None:
            return False
        # Compared in Python against an id the database hands back, unlike the predicates
        # above, which hand theirs to it.
        return UUID(str(version_id)) == get_current_session().scalar(select(cls.active_for(suite_id)))

    @classmethod
    def in_force_for(cls, suite_id) -> Self | None:
        """The suite's highest frozen version, or None when it has none.

        The placeholder is not a version in force: it is what a suite that keeps no versions
        resolves to, and it belongs to no suite.
        """
        active_id = get_current_session().scalar(select(cls.active_for(suite_id)))
        version = cls.get(active_id) if active_id else None
        return version if version and version.test_suite_id else None

    @staticmethod
    def document_version(version: int) -> str:
        """A version number as the semantic version string ODCS wants in ``version``."""
        return f"{version}.0.0"

    @classmethod
    def open_draft(cls, suite_id) -> tuple[Self, Self | None]:
        """Open a draft on the suite, carrying the version in force forward.

        Returns the new draft and the version its document was copied from, which is None
        when the suite had no frozen version to carry forward.
        """
        source = cls.in_force_for(suite_id)
        version = cls.next_version_for(suite_id)
        document = copy.deepcopy(source.metadata_document) if source else None
        if document and "version" in document:
            document["version"] = cls.document_version(version)
        draft = cls(
            id=uuid4(),
            test_suite_id=suite_id,
            version=version,
            metadata_document=document,
            odcs_api_version=source.odcs_api_version if source else None,
        )
        session = get_current_session()
        session.add(draft)
        session.flush()
        return draft, source

    @classmethod
    def draft_for(cls, suite_id) -> Self | None:
        """The suite's open draft, if it has one."""
        return get_current_session().scalars(
            select(cls).where(cls.test_suite_id == suite_id, cls.frozen_at.is_(None))
        ).first()

    @classmethod
    def for_number(cls, suite_id, version: int) -> Self | None:
        """The suite's version carrying that number, if it has one."""
        return get_current_session().scalars(
            select(cls).where(cls.test_suite_id == suite_id, cls.version == version)
        ).first()

    @classmethod
    def next_version_for(cls, suite_id) -> int:
        """One past the suite's highest version number, or 1 when it has none."""
        highest = get_current_session().scalar(
            select(func.max(cls.version)).where(cls.test_suite_id == suite_id)
        )
        return (highest or 0) + 1


class FrozenVersionError(Exception):
    """Raised when a write targets a frozen version of a contract."""

    def __init__(self, version_id) -> None:
        super().__init__(f"Version {version_id} is frozen and cannot be written.")
        self.version_id = version_id
