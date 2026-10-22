from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.test_run import TestRun

pytestmark = pytest.mark.unit

MODULE = "testgen.common.models.test_run"

STARTED = datetime(2026, 10, 1, 12, 0)
BEFORE_START = datetime(2026, 10, 1, 11, 55, tzinfo=UTC)
DURING_RUN = datetime(2026, 10, 1, 12, 5, tzinfo=UTC)
VERSION_ID = uuid4()
SUITE_ID = uuid4()


@pytest.fixture
def mock_session():
    session = MagicMock()
    with patch(f"{MODULE}.get_current_session", return_value=session):
        yield session


def _run(version_id=VERSION_ID) -> TestRun:
    return TestRun(id=uuid4(), version_id=version_id, test_starttime=STARTED)


def _version(frozen_at, test_suite_id=SUITE_ID, version=2):
    return SimpleNamespace(version=version, frozen_at=frozen_at, test_suite_id=test_suite_id)


def test_a_run_with_no_version_checked_the_version_in_force(mock_session):
    assert _run(version_id=None).checked_version_in_force() is True
    mock_session.execute.assert_not_called()


def test_a_run_of_a_regular_suite_checked_the_version_in_force(mock_session):
    mock_session.execute.return_value.first.return_value = _version(frozen_at=None, test_suite_id=None)
    assert _run().checked_version_in_force() is True


@pytest.mark.parametrize(
    ("frozen_at", "in_force_at_start", "expected"),
    [
        (None, 1, False),
        (DURING_RUN, 1, False),
        (BEFORE_START, 2, True),
        (BEFORE_START, 3, False),
    ],
    ids=["draft", "frozen-during-the-run", "in-force", "superseded-before-the-run"],
)
def test_a_run_counts_only_when_its_version_was_in_force_at_the_start(
    mock_session, frozen_at, in_force_at_start, expected
):
    mock_session.execute.return_value.first.return_value = _version(frozen_at)
    mock_session.scalar.return_value = in_force_at_start

    assert _run().checked_version_in_force() is expected


def test_a_run_of_a_discarded_draft_did_not_check_the_version_in_force(mock_session):
    mock_session.execute.return_value.first.return_value = None
    assert _run().checked_version_in_force() is False
