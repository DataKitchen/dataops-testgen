"""Resolving the contract version a run, an export, or an import addresses, and a contract's verification status."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common import contract_service
from testgen.common.contract_service import (
    NoActiveTestsError,
    NotAContractError,
    UnknownVersionError,
    VerificationUnavailable,
)
from testgen.common.enums import JobStatus, SuiteType
from testgen.common.models.suite_version import ContractState, SuiteVersion, VersionState

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 9, 12, tzinfo=UTC)


def _suite(suite_type=SuiteType.CONTRACT):
    return MagicMock(id=uuid4(), suite_type=suite_type)


@pytest.fixture
def session():
    with patch.object(contract_service, "get_current_session") as session_fn:
        yield session_fn.return_value


# --- version_by_number ---


def test_a_version_of_a_regular_suite_is_refused():
    with pytest.raises(NotAContractError):
        contract_service.version_by_number(_suite(SuiteType.STANDARD), 1)


def test_an_unknown_version_names_the_highest_one(session):
    session.scalar.return_value = 3
    with (
        patch.object(SuiteVersion, "for_number", return_value=None),
        pytest.raises(UnknownVersionError) as refused,
    ):
        contract_service.version_by_number(_suite(), 9)
    assert (refused.value.version, refused.value.highest) == (9, 3)


# --- run_target ---


def _run_target(suite, version=None, *, found=None, run_default=None, active=True, active_tests=2):
    with (
        patch.object(SuiteVersion, "for_number", return_value=found),
        patch.object(SuiteVersion, "get", return_value=run_default),
        patch.object(SuiteVersion, "is_active", return_value=active),
        patch.object(contract_service.TestDefinition, "list_for_suite", return_value=([], active_tests)) as listing,
        patch.object(contract_service, "get_current_session"),
    ):
        return contract_service.run_target(suite, version), listing


def test_a_regular_suite_has_no_run_target():
    target, listing = _run_target(_suite(SuiteType.STANDARD))
    assert target is None
    listing.assert_not_called()


def test_a_contract_runs_its_active_version_by_default():
    active = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN)
    target, _ = _run_target(_suite(), run_default=active)
    assert (target.version, target.state, target.note) == (active, VersionState.ACTIVE, None)


def test_a_run_of_the_draft_is_a_preview():
    draft = SuiteVersion(id=uuid4(), version=1)
    target, _ = _run_target(_suite(), run_default=draft, active=False)
    assert target.state == VersionState.DRAFT
    assert "Unless the version is frozen before the run starts" in target.note


def test_a_run_of_a_superseded_version_is_a_check():
    superseded = SuiteVersion(id=uuid4(), version=2, frozen_at=FROZEN)
    target, _ = _run_target(_suite(), 2, found=superseded, active=False)
    assert target.version is superseded
    assert target.state == VersionState.SUPERSEDED
    assert "checks a superseded version" in target.note


def test_a_version_with_no_active_tests_is_refused():
    draft = SuiteVersion(id=uuid4(), version=4)
    with pytest.raises(NoActiveTestsError) as refused:
        _run_target(_suite(), 4, found=draft, active=False, active_tests=0)
    assert (refused.value.version, refused.value.state) == (draft, VersionState.DRAFT)


def test_only_the_versions_active_tests_count():
    version = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN)
    _, listing = _run_target(_suite(), 3, found=version)
    assert listing.call_args.kwargs["test_active"] is True
    assert listing.call_args.kwargs["version_id"] == version.id
    assert listing.call_args.kwargs["suite_types"] == (SuiteType.CONTRACT,)


# --- import_destination ---


@pytest.mark.parametrize(
    ("resolved", "preview", "expected"),
    [
        (SuiteVersion(id=uuid4(), version=4), True, (4, VersionState.DRAFT)),
        (SuiteVersion(id=uuid4(), version=4), False, (4, VersionState.DRAFT)),
        (SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN), True, (4, VersionState.DRAFT)),
        (SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN), False, (3, VersionState.ACTIVE)),
    ],
    ids=["preview-into-draft", "apply-into-draft", "preview-opens-a-draft", "apply-into-a-frozen-version"],
)
def test_an_import_lands_in_the_draft_or_names_the_one_it_would_open(resolved, preview, expected):
    with (
        patch.object(contract_service, "version_for_export", return_value=resolved),
        patch.object(SuiteVersion, "next_version_for", return_value=4),
        patch.object(SuiteVersion, "is_active", return_value=True),
    ):
        assert contract_service.import_destination(_suite(), preview=preview) == expected


# --- contract_status ---


def _status(state, *, runs=(), summaries=None):
    summaries = summaries or {}

    def select_summary(*, test_run_ids, **_):
        found = [summaries[run_id] for run_id in test_run_ids if run_id in summaries]
        return found, len(found)

    with (
        patch.object(SuiteVersion, "states_for", side_effect=lambda ids: {ids[0]: state}),
        patch.object(contract_service.TestRun, "latest_verification", side_effect=list(runs)) as latest,
        patch.object(contract_service.TestRun, "select_summary", side_effect=select_summary),
    ):
        return contract_service.contract_status(_suite()), latest


def test_a_contract_with_nothing_frozen_has_no_verification():
    draft = SuiteVersion(id=uuid4(), version=1)
    status, latest = _status(ContractState(active=None, draft=draft))
    assert (status.counted_from, status.unavailable) == (draft, VerificationUnavailable.nothing_frozen)
    latest.assert_not_called()


def test_a_frozen_version_never_run_has_no_verification():
    active = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN)
    status, _ = _status(ContractState(active=active, draft=None), runs=[None])
    assert status.unavailable == VerificationUnavailable.not_run_since_frozen
    assert status.counted_from is active


def test_the_latest_completed_run_is_the_verification():
    active = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN)
    run = MagicMock(id=uuid4())
    summary = MagicMock(status=JobStatus.COMPLETED)
    status, _ = _status(ContractState(active=active, draft=None), runs=[run], summaries={run.id: summary})
    assert (status.latest_verification, status.incomplete_run, status.unavailable) == (summary, None, None)


def test_an_incomplete_latest_run_falls_back_to_the_last_completed_one():
    active = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN)
    newest, completed = MagicMock(id=uuid4()), MagicMock(id=uuid4())
    summaries = {newest.id: MagicMock(status=JobStatus.ERROR), completed.id: MagicMock(status=JobStatus.COMPLETED)}
    status, _ = _status(ContractState(active=active, draft=None), runs=[newest, completed], summaries=summaries)
    assert status.latest_verification is summaries[completed.id]
    assert status.incomplete_run is summaries[newest.id]
    assert status.unavailable is None


def test_an_incomplete_latest_run_with_no_completed_one_has_no_verification():
    active = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN)
    newest = MagicMock(id=uuid4())
    summaries = {newest.id: MagicMock(status=JobStatus.RUNNING)}
    status, _ = _status(ContractState(active=active, draft=None), runs=[newest, None], summaries=summaries)
    assert status.latest_verification is None
    assert status.incomplete_run is summaries[newest.id]
    assert status.unavailable == VerificationUnavailable.latest_run_incomplete


def test_contract_status_refuses_a_regular_suite():
    with pytest.raises(ValueError, match="not a contract"):
        contract_service.contract_status(_suite(SuiteType.STANDARD))
