from unittest.mock import patch

import pytest

from testgen.commands.run_rollup_scores import run_refresh_run_scores
from testgen.common.enums import JobKey

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_rollup_scores"


@pytest.mark.parametrize(
    ("run_job_key", "rollup"),
    [(JobKey.run_profile, "run_profile_rollup_scoring_queries"), (JobKey.run_tests, "run_test_rollup_scoring_queries")],
)
def test_refresh_rolls_up_the_run_by_its_kind(run_job_key, rollup):
    with patch(f"{MODULE}.{rollup}") as mock_rollup:
        run_refresh_run_scores(str(run_job_key), "DEFAULT", "run-1", "tg-1")

    mock_rollup.assert_called_once_with("DEFAULT", "run-1", "tg-1")


def test_refresh_rejects_an_unknown_run_kind():
    with pytest.raises(ValueError, match="run-monitors"):
        run_refresh_run_scores("run-monitors", "DEFAULT", "run-1")
