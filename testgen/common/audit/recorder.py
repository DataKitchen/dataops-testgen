"""Record audit events, written when the database work they describe commits.

A record made while a database session is current is held on that session and written by its next commit; a
rollback, or closing the session without committing, discards it. A record whose outcome is not ``succeeded``
describes work that did not happen, so it is written at once.
"""

import logging
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.orm import SessionTransaction

from testgen.common.audit.actions import CHANGE_ACTIONS, AuditAction, AuditTargetType, Outcome
from testgen.common.audit.fields import AuditFields, FieldChange, pending_changes, to_record
from testgen.common.audit.record import Actor, AuditRecord
from testgen.common.audit.sinks import get_sink
from testgen.common.enums import JobSource
from testgen.common.models import Session, get_current_session

LOG = logging.getLogger("testgen")

_CONTEXT_KEY = "audit_context"
_PENDING_KEY = "audit_pending"
_WRITTEN_KEY = "audit_written_changes"


@dataclass(frozen=True)
class AuditContext:
    """Who is acting, and through which entry point."""

    source: JobSource
    actor: Actor | None = None
    cause_type: str | None = None
    cause_id: str | None = None


_SYSTEM_CONTEXT = AuditContext(source=JobSource.system)
_context_resolver: Callable[[], AuditContext | None] | None = None


def bind(context: AuditContext, session: SQLAlchemySession | None = None) -> None:
    """Attribute the records made on ``session`` (default: the current session) to ``context``."""
    if (session := session or get_current_session()) is None:
        LOG.error("Audit context for %s not bound: no database session", context.source)
        return
    session.info[_CONTEXT_KEY] = context


def set_context_resolver(resolver: Callable[[], AuditContext | None]) -> None:
    """Set the process-wide fallback for a record made on a session that has no context bound."""
    global _context_resolver
    _context_resolver = resolver


def record(
    action: AuditAction,
    subject: object | None = None,
    *,
    outcome: Outcome = Outcome.SUCCEEDED,
    actor: Actor | None = None,
    project_code: str | None = None,
    target_type: AuditTargetType | None = None,
    targets: Iterable[object] = (),
    target_count: int | None = None,
    target_name: str | None = None,
    cause_type: AuditTargetType | None = None,
    cause_id: object | None = None,
    changes: dict[str, dict[str, Any]] | None = None,
    only: Collection[str] | None = None,
    exclude: Collection[str] = (),
) -> None:
    """Record ``action``.

    An action in ``CHANGE_ACTIONS`` is recorded only when at least one field changed.

    :param subject: the affected object, whose model declares ``__audit__``. It supplies the target, the project and
        the changed fields, whether or not it was saved yet; the other arguments override what it supplies.
    :param outcome: ``succeeded`` records are written when the current session commits; others at once.
    :param actor: overrides the acting user of the context, e.g. the attempted identity of a failed sign-in.
    :param targets: ids of the affected objects; only the first ``TARGETS_CAP`` are written.
    :param target_count: how many objects were affected; defaults to the number of ``targets``.
    :param target_name: name of the affected object, written only when ``target_count`` is 1.
    :param cause_type: overrides the cause of the context, e.g. the deletion an action is a side effect of.
    :param cause_id: id of that cause.
    :param changes: changed fields, as ``{field: {"from": ..., "to": ...}}``, for an action with no subject.
        An entry whose two values are equal is dropped.
    :param only: limits the subject's changed fields to these.
    :param exclude: leaves these out of the subject's changed fields.
    """
    try:
        session = get_current_session()
        if subject is not None:
            declaration: AuditFields = type(subject).__audit__
            target_type = target_type or declaration.target_type
            targets = targets or (getattr(subject, declaration.id),)
            if target_name is None and declaration.name:
                target_name = getattr(subject, declaration.name)
            if project_code is None and declaration.project:
                project_code = getattr(subject, declaration.project)
            if changes is None:
                names = tuple(
                    name for name in declaration.declared()
                    if (only is None or name in only) and name not in exclude
                )
                changes = _subject_changes(session, subject, declaration, names)
        changes = {
            name: entry for name, entry in (changes or {}).items()
            if not ("from" in entry and entry["from"] == entry.get("to"))
        }
        if action in CHANGE_ACTIONS and not changes:
            return

        context = _context_of(session)
        target_ids = tuple(str(target) for target in targets)
        entry = AuditRecord(
            id=uuid4(),
            occurred_at=datetime.now(UTC).isoformat(),
            action=action,
            outcome=outcome,
            source=context.source,
            actor=actor or context.actor,
            project_code=project_code,
            target_type=target_type,
            target_count=len(target_ids) if target_count is None else target_count,
            targets=target_ids,
            target_name=target_name,
            cause_type=cause_type or context.cause_type,
            cause_id=(None if cause_id is None else str(cause_id)) if cause_type else context.cause_id,
            changes=changes,
        )
        if session is None or outcome != Outcome.SUCCEEDED:
            get_sink().write([entry])
        else:
            session.info.setdefault(_PENDING_KEY, []).append(entry)
    except Exception:
        LOG.exception("Audit record failed: %s", action)


def _subject_changes(
    session: SQLAlchemySession | None,
    subject: object,
    declaration: AuditFields,
    names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """The changes to ``names``: those already flushed in this transaction, then those ``subject`` still holds.

    The flushed changes it reports are consumed, so that a later record of the same subject does not repeat them.
    """
    written: dict[str, FieldChange] = {}
    if session is not None and (stashed := session.info.get(_WRITTEN_KEY, {}).get(id(subject))):
        _, stashed_changes = stashed
        written = {name: stashed_changes.pop(name) for name in names if name in stashed_changes}
    for name, change in pending_changes(subject, names).items():
        written[name] = written[name].then(change) if name in written else change
    return to_record(subject, declaration, written)


def _context_of(session: SQLAlchemySession | None) -> AuditContext:
    if session is not None and (context := session.info.get(_CONTEXT_KEY)):
        return context
    if _context_resolver is not None and (context := _context_resolver()):
        return context
    return _SYSTEM_CONTEXT


@event.listens_for(Session, "before_flush")
def _stash_changes(session: SQLAlchemySession, _flush_context: object, _instances: object) -> None:
    # A flush clears an object's attribute history, so its declared changes are kept until it is recorded.
    try:
        stash = session.info.setdefault(_WRITTEN_KEY, {})
        for obj in [*session.new, *session.dirty]:
            if (declaration := getattr(type(obj), "__audit__", None)) is None:
                continue
            if not (changes := pending_changes(obj, declaration.declared())):
                continue
            _, stashed = stash.setdefault(id(obj), (obj, {}))
            for name, change in changes.items():
                stashed[name] = stashed[name].then(change) if name in stashed else change
    except Exception:
        LOG.exception("Audit changes could not be kept for the flush")


@event.listens_for(Session, "after_commit")
def _write_pending(session: SQLAlchemySession) -> None:
    session.info.pop(_WRITTEN_KEY, None)
    if pending := session.info.pop(_PENDING_KEY, None):
        try:
            get_sink().write(pending)
        except Exception:
            LOG.exception("Audit records could not be written: %s", [entry.action for entry in pending])


@event.listens_for(Session, "after_transaction_end")
def _discard_pending(session: SQLAlchemySession, transaction: SessionTransaction) -> None:
    # Reached after a commit too, by which point the pending records were written.
    if transaction.parent is None:
        session.info.pop(_PENDING_KEY, None)
        session.info.pop(_WRITTEN_KEY, None)
