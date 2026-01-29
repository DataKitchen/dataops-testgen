import zoneinfo
from collections.abc import Callable
from datetime import datetime
from typing import TypedDict

import cron_converter
import cron_descriptor

from testgen.ui.session import temp_value


class CronSample(TypedDict):
    id: str | None
    error: str | None
    samples: list[str] | None
    readable_expr: str | None

class CronSampleHandlerPayload(TypedDict):
    tz: str
    cron_expr: str


CronSampleCallback = Callable[[CronSampleHandlerPayload], None]


def get_cron_sample(cron_expr: str, cron_tz: str, sample_count: int) -> CronSample:
    try:
        cron_obj = cron_converter.Cron(cron_expr)
        cron_schedule = cron_obj.schedule(datetime.now(zoneinfo.ZoneInfo(cron_tz)))
        readble_cron_schedule = cron_descriptor.get_description(cron_expr)
        return {
            "samples": [cron_schedule.next().strftime("%a %b %-d, %-I:%M %p") for _ in range(sample_count)],
            "readable_expr": readble_cron_schedule,
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": "Error validating the Cron expression"}


def get_cron_sample_handler(key: str, *, sample_count: int = 3) -> tuple[dict | None, CronSampleCallback]:
    cron_sample_result, set_cron_sample = temp_value(key, default={})

    def on_cron_sample(payload: CronSampleHandlerPayload):
        cron_expr = payload["cron_expr"]
        cron_tz = payload.get("tz", "America/New_York")
        cron_sample = get_cron_sample(cron_expr, cron_tz, sample_count)
        set_cron_sample(cron_sample)

    return cron_sample_result, on_cron_sample


def parse_fuzzy_date(value: str | int) -> datetime | None:
    if type(value) == str:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    elif type(value) == int or type(value) == float:
        ts = int(value)
        if ts >= 1e11:
            ts /= 1000
        return datetime.fromtimestamp(ts)
    return None
