import zoneinfo
from datetime import datetime
from typing import TypedDict

import cron_converter
import cron_descriptor


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
            samples = [cron_schedule.next().strftime("%a %b %-d, %-I:%M %p") for _ in range(sample_count)]
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
