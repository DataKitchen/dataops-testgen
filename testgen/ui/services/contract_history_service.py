"""What the Version History dialog lists for a contract, and the documents it compares."""

import json
import re
from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from testgen.common import contract_comparison, contract_service
from testgen.common.contract_comparison import (
    DocumentChange,
    DocumentChangeKind,
    ItemName,
    PiiRedactedValue,
    TermChange,
    TermChangeKind,
)
from testgen.common.enums import JOB_STATUS_LABEL
from testgen.common.models import get_current_session
from testgen.common.models.suite_version import SuiteVersion, format_version, version_state
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_suite import TestSuite
from testgen.common.pii_masking import PII_REDACTED
from testgen.ui.services.contract_import_service import IMPORT_PREVIEW_ROW_LIMIT

_VERSION_LIMIT = 1000


def _epoch_ms(moment: datetime | None) -> int | None:
    return int(moment.timestamp() * 1000) if moment else None


def version_history(suite: TestSuite) -> dict[str, Any]:
    """The Version History dialog's props: every version of the contract, newest first, each with its detail
    and the pair of versions its Compare opens on.

    The newest version compares the active version against the draft, or the two newest versions when there is
    no draft. Any other version compares itself against the newest version.
    """
    items, _ = SuiteVersion.list_for_suite(suite.id, page=1, limit=_VERSION_LIMIT)
    active_number = next((item.version for item in items if item.frozen_at is not None), None)

    draft = next((item for item in items if item.frozen_at is None), None)
    if len(items) < 2:
        newest_comparison = None
    elif draft and active_number is not None:
        newest_comparison = {"source": active_number, "target": draft.version}
    else:
        newest_comparison = {"source": items[1].version, "target": items[0].version}

    versions = []
    options = []
    for item in items:
        state = version_state(item.frozen_at, item.version == active_number)
        state_text = state.value.capitalize()
        options.append({"value": item.version, "label": format_version(item.version, state, item.label)})
        versions.append({
            "version": item.version,
            "state": state.value,
            "caption": f"{state_text} · {item.label}" if item.label else state_text,
            "detail": {
                "title": f"Version {item.version}",
                "state": state_text,
                "terms": contract_service.term_count(item.id),
                "runs": {
                    "count": item.run_count,
                    "latest_run_id": str(item.latest_run_id) if item.latest_run_id else None,
                    "latest_started_at": _epoch_ms(item.latest_run_started_at),
                    "latest_status": JOB_STATUS_LABEL.get(item.latest_run_status, item.latest_run_status)
                    if item.latest_run_status else None,
                },
                "label": item.label,
                "frozen_by": item.frozen_by,
                "frozen_at": _epoch_ms(item.frozen_at),
                "frozen": item.frozen_at is not None,
                "comparison": newest_comparison if item is items[0] else {
                    "source": item.version, "target": items[0].version,
                },
            },
        })

    return {
        "contract": suite.test_suite,
        "versions": versions,
        "options": options,
        "compare_disabled_reason": None if len(items) > 1 else "There is only one version.",
    }


def version_comparison(suite: TestSuite, source: int, target: int) -> dict[str, Any]:
    """The documents of two versions of the contract, as Export Contract produces them.

    :param source: the version number shown on the left
    :param target: the version number shown on the right
    :return: both documents named by version, or the reason one could not be produced
    """
    active = SuiteVersion.in_force_for(suite.id)
    result: dict[str, Any] = {"source": source, "target": target, "error": None}
    documents = {}
    for side, number in (("source", source), ("target", target)):
        try:
            version = contract_service.version_for_export(suite, number)
        except ValueError as e:
            result[f"{side}_label"] = f"v{number}"
            result["error"] = str(e)
            continue
        is_active = active is not None and version.version == active.version
        label = format_version(version.version, version_state(version.frozen_at, is_active), version.label)
        result[f"{side}_label"] = label
        try:
            documents[side] = contract_service.export_version(version, contract_name=suite.test_suite).text
        except ValueError as e:
            result["error"] = f"{label} could not be rendered. {e}"
    result["source_document"] = None if result["error"] else documents["source"]
    result["target_document"] = None if result["error"] else documents["target"]
    return result



def version_changes(suite: TestSuite, source: int, target: int, mask_pii: bool) -> dict[str, Any]:
    """What differs between two versions of the contract, quality rule by rule and in its metadata.

    :param source: the version number compared from
    :param target: the version number compared to
    :param mask_pii: whether values of PII columns that can carry source data are redacted
    :return: the rows of both halves, or the reason a version could not be found
    """
    result: dict[str, Any] = {"source": source, "target": target, "error": None, "rules": None, "metadata": None}
    try:
        source_version = contract_service.version_for_export(suite, source)
        target_version = contract_service.version_for_export(suite, target)
    except ValueError as e:
        result["error"] = str(e)
        return result
    pii_columns = (
        contract_comparison.pii_columns(suite, source_version, target_version) if mask_pii else frozenset()
    )
    result["rules"] = rule_changes(source_version.id, target_version.id, pii_columns=pii_columns)
    result["metadata"] = metadata_changes(source_version, target_version, suite, pii_columns=pii_columns)
    return result

_RULE_CHANGE_ORDER = {
    TermChangeKind.REMOVED: 0,
    TermChangeKind.EDITED: 1,
    TermChangeKind.REGENERATED: 1,
    TermChangeKind.REGENERATED_AND_EDITED: 1,
    TermChangeKind.CHANGED: 1,
    TermChangeKind.ADDED: 2,
}

_FIELD_LABELS = {
    "test_type": "Test Type",
    "schema_name": "Schema",
    "table_name": "Table",
    "column_name": "Column",
    "test_description": "Description",
    "test_active": "Active",
    "severity": "Severity",
    "lock_refresh": "Lock Refresh",
}

_NO_VALUE = "—"


def rule_changes(source_id: UUID, target_id: UUID, pii_columns: Collection[tuple[str, str]]) -> dict[str, Any]:
    """The quality rules that differ between two versions, as rows for the Changes view.

    :param source_id: the id of the version compared from
    :param target_id: the id of the version compared to
    :param pii_columns: the ``(table, column)`` pairs whose values that can carry source data are redacted
    :return: a summary of the counts, the rows (removals, then changes, then additions), and the empty state
    """
    changes = sorted(
        contract_comparison.term_changes(source_id, target_id), key=lambda change: _RULE_CHANGE_ORDER[change.kind]
    )
    test_types = _test_types({
        term.test_type for change in changes for term in (change.before, change.after) if term is not None
    })
    added = sum(1 for change in changes if change.kind is TermChangeKind.ADDED)
    removed = sum(1 for change in changes if change.kind is TermChangeKind.REMOVED)
    counts = [(added, "added"), (removed, "removed"), (len(changes) - added - removed, "changed")]
    return {
        "summary": " · ".join(f"{count} {noun}" for count, noun in counts if count) or None,
        "rows": [_rule_row(change, test_types, pii_columns) for change in changes[:IMPORT_PREVIEW_ROW_LIMIT]],
        "total_rows": len(changes),
        "truncated": len(changes) > IMPORT_PREVIEW_ROW_LIMIT,
        "empty_state": None if changes else "No quality rules changed.",
    }


def _test_types(codes: set[str]) -> dict[str, TestType]:
    if not codes:
        return {}
    rows = get_current_session().scalars(select(TestType).where(TestType.test_type.in_(codes)))
    return {row.test_type: row for row in rows}


def _rule_row(
    change: TermChange, test_types: dict[str, TestType], pii_columns: Collection[tuple[str, str]]
) -> dict[str, Any]:
    term = change.term
    test_type = test_types.get(term.test_type)
    prompts = {column: prompt for column, prompt, _ in test_type.param_fields} if test_type else {}

    def label(field: str) -> str:
        return prompts.get(field) or _FIELD_LABELS.get(field) or field.replace("_", " ").capitalize()

    redacted = contract_comparison.pii_redacted_fields(change, pii_columns)

    def value(field: str, side: Any) -> str:
        raw = getattr(side, field)
        if field in redacted:
            return PII_REDACTED
        if field == "test_type":
            return _short_name(raw, test_types)
        if raw is None or raw == "":
            return _NO_VALUE
        if isinstance(raw, bool):
            return "Yes" if raw else "No"
        return str(raw)

    return {
        "change": change.kind.value,
        "table": term.table_name,
        "column": term.column_name or "",
        "test_type": _short_name(term.test_type, test_types),
        "fields": [
            {"label": label(field), "before": value(field, change.before), "after": value(field, change.after)}
            for field in change.fields
        ],
    }


def _short_name(code: str, test_types: dict[str, TestType]) -> str:
    test_type = test_types.get(code)
    return (test_type.test_name_short if test_type else None) or code


_SECTIONS = {
    "name": "Overview",
    "domain": "Overview",
    "tenant": "Overview",
    "tags": "Overview",
    "description": "Overview",
    "schema": "Schema",
    "team": "Team",
    "roles": "Roles",
    "support": "Support",
    "slaProperties": "Service Levels",
    "servers": "Servers",
}
_SECTION_ORDER = [*dict.fromkeys(_SECTIONS.values()), "Other"]

# Keys that only hold the items of a list, which the item names already say.
_CONTAINER_KEYS = frozenset({"properties", "members"})


def metadata_changes(
    source: SuiteVersion, target: SuiteVersion, suite: TestSuite, pii_columns: Collection[tuple[str, str]]
) -> dict[str, Any]:
    """What differs between two versions' metadata documents, as rows for the Changes view.

    :param source: the version compared from
    :param target: the version compared to
    :param suite: the contract both versions belong to
    :param pii_columns: the ``(table, column)`` pairs whose values that can carry source data are redacted
    :return: a summary of the count, one row per change with its section, field and both values, ordered by
        section, and the empty state
    """
    changes = contract_comparison.version_document_changes(
        source, target, suite, hide_source_data=False, pii_columns=pii_columns
    )
    rows = sorted((_metadata_row(change) for change in changes), key=lambda row: _SECTION_ORDER.index(row["section"]))
    return {
        "summary": f"{len(changes)} changed" if changes else None,
        "rows": rows,
        "empty_state": None if changes else "No metadata changed.",
    }


def _metadata_row(change: DocumentChange) -> dict[str, Any]:
    top, *rest = change.steps
    section = _SECTIONS.get(top, "Other")
    steps = rest if top in _SECTIONS and section != "Overview" else change.steps
    names = ".".join(step.name for step in steps if isinstance(step, ItemName))
    keys = " · ".join(
        _humanize(step) for step in steps if not isinstance(step, ItemName) and step not in _CONTAINER_KEYS
    )
    return {
        "section": section,
        "field": " · ".join(part for part in (names, keys) if part) or section,
        "before": _metadata_value(change.before, change.kind),
        "after": _metadata_value(change.after, change.kind),
    }


def _humanize(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", key).lower().capitalize()


def _metadata_value(value: Any, kind: DocumentChangeKind) -> str:
    if value is None:
        return _NO_VALUE
    if isinstance(value, dict | list) and kind is not DocumentChangeKind.CHANGED:
        return kind.value
    if _holds_redacted(value):
        return PII_REDACTED
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)
    return str(value)


def _holds_redacted(value: Any) -> bool:
    if isinstance(value, PiiRedactedValue):
        return True
    if isinstance(value, dict):
        return any(_holds_redacted(item) for item in value.values())
    if isinstance(value, list):
        return any(_holds_redacted(item) for item in value)
    return False
