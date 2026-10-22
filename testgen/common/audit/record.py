from dataclasses import dataclass, field
from typing import Any, Protocol, Self
from uuid import UUID

from testgen.common.audit.actions import AuditAction, Outcome
from testgen.common.enums import JobSource

SCHEMA_VERSION = 1
TARGETS_CAP = 100


class _UserLike(Protocol):
    id: UUID
    username: str
    name: str | None


@dataclass(frozen=True)
class Actor:
    """The person an action is attributed to.

    ``id`` is the permanent identity; the names are carried for readability and may change over time.
    """

    id: UUID | None
    username: str | None
    display_name: str | None = None

    @classmethod
    def of(cls, user: _UserLike) -> Self:
        return cls(id=user.id, username=user.username, display_name=user.name)

    @classmethod
    def attempted(cls, username: str | None) -> Self:
        """An unverified identity: the username given to a sign-in that failed."""
        return cls(id=None, username=username)


@dataclass(frozen=True)
class AuditRecord:
    """One audit event, in the field set of ``SCHEMA_VERSION``.

    Fields may be added in later versions; existing names and meanings do not change.
    """

    id: UUID
    occurred_at: str
    action: AuditAction
    outcome: Outcome
    source: JobSource
    actor: Actor | None = None
    project_code: str | None = None
    target_type: str | None = None
    target_count: int = 0
    targets: tuple[str, ...] = ()
    target_name: str | None = None
    cause_type: str | None = None
    cause_id: str | None = None
    changes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The record as written: flat, with every field present."""
        actor = self.actor or Actor(id=None, username=None)
        return {
            "schema_version": SCHEMA_VERSION,
            "id": str(self.id),
            "occurred_at": self.occurred_at,
            "action": str(self.action),
            "outcome": str(self.outcome),
            "actor_id": str(actor.id) if actor.id else None,
            "actor_username": actor.username,
            "actor_display_name": actor.display_name,
            "source": str(self.source),
            "project_code": self.project_code,
            "target_type": self.target_type,
            "target_count": self.target_count,
            "targets": list(self.targets[:TARGETS_CAP]),
            "target_name": self.target_name if self.target_count == 1 else None,
            "cause_type": self.cause_type,
            "cause_id": self.cause_id,
            "changes": {name: dict(entry) for name, entry in self.changes.items()},
        }

