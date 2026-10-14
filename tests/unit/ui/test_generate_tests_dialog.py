"""Tests for the value hash warning in the Generate Tests dialog, testgen.ui.views.dialogs.generate_tests_dialog."""

from unittest.mock import MagicMock, patch

import pytest

from testgen.ui.views.dialogs import generate_tests_dialog as dialog

pytestmark = pytest.mark.unit


def _warning(
    *,
    supports_value_hash=True,
    profile_run_id="run-1",
    has_value_hashes=False,
    profile_table_comparison=False,
    profiling_delay_days=0,
):
    table_group = MagicMock(
        profile_table_comparison=profile_table_comparison, profiling_delay_days=profiling_delay_days
    )
    with (
        patch.object(dialog.TableGroup, "get", return_value=table_group),
        patch.object(dialog.Connection, "get"),
        patch.object(dialog, "get_flavor_service", return_value=MagicMock(supports_value_hash=supports_value_hash)),
        patch.object(dialog.ProfilingRun, "latest_readable_id", return_value=profile_run_id),
        patch.object(dialog.ProfileResult, "has_value_hashes", return_value=has_value_hashes),
    ):
        return dialog.get_value_hash_warning.__wrapped__("tg-1")


def test_warns_to_turn_on_table_comparison_when_it_is_off(db_session_mock):
    assert "Profile for table comparison" in _warning(profile_table_comparison=False)


def test_warns_to_profile_again_when_it_is_on_but_the_profile_has_no_hashes(db_session_mock):
    warning = _warning(profile_table_comparison=True)

    assert "Run profiling again" in warning
    assert "Profile for table comparison" not in warning


@pytest.mark.parametrize(
    ("profiling_delay_days", "age_note"),
    [
        pytest.param(0, None, id="no_minimum_age"),
        pytest.param(1, "once it is 1 day old", id="one_day"),
        pytest.param(3, "once it is 3 days old", id="several_days"),
    ],
)
def test_names_the_minimum_profiling_age_a_new_run_must_reach(db_session_mock, profiling_delay_days, age_note):
    warning = _warning(profile_table_comparison=True, profiling_delay_days=profiling_delay_days)

    if age_note:
        assert age_note in warning
    else:
        assert "minimum profiling age" not in warning


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"has_value_hashes": True}, id="profile_has_hashes"),
        pytest.param({"profile_run_id": None}, id="no_profile"),
        pytest.param({"supports_value_hash": False}, id="connection_type_does_not_hash"),
    ],
)
def test_no_warning(db_session_mock, overrides):
    assert _warning(**overrides) is None
