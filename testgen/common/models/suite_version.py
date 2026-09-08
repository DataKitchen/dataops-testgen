from datetime import datetime
from typing import Any, Self
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, Integer, String, text
from sqlalchemy.dialects import postgresql

from testgen.common.models.custom_types import NullIfEmptyString
from testgen.common.models.entity import Entity


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
