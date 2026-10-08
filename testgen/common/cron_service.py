import zoneinfo
from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict

import cron_converter
import cron_descriptor

from testgen.common import date_service


class CronSample(TypedDict, total=False):
    id: str | None
    error: str | None
    samples: list[str] | list[int] | None
    readable_expr: str | None


def get_cron_sample(
    cron_expr: str,
    cron_tz: str,
    sample_count: int,
    *,
    reference_time: datetime | None = None,
    formatted: bool = False,
) -> CronSample:
    try:
        cron_obj = cron_converter.Cron(cron_expr)
        cron_schedule = cron_obj.schedule(reference_time or datetime.now(zoneinfo.ZoneInfo(cron_tz)))
        readable_cron_schedule = cron_descriptor.get_description(cron_expr)
        if formatted:
            samples = [date_service.format_friendly_datetime(cron_schedule.next(), "%a %b %-d, %-I:%M %p") for _ in range(sample_count)]
        else:
            samples = [int(cron_schedule.next().timestamp()) for _ in range(sample_count)]
    except zoneinfo.ZoneInfoNotFoundError:
        return {"error": f"Unknown timezone `{cron_tz}`. Use an IANA name (e.g. `America/New_York`)."}
    except ValueError as e:
        return {"error": str(e)}
    except Exception:
        return {"error": "Error validating the Cron expression"}
    else:
        return {
            "samples": samples,
            "readable_expr": readable_cron_schedule,
        }


def describe_cron(cron_expr: str) -> str | None:
    """Human-readable description of a cron expression, e.g. ``At 04:00 AM``. Returns ``None`` if unparseable."""
    try:
        return cron_descriptor.get_description(cron_expr)
    except Exception:
        return None


# Widths of the ``job_schedules`` VARCHAR columns (030_initialize_new_schema_structure.sql).
_CRON_EXPR_MAX = 50
_CRON_TZ_MAX = 30

def validate_schedule(cron_expr: str | None, cron_tz: str | None, *, field_names: Mapping[str, str]) -> list[str]:
    """Return every reason a cron expression and timezone cannot be stored as a schedule (empty list = valid).

    Args:
        cron_expr: The cron expression, five space-separated fields.
        cron_tz: An IANA timezone name.
        field_names: Name to show in the messages for each input, keyed ``cron_expr`` and ``cron_tz``.
    """
    names = field_names
    errors: list[str] = []

    if not cron_expr:
        errors.append(f"`{names['cron_expr']}` is required.")
    elif len(cron_expr) > _CRON_EXPR_MAX:
        errors.append(f"`{names['cron_expr']}` must be at most {_CRON_EXPR_MAX} characters.")

    if not cron_tz:
        errors.append(f"`{names['cron_tz']}` is required (IANA name, e.g. `UTC`).")
    elif len(cron_tz) > _CRON_TZ_MAX:
        errors.append(f"`{names['cron_tz']}` must be at most {_CRON_TZ_MAX} characters.")

    if not errors:
        sample = get_cron_sample(cron_expr, cron_tz, sample_count=1)
        if "error" in sample:
            errors.append(f"Invalid cron expression or timezone: {sample['error']}")

    return errors


def normalize_cron(cron_expr: str) -> str:
    """Return ``cron_expr`` in canonical form, e.g. ``0 3 * * mon-fri`` as ``0 3 * * 1-5``.

    The expression must already be valid.
    """
    return cron_converter.Cron(cron_expr).to_string()
