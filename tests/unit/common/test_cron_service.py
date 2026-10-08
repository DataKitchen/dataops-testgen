"""Tests for ``validate_schedule`` and ``normalize_cron``."""

import pytest

from testgen.common.cron_service import normalize_cron, validate_schedule

pytestmark = pytest.mark.unit

NAMES = {"cron_expr": "cron_expression", "cron_tz": "timezone"}


@pytest.mark.parametrize(
    ("cron_expr", "cron_tz"),
    [
        ("0 3 * * *", "UTC"),
        ("*/15 * * * *", "America/New_York"),
        ("0 3 * * mon-fri", "Europe/Lisbon"),
    ],
)
def test_validate_accepts_a_valid_schedule(cron_expr, cron_tz):
    assert validate_schedule(cron_expr, cron_tz, field_names=NAMES) == []


def test_validate_requires_both_fields():
    assert validate_schedule("", None, field_names=NAMES) == [
        "`cron_expression` is required.",
        "`timezone` is required (IANA name, e.g. `UTC`).",
    ]


@pytest.mark.parametrize(
    ("cron_expr", "reason"),
    [
        ("61 * * * *", "Value 61 out of range for 'minute'"),
        ("0 3 * * * *", "Invalid cron string format"),
        ("@daily", "Invalid cron string format"),
        ("0 0 31 2 *", "Error validating the Cron expression"),
    ],
    ids=["out-of-range", "six-fields", "macro", "never-fires"],
)
def test_validate_rejects_an_expression_the_scheduler_cannot_run(cron_expr, reason):
    assert validate_schedule(cron_expr, "UTC", field_names=NAMES) == [f"Invalid cron expression or timezone: {reason}"]


@pytest.mark.parametrize("cron_tz", ["Mars/Base", "Europe/Atlantis"])
def test_validate_rejects_an_unknown_timezone(cron_tz):
    assert validate_schedule("0 3 * * *", cron_tz, field_names=NAMES) == [
        f"Invalid cron expression or timezone: Unknown timezone `{cron_tz}`. Use an IANA name (e.g. `America/New_York`).",
    ]


def test_validate_rejects_values_wider_than_their_columns():
    """``America/Argentina/ComodRivadavia`` is a valid IANA name that does not fit ``cron_tz``."""
    assert validate_schedule("0 3 * * " + "1," * 30 + "1", "America/Argentina/ComodRivadavia", field_names=NAMES) == [
        "`cron_expression` must be at most 50 characters.",
        "`timezone` must be at most 30 characters.",
    ]


def test_validate_names_fields_by_the_supplied_mapping():
    assert validate_schedule("", "", field_names={"cron_expr": "schedule", "cron_tz": "cron_tz"}) == [
        "`schedule` is required.",
        "`cron_tz` is required (IANA name, e.g. `UTC`).",
    ]


@pytest.mark.parametrize(
    ("cron_expr", "normalized"),
    [
        ("0 3 * * *", "0 3 * * *"),
        ("0  3 * *  *", "0 3 * * *"),
        ("0 3 * * mon-fri", "0 3 * * 1-5"),
    ],
)
def test_normalize_gives_one_spelling_per_schedule(cron_expr, normalized):
    assert normalize_cron(cron_expr) == normalized
