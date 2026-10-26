"""What differs between two versions of a contract: its quality rules, and its metadata document."""

import copy
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.types import TypeDecorator

from testgen.common import contract_service
from testgen.common.enums import MANAGED_TEST_TYPES
from testgen.common.models import get_current_session
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.common.source_value_fields import hidden_slots, value_digest

# Columns a term's diff compares: what the term checks and how, never bookkeeping.
TERM_DIFF_FIELDS = (
    "test_type", "schema_name", "table_name", "column_name", "test_description", "test_active", "severity",
    "skip_errors", "baseline_ct", "baseline_unique_ct", "baseline_value", "baseline_value_ct", "threshold_value",
    "baseline_sum", "baseline_avg", "baseline_sd", "lower_tolerance", "upper_tolerance", "subset_condition",
    "groupby_names", "having_condition", "window_date_column", "window_days", "match_schema_name",
    "match_table_name", "match_column_names", "match_subset_condition", "match_groupby_names",
    "match_having_condition", "history_calculation", "history_calculation_upper", "history_lookback",
    "custom_query", "lock_refresh", "impact_dimension", "external_url", "custom_metadata",
)


class TermChangeKind(StrEnum):
    ADDED = "Added"
    REMOVED = "Removed"
    EDITED = "Edited"
    REGENERATED = "Regenerated"
    REGENERATED_AND_EDITED = "Regenerated and edited"
    CHANGED = "Changed"


@dataclass(frozen=True)
class TermChange:
    kind: TermChangeKind
    before: TestDefinition | None
    after: TestDefinition | None
    fields: list[str]

    @property
    def term(self) -> TestDefinition:
        return self.after or self.before


def term_changes(source_id: UUID, target_id: UUID) -> list[TermChange]:
    """Every test that differs between two versions, matched by rule ID, in table, column and test type order."""
    before = _terms_by_identity(source_id)
    after = _terms_by_identity(target_id)
    changes = []
    for key in before.keys() | after.keys():
        old, new = before.get(key), after.get(key)
        if old is None:
            changes.append(TermChange(TermChangeKind.ADDED, None, new, []))
        elif new is None:
            changes.append(TermChange(TermChangeKind.REMOVED, old, None, []))
        elif fields := [field for field in TERM_DIFF_FIELDS if _stored_value(old, field) != _stored_value(new, field)]:
            regenerated = new.last_auto_gen_date != old.last_auto_gen_date
            edited = new.last_manual_update != old.last_manual_update
            kind = (
                TermChangeKind.REGENERATED_AND_EDITED if regenerated and edited
                else TermChangeKind.REGENERATED if regenerated
                else TermChangeKind.EDITED if edited
                else TermChangeKind.CHANGED
            )
            changes.append(TermChange(kind, old, new, fields))
    return sorted(
        changes,
        key=lambda change: (
            change.term.table_name or "", change.term.column_name or "", change.term.test_type,
            change.term.contract_term_id or "",
        ),
    )


def _stored_value(term: TestDefinition, field: str) -> Any:
    """``term``'s ``field`` as its column stores it, so values the column stores alike compare equal.

    An empty integer is stored as 0 when a test is written through the model, and as NULL when
    generation writes it, so a copied test would otherwise differ from the one it was copied from.
    """
    value = getattr(term, field)
    column_type = TestDefinition.__table__.c[field].type
    return column_type.process_bind_param(value, None) if isinstance(column_type, TypeDecorator) else value


def _terms_by_identity(version_id: UUID) -> dict[str, TestDefinition]:
    rows = get_current_session().scalars(
        select(TestDefinition).where(
            TestDefinition.version_id == version_id,
            TestDefinition.test_type.not_in(MANAGED_TEST_TYPES),
        )
    ).all()
    # A row without a rule ID is keyed by its own id, which no other version shares.
    return {row.contract_term_id or str(row.id): row for row in rows}


class DocumentChangeKind(StrEnum):
    ADDED = "Added"
    REMOVED = "Removed"
    CHANGED = "Changed"


@dataclass(frozen=True)
class ItemName:
    """A step into the item of a list of named objects (tables, columns) that carries this name."""

    name: str


@dataclass(frozen=True)
class HiddenValue:
    """A value that can carry source data, in place of the value. Equal values have equal digests."""

    digest: str


_UNCOMPARED_FIELDS = frozenset({*contract_service.OWNED_FIELDS, "status"})

# Fields that name an item of a list in a metadata document, in the order they are tried.
_ITEM_KEYS = ("name", "username", "property", "role", "channel", "server", "id")


@dataclass(frozen=True)
class DocumentChange:
    steps: tuple[str | ItemName, ...]
    kind: DocumentChangeKind
    before: Any
    after: Any

    @property
    def path(self) -> str:
        return "$" + "".join(f"[{step.name}]" if isinstance(step, ItemName) else f".{step}" for step in self.steps)


def document_changes(
    before: dict[str, Any] | None, after: dict[str, Any] | None, hide_source_data: bool
) -> list[DocumentChange]:
    """Each place at which ``after`` differs from ``before``: added, removed or changed, with the value on each side.

    Objects are compared key by key, and lists of objects item by item on the first of ``_ITEM_KEYS`` that
    identifies every item on both sides (tables and columns by name, team members by username, service levels
    by property); any other list that differs is reported changed as a whole. With ``hide_source_data``, each
    value that can carry source data is compared, and reported, as a ``HiddenValue``.
    """
    before, after = before or {}, after or {}
    if hide_source_data:
        key = secrets.token_bytes(32)
        before, after = _with_hidden_values(before, key), _with_hidden_values(after, key)
    return _changes(before, after, ())


def version_document_changes(
    source: SuiteVersion, target: SuiteVersion, suite: TestSuite, hide_source_data: bool
) -> list[DocumentChange]:
    """What differs between two versions' metadata documents, as ``document_changes`` reports it. The fields
    TestGen owns, and the contract's ``status``, which follows each version's state, are not compared."""
    before, after = (
        {
            key: value
            for key, value in contract_service.document_with_contract_name(version, suite).items()
            if key not in _UNCOMPARED_FIELDS
        }
        for version in (source, target)
    )
    return document_changes(before, after, hide_source_data)


def _with_hidden_values(node: Any, key: bytes) -> Any:
    masked = copy.deepcopy(node)
    for slot in list(hidden_slots(masked)):
        slot.container[slot.key] = HiddenValue(value_digest(key, "", slot.container[slot.key]))
    return masked


def _changes(before: Any, after: Any, steps: tuple[str | ItemName, ...]) -> list[DocumentChange]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return _keyed_changes(before, after, lambda key: (*steps, key))
    if item_key := _item_key(before, after):
        return _keyed_changes(
            {item[item_key]: item for item in before},
            {item[item_key]: item for item in after},
            lambda name: (*steps, ItemName(name)),
        )
    return [DocumentChange(steps, DocumentChangeKind.CHANGED, before, after)]


def _keyed_changes(
    before: dict, after: dict, child_steps: Callable[[str], tuple[str | ItemName, ...]]
) -> list[DocumentChange]:
    changes = []
    for key in [*before, *(key for key in after if key not in before)]:
        if key not in after:
            changes.append(DocumentChange(child_steps(key), DocumentChangeKind.REMOVED, before[key], None))
        elif key not in before:
            changes.append(DocumentChange(child_steps(key), DocumentChangeKind.ADDED, None, after[key]))
        else:
            changes += _changes(before[key], after[key], child_steps(key))
    return changes


def _item_key(before: Any, after: Any) -> str | None:
    if not isinstance(before, list) or not isinstance(after, list):
        return None
    return next((key for key in _ITEM_KEYS if _identifies(key, before) and _identifies(key, after)), None)


def _identifies(key: str, items: list) -> bool:
    return (
        all(isinstance(item, dict) and isinstance(item.get(key), str) and item[key] for item in items)
        and len({item[key] for item in items}) == len(items)
    )
