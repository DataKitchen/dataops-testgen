"""Freshness monitor scenario tests.

Pure Python tests that iterate through time series data, calling
compute_freshness_threshold() at each step with growing history,
and asserting expected outcomes at key checkpoints.

See scripts/test_data/SCENARIOS.md for scenario descriptions.
"""

import json

import pandas as pd
import pytest

from testgen.common.models.test_suite import PredictSensitivity

from .conftest import (
    ScenarioPoint,
    _gen_daily_late_gap_phase,
    _gen_daily_late_schedule_phase,
    _gen_daily_regular,
    _gen_mwf_late,
    _gen_mwf_regular,
    _gen_subdaily_gap_phase,
    _gen_subdaily_gap_schedule_phase,
    _gen_subdaily_regular,
    _gen_training_only,
    _gen_weekly_early,
    _run_scenario,
)


def _updates(results: list[ScenarioPoint]) -> list[ScenarioPoint]:
    """Filter to update points only (value == 0)."""
    return [p for p in results if p.value == 0]


def _anomalies(results: list[ScenarioPoint]) -> list[ScenarioPoint]:
    """Filter to anomaly points only (result_code == 0)."""
    return [p for p in results if p.result_code == 0]



def _schedule(point: ScenarioPoint) -> dict | None:
    if not point.prediction_json:
        return None
    data = json.loads(point.prediction_json)
    return data if data else None


# ─── Scenario 1: Daily Regular ──────────────────────────────────────


class Test_DailyRegular:
    """Happy path: daily weekday updates at 07:00 UTC, 5 weeks."""

    @pytest.fixture(scope="class")
    def results_excl(self) -> list[ScenarioPoint]:
        rows = _gen_daily_regular()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=True, tz="America/New_York")

    @pytest.fixture(scope="class")
    def results_no_excl(self) -> list[ScenarioPoint]:
        rows = _gen_daily_regular()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=False, tz=None)

    def test_training_exits(self, results_excl: list[ScenarioPoint]) -> None:
        """Training should end. First non-training update needs 5 gaps + min_lookback=30 rows."""
        updates = _updates(results_excl)
        first_non_training = next((i for i, p in enumerate(updates) if p.upper is not None), None)
        assert first_non_training is not None
        # 5 weekday updates = 5 gaps, but min_lookback=30 means ~30 rows needed first
        # With 12h obs interval and daily updates, training exits around update 10-14
        assert 6 <= first_non_training <= 16

    def test_zero_anomalies_excl(self, results_excl: list[ScenarioPoint]) -> None:
        assert len(_anomalies(results_excl)) == 0

    def test_zero_anomalies_no_excl(self, results_no_excl: list[ScenarioPoint]) -> None:
        assert len(_anomalies(results_no_excl)) == 0

    def test_thresholds_present_after_training(self, results_excl: list[ScenarioPoint]) -> None:
        post_training = [p for p in results_excl if p.upper is not None]
        assert len(post_training) > 0
        for p in post_training:
            assert p.upper > 0


# ─── Scenario 2a: Daily Late (Gap Phase) ────────────────────────────


class Test_DailyLateGapPhase:
    """3-day outage during gap-duration phase (~16 completed gaps)."""

    @pytest.fixture(scope="class")
    def results_excl(self) -> list[ScenarioPoint]:
        rows = _gen_daily_late_gap_phase()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=True, tz="America/New_York")

    @pytest.fixture(scope="class")
    def results_no_excl(self) -> list[ScenarioPoint]:
        rows = _gen_daily_late_gap_phase()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=False, tz=None)

    def test_schedule_tentative_excl(self, results_excl: list[ScenarioPoint]) -> None:
        """At ~16 gaps, schedule should be tentative (not active)."""
        outage_start = pd.Timestamp("2025-10-29")
        pre_outage = [p for p in results_excl if p.timestamp < outage_start and p.prediction_json]
        last_sched = _schedule(pre_outage[-1]) if pre_outage else None
        if last_sched and last_sched.get("schedule_stage"):
            assert last_sched["schedule_stage"] in ("tentative", "training")

    def test_anomaly_detected_during_outage_excl(self, results_excl: list[ScenarioPoint]) -> None:
        """Anomaly should be detected during the Wed-Fri outage."""
        outage_start = pd.Timestamp("2025-10-29")
        recovery = pd.Timestamp("2025-11-03 07:00")  # Mon
        outage_anomalies = [p for p in _anomalies(results_excl) if outage_start <= p.timestamp < recovery]
        assert len(outage_anomalies) > 0

    def test_anomaly_detected_during_outage_no_excl(self, results_no_excl: list[ScenarioPoint]) -> None:
        """Anomaly should be detected during outage (possibly delayed)."""
        outage_start = pd.Timestamp("2025-10-29")
        recovery = pd.Timestamp("2025-11-03 19:00")
        outage_anomalies = [p for p in _anomalies(results_no_excl) if outage_start <= p.timestamp <= recovery]
        assert len(outage_anomalies) > 0

    def test_recovery_passes_excl(self, results_excl: list[ScenarioPoint]) -> None:
        """After recovery on Monday, subsequent updates should pass.

        The first recovery update (Mon 07:00) marks the completion of the
        anomalous outage gap, so it legitimately fails. The SECOND update
        after recovery should pass.
        """
        recovery = pd.Timestamp("2025-11-03 07:00")
        post_recovery_updates = [p for p in _updates(results_excl) if p.timestamp >= recovery]
        assert len(post_recovery_updates) >= 2
        # First recovery update completes the outage gap — expected to fail
        assert post_recovery_updates[0].result_code == 0
        # Second and subsequent updates should pass
        for p in post_recovery_updates[1:3]:
            assert p.result_code == 1, f"Expected pass at {p.timestamp}, got code={p.result_code}"


# ─── Scenario 2b: Daily Late (Schedule Phase) ───────────────────────


class Test_DailyLateSchedulePhase:
    """3-day outage during schedule inference phase (~26 completed gaps)."""

    @pytest.fixture(scope="class")
    def results_excl(self) -> list[ScenarioPoint]:
        rows = _gen_daily_late_schedule_phase()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=True, tz="America/New_York")

    @pytest.fixture(scope="class")
    def results_no_excl(self) -> list[ScenarioPoint]:
        rows = _gen_daily_late_schedule_phase()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=False, tz="America/New_York")

    def test_schedule_active_before_outage(self, results_excl: list[ScenarioPoint]) -> None:
        """By ~26 gaps, schedule should reach 'active' stage."""
        outage_start = pd.Timestamp("2025-11-12")
        pre_outage = [p for p in results_excl if p.timestamp < outage_start and p.prediction_json]
        last_sched = _schedule(pre_outage[-1]) if pre_outage else None
        assert last_sched is not None
        assert last_sched.get("schedule_stage") == "active"

    def test_anomaly_detected_during_outage_excl(self, results_excl: list[ScenarioPoint]) -> None:
        outage_start = pd.Timestamp("2025-11-12")
        recovery = pd.Timestamp("2025-11-17 07:00")
        outage_anomalies = [p for p in _anomalies(results_excl) if outage_start <= p.timestamp < recovery]
        assert len(outage_anomalies) > 0

    def test_anomaly_detected_during_outage_no_excl(self, results_no_excl: list[ScenarioPoint]) -> None:
        outage_start = pd.Timestamp("2025-11-12")
        recovery = pd.Timestamp("2025-11-17 19:00")
        outage_anomalies = [p for p in _anomalies(results_no_excl) if outage_start <= p.timestamp <= recovery]
        assert len(outage_anomalies) > 0

    def test_detection_no_later_than_gap_phase(self, results_excl: list[ScenarioPoint]) -> None:
        """Schedule-phase detection should be no later than gap-phase."""
        gap_rows = _gen_daily_late_gap_phase()
        gap_results = _run_scenario(gap_rows, PredictSensitivity.medium, exclude_weekends=True, tz="America/New_York")

        # Find first anomaly relative to outage start in each scenario
        gap_outage_start = pd.Timestamp("2025-10-29")
        sched_outage_start = pd.Timestamp("2025-11-12")

        gap_first = next(
            ((p.timestamp - gap_outage_start).total_seconds() for p in _anomalies(gap_results)
             if p.timestamp >= gap_outage_start),
            None,
        )
        sched_first = next(
            ((p.timestamp - sched_outage_start).total_seconds() for p in _anomalies(results_excl)
             if p.timestamp >= sched_outage_start),
            None,
        )

        assert gap_first is not None and sched_first is not None
        assert sched_first <= gap_first, (
            f"Schedule-phase detected at +{sched_first/3600:.1f}h but gap-phase at +{gap_first/3600:.1f}h"
        )


# ─── Scenario 3: Sub-daily Regular ──────────────────────────────────


class Test_SubdailyRegular:
    """Sub-daily happy path: updates every 2h from 08:00-18:00 on weekdays."""

    @pytest.fixture(scope="class")
    def results(self) -> list[ScenarioPoint]:
        rows = _gen_subdaily_regular()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=True, tz="America/New_York")

    def test_zero_anomalies(self, results: list[ScenarioPoint]) -> None:
        assert len(_anomalies(results)) == 0

    def test_schedule_active_with_subdaily(self, results: list[ScenarioPoint]) -> None:
        """Schedule should reach active with sub_daily frequency."""
        last_with_sched = None
        for p in reversed(results):
            sched = _schedule(p)
            if sched and sched.get("schedule_stage"):
                last_with_sched = sched
                break
        assert last_with_sched is not None
        assert last_with_sched["schedule_stage"] == "active"
        assert last_with_sched["frequency"] == "sub_daily"

    def test_window_set(self, results: list[ScenarioPoint]) -> None:
        """Active sub-daily schedule should have a time window."""
        last_with_sched = None
        for p in reversed(results):
            sched = _schedule(p)
            if sched and sched.get("schedule_stage") == "active":
                last_with_sched = sched
                break
        assert last_with_sched is not None
        assert last_with_sched.get("window_start") is not None
        assert last_with_sched.get("window_end") is not None


# ─── Scenario 4a: Sub-daily Gap (Gap Phase) ─────────────────────────


class Test_SubdailyGapPhase:
    """Within-window gap during gap-duration phase (schedule NOT active)."""

    @pytest.fixture(scope="class")
    def results(self) -> list[ScenarioPoint]:
        rows = _gen_subdaily_gap_phase()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=True, tz="America/New_York")

    def test_schedule_not_active(self, results: list[ScenarioPoint]) -> None:
        """Schedule should NOT be active at ~16 days of history."""
        gap_date = pd.Timestamp("2025-10-22")
        pre_gap = [p for p in results if p.timestamp < gap_date and p.prediction_json]
        if pre_gap:
            sched = _schedule(pre_gap[-1])
            if sched and sched.get("schedule_stage"):
                assert sched["schedule_stage"] != "active"

    def test_anomaly_detected_late(self, results: list[ScenarioPoint]) -> None:
        """Without schedule, anomaly triggers late (fallback to upper)."""
        gap_start = pd.Timestamp("2025-10-22 10:00")
        gap_end = pd.Timestamp("2025-10-23 08:00")
        gap_anomalies = [p for p in _anomalies(results) if gap_start <= p.timestamp <= gap_end]
        assert len(gap_anomalies) > 0

    def test_recovery_passes(self, results: list[ScenarioPoint]) -> None:
        """Recovery at Thu 10:00 should pass."""
        recovery = pd.Timestamp("2025-10-23 10:00")
        post = [p for p in _updates(results) if p.timestamp >= recovery]
        assert len(post) > 0
        assert post[0].result_code == 1


# ─── Scenario 4b: Sub-daily Gap (Schedule Phase) ────────────────────


class Test_SubdailyGapSchedulePhase:
    """Within-window gap during schedule inference phase (schedule active)."""

    @pytest.fixture(scope="class")
    def results(self) -> list[ScenarioPoint]:
        rows = _gen_subdaily_gap_schedule_phase()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=True, tz="America/New_York")

    def test_schedule_active(self, results: list[ScenarioPoint]) -> None:
        """Schedule should be active by the gap date."""
        gap_date = pd.Timestamp("2025-10-29")
        pre_gap = [p for p in results if p.timestamp < gap_date and p.prediction_json]
        sched = _schedule(pre_gap[-1]) if pre_gap else None
        assert sched is not None
        assert sched.get("schedule_stage") == "active"

    def test_anomaly_detected_earlier_than_gap_phase(self, results: list[ScenarioPoint]) -> None:
        """Schedule-aware detection should catch the gap earlier than 4a."""
        gap_phase_rows = _gen_subdaily_gap_phase()
        gap_phase_results = _run_scenario(
            gap_phase_rows, PredictSensitivity.medium, exclude_weekends=True, tz="America/New_York",
        )

        # Time from gap start to first anomaly
        gap_4a_start = pd.Timestamp("2025-10-22 10:00")
        gap_4b_start = pd.Timestamp("2025-10-29 10:00")

        first_4a = next(
            ((p.timestamp - gap_4a_start).total_seconds() for p in _anomalies(gap_phase_results)
             if p.timestamp >= gap_4a_start),
            None,
        )
        first_4b = next(
            ((p.timestamp - gap_4b_start).total_seconds() for p in _anomalies(results)
             if p.timestamp >= gap_4b_start),
            None,
        )

        assert first_4a is not None and first_4b is not None
        assert first_4b < first_4a, (
            f"4b detected at +{first_4b/3600:.1f}h but 4a at +{first_4a/3600:.1f}h"
        )

    def test_off_window_suppressed(self, results: list[ScenarioPoint]) -> None:
        """Overnight/off-window observations should be suppressed (passed) when schedule is active."""
        gap_date = pd.Timestamp("2025-10-29")
        # After the gap, overnight obs between 0:00-6:00 should not be anomalies
        overnight_after_gap = [
            p for p in results
            if p.timestamp.date() == gap_date.date()
            and p.timestamp.hour < 6
            and p.value > 0
            and p.upper is not None  # post-training
        ]
        for p in overnight_after_gap:
            assert p.result_code != 0, f"Off-window anomaly at {p.timestamp}"


# ─── Scenario 5: Weekly Early ───────────────────────────────────────


class Test_WeeklyEarly:
    """Weekly Thursday updates, early Tuesday update in week 11."""

    @pytest.fixture(scope="class")
    def results(self) -> list[ScenarioPoint]:
        rows = _gen_weekly_early()
        return _run_scenario(rows, PredictSensitivity.low, exclude_weekends=False, tz=None)

    def test_early_update_detected(self, results: list[ScenarioPoint]) -> None:
        """Lower bound should trigger on the early Tuesday update."""
        early_ts = pd.Timestamp("2025-10-21 10:00")
        early_point = next((p for p in results if p.timestamp == early_ts), None)
        assert early_point is not None
        assert early_point.result_code == 0, f"Expected anomaly at early update, got code={early_point.result_code}"

    def test_lower_bound_present(self, results: list[ScenarioPoint]) -> None:
        """Lower bound should be non-None by the time of the early update."""
        early_ts = pd.Timestamp("2025-10-21 10:00")
        early_point = next((p for p in results if p.timestamp == early_ts), None)
        assert early_point is not None
        assert early_point.lower is not None
        assert early_point.lower > 0


# ─── Scenario 6: Training Only ──────────────────────────────────────


class Test_TrainingOnly:
    """Insufficient data: only 4 updates (3 completed gaps)."""

    @pytest.fixture(scope="class")
    def results(self) -> list[ScenarioPoint]:
        rows = _gen_training_only()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=False, tz=None)

    def test_all_training(self, results: list[ScenarioPoint]) -> None:
        """ALL observations should be training (result_code == -1)."""
        for p in results:
            assert p.result_code == -1, f"Expected training at {p.timestamp}, got code={p.result_code}"

    def test_upper_never_set(self, results: list[ScenarioPoint]) -> None:
        """Upper threshold should never be non-None."""
        for p in results:
            assert p.upper is None, f"Expected upper=None at {p.timestamp}, got {p.upper}"


# ─── Scenario 7: MWF Regular ────────────────────────────────────────


class Test_MWFRegular:
    """Mon/Wed/Fri updates at 07:00 UTC, 8 weeks. No anomalies."""

    @pytest.fixture(scope="class")
    def results(self) -> list[ScenarioPoint]:
        rows = _gen_mwf_regular()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=False, tz="America/New_York")

    def test_zero_anomalies(self, results: list[ScenarioPoint]) -> None:
        assert len(_anomalies(results)) == 0

    def test_schedule_active(self, results: list[ScenarioPoint]) -> None:
        last_sched = None
        for p in reversed(results):
            sched = _schedule(p)
            if sched and sched.get("schedule_stage"):
                last_sched = sched
                break
        assert last_sched is not None
        assert last_sched["schedule_stage"] == "active"

    def test_active_days_mwf(self, results: list[ScenarioPoint]) -> None:
        """Active days should be Mon(0), Wed(2), Fri(4)."""
        last_sched = None
        for p in reversed(results):
            sched = _schedule(p)
            if sched and sched.get("schedule_stage") == "active":
                last_sched = sched
                break
        assert last_sched is not None
        assert set(last_sched["active_days"]) == {0, 2, 4}

    def test_frequency_irregular(self, results: list[ScenarioPoint]) -> None:
        """MWF cadence (median ~48h gap) should classify as 'irregular'."""
        last_sched = None
        for p in reversed(results):
            sched = _schedule(p)
            if sched and sched.get("schedule_stage") == "active":
                last_sched = sched
                break
        assert last_sched is not None
        assert last_sched["frequency"] == "irregular"


# ─── Scenario 8: MWF Late ───────────────────────────────────────────


class Test_MWFLate:
    """Mon/Wed/Fri updates, skip Wed+Fri of week 8 (outage)."""

    @pytest.fixture(scope="class")
    def results(self) -> list[ScenarioPoint]:
        rows = _gen_mwf_late()
        return _run_scenario(rows, PredictSensitivity.medium, exclude_weekends=False, tz="America/New_York")

    def test_schedule_active_before_outage(self, results: list[ScenarioPoint]) -> None:
        outage_start = pd.Timestamp("2025-11-26")
        pre_outage = [p for p in results if p.timestamp < outage_start and p.prediction_json]
        sched = _schedule(pre_outage[-1]) if pre_outage else None
        assert sched is not None
        assert sched.get("schedule_stage") == "active"

    def test_anomaly_on_missed_wed(self, results: list[ScenarioPoint]) -> None:
        """Anomaly should be detected around the missed Wed update."""
        missed_wed = pd.Timestamp("2025-11-26")
        next_update = pd.Timestamp("2025-12-01 07:00")  # Mon recovery
        outage_anomalies = [p for p in _anomalies(results) if missed_wed <= p.timestamp < next_update]
        assert len(outage_anomalies) > 0

    def test_recovery_passes(self, results: list[ScenarioPoint]) -> None:
        """After recovery on Mon week 9, subsequent updates should pass.

        The first recovery update completes the outage gap and fails.
        The second update after recovery should pass.
        """
        recovery = pd.Timestamp("2025-12-01 07:00")
        post_recovery = [p for p in _updates(results) if p.timestamp >= recovery]
        assert len(post_recovery) >= 2
        # First recovery update completes the outage gap — expected to fail
        assert post_recovery[0].result_code == 0
        # Second update after recovery should pass
        assert post_recovery[1].result_code == 1
