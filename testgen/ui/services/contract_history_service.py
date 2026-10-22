"""What the Version History dialog lists for a contract, and the documents it compares."""

from datetime import datetime
from typing import Any

from testgen.common import contract_service
from testgen.common.enums import JOB_STATUS_LABEL
from testgen.common.models.suite_version import SuiteVersion, format_version, version_state
from testgen.common.models.test_suite import TestSuite

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
        options.append({"value": item.version, "label": format_version(item.version, state)})
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
        label = format_version(version.version, version_state(version.frozen_at, is_active))
        result[f"{side}_label"] = label
        try:
            documents[side] = contract_service.export_version(version, contract_name=suite.test_suite).text
        except ValueError as e:
            result["error"] = f"{label} could not be rendered. {e}"
    result["source_document"] = None if result["error"] else documents["source"]
    result["target_document"] = None if result["error"] else documents["target"]
    return result
