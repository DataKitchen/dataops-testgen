from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.contract_service import ExportedDocument
from testgen.common.enums import JobStatus
from testgen.common.models.suite_version import SuiteVersion, SuiteVersionListItem
from testgen.common.models.test_suite import TestSuite
from testgen.ui.services import contract_history_service as service

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
LATEST_RUN = datetime(2026, 10, 11, 16, 20, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _item(version: int, frozen: bool, **overrides) -> SuiteVersionListItem:
    fields = {
        "id": uuid4(), "version": version, "label": None, "created_by": None,
        "frozen_at": FROZEN if frozen else None, "frozen_by": "alice" if frozen else None,
        "term_count": 150, "run_count": 0, "latest_run_id": None, "latest_run_status": None,
        "latest_run_started_at": None,
    }
    fields.update(overrides)
    return SuiteVersionListItem(**fields)


def _suite() -> TestSuite:
    return TestSuite(id=uuid4(), test_suite="orders_contract")


def _history(items, term_counts=None):
    counts = term_counts or {}
    with (
        patch.object(service.SuiteVersion, "list_for_suite", return_value=(items, len(items))),
        patch.object(service.contract_service, "term_count", side_effect=lambda version_id: counts.get(version_id, 147)),
    ):
        return service.version_history(_suite())


def test_the_history_lists_every_version_newest_first_with_its_state():
    history = _history([_item(4, False), _item(3, True, label="Q3 agreement"), _item(2, True), _item(1, True)])

    assert history["contract"] == "orders_contract"
    assert [(v["version"], v["state"], v["caption"]) for v in history["versions"]] == [
        (4, "draft", "Draft"),
        (3, "active", "Active · Q3 agreement"),
        (2, "superseded", "Superseded"),
        (1, "superseded", "Superseded"),
    ]
    assert history["options"] == [
        {"value": 4, "label": "v4 draft"},
        {"value": 3, "label": "v3 active"},
        {"value": 2, "label": "v2 superseded"},
        {"value": 1, "label": "v1 superseded"},
    ]


def test_a_draft_shows_its_state_terms_and_runs():
    run_id = uuid4()
    draft = _item(4, False, run_count=2, latest_run_id=run_id, latest_run_status=JobStatus.ERROR, latest_run_started_at=LATEST_RUN)
    history = _history([draft, _item(3, True)], term_counts={draft.id: 147})

    assert history["versions"][0]["detail"] == {
        "title": "Version 4",
        "state": "Draft",
        "terms": 147,
        "runs": {"count": 2, "latest_run_id": str(run_id), "latest_started_at": _ms(LATEST_RUN), "latest_status": "Error"},
        "label": None,
        "frozen_by": None,
        "frozen_at": None,
        "frozen": False,
        "comparison": {"source": 3, "target": 4},
    }


def test_a_frozen_version_shows_its_label_and_who_froze_it_and_when():
    detail = _history([_item(3, True, label="Q3 agreement")])["versions"][0]["detail"]

    assert detail["frozen"] is True
    assert detail["label"] == "Q3 agreement"
    assert detail["frozen_by"] == "alice"
    assert detail["frozen_at"] == _ms(FROZEN)


def test_a_version_without_runs_has_no_latest_run():
    runs = _history([_item(3, True)])["versions"][0]["detail"]["runs"]

    assert runs == {"count": 0, "latest_run_id": None, "latest_started_at": None, "latest_status": None}


def _comparisons(history) -> dict[int, dict | None]:
    return {v["version"]: v["detail"]["comparison"] for v in history["versions"]}


def test_the_newest_version_compares_the_active_version_against_the_draft():
    history = _history([_item(4, False), _item(3, True), _item(2, True)])

    assert _comparisons(history)[4] == {"source": 3, "target": 4}
    assert history["compare_disabled_reason"] is None


def test_without_a_draft_the_newest_version_compares_the_two_newest_versions():
    assert _comparisons(_history([_item(3, True), _item(2, True)]))[3] == {"source": 2, "target": 3}


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([_item(4, False), _item(3, True), _item(2, True)], {3: {"source": 3, "target": 4}, 2: {"source": 2, "target": 4}}),
        ([_item(3, True), _item(2, True), _item(1, True)], {2: {"source": 2, "target": 3}, 1: {"source": 1, "target": 3}}),
    ],
    ids=["with-draft", "without-draft"],
)
def test_an_older_version_compares_itself_against_the_newest_version(items, expected):
    comparisons = _comparisons(_history(items))

    assert {number: comparisons[number] for number in expected} == expected


def test_a_contract_with_one_version_has_nothing_to_compare():
    history = _history([_item(1, False)])

    assert _comparisons(history) == {1: None}
    assert history["compare_disabled_reason"] == "There is only one version."


def _version(versions: dict[int, SuiteVersion], number: int) -> SuiteVersion:
    if number not in versions:
        raise ValueError(f"This contract has no version {number}.")
    return versions[number]


def _compare(source, target, documents):
    suite = _suite()
    versions = {
        4: SuiteVersion(id=uuid4(), version=4, frozen_at=None),
        3: SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN),
    }
    with (
        patch.object(service.contract_service, "version_for_export", side_effect=lambda _, number: _version(versions, number)),
        patch.object(service.contract_service, "export_version", side_effect=documents),
        patch.object(service.SuiteVersion, "in_force_for", return_value=versions[3]),
    ):
        return service.version_comparison(suite, source, target)


def test_a_comparison_carries_both_documents_named_by_version():
    result = _compare(3, 4, [ExportedDocument("a: 1\n", []), ExportedDocument("a: 2\n", [])])

    assert result == {
        "source": 3,
        "target": 4,
        "source_label": "v3 active",
        "target_label": "v4 draft",
        "source_document": "a: 1\n",
        "target_document": "a: 2\n",
        "error": None,
    }


def test_a_version_that_cannot_be_rendered_is_reported():
    result = _compare(3, 4, [ExportedDocument("a: 1\n", []), ValueError("Term 12 names an undeclared column.")])

    assert result["error"] == "v4 draft could not be rendered. Term 12 names an undeclared column."
    assert result["source_document"] is None
    assert result["target_document"] is None


def test_a_version_that_no_longer_exists_is_reported():
    result = _compare(3, 5, [ExportedDocument("a: 1\n", [])])

    assert result["error"] == "This contract has no version 5."
    assert result["target_label"] == "v5"
    assert result["source_document"] is None
    assert result["target_document"] is None
