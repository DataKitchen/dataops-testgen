from collections.abc import Callable
from typing import TypedDict

from testgen.common.cron_service import get_cron_sample
from testgen.ui.session import temp_value


class CronSampleHandlerPayload(TypedDict):
    tz: str
    cron_expr: str


CronSampleCallback = Callable[[CronSampleHandlerPayload], None]


def get_cron_sample_handler(key: str, *, sample_count: int = 3) -> tuple[dict | None, CronSampleCallback]:
    cron_sample_result, set_cron_sample = temp_value(key, default={})

    def on_cron_sample(payload: CronSampleHandlerPayload):
        cron_expr = payload["cron_expr"]
        cron_tz = payload.get("tz", "America/New_York")
        cron_sample = get_cron_sample(cron_expr, cron_tz, sample_count, formatted=True)
        set_cron_sample(cron_sample)

    return cron_sample_result, on_cron_sample
