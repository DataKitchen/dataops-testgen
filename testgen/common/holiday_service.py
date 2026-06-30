"""Holiday calendar utilities: resolve and validate country / financial-market holiday codes.

Holiday codes name the calendars excluded from prediction baselines — used as SARIMAX
exogenous regressors and in freshness business-time gap calculations. Each code resolves
via the ``holidays`` package as either a country (ISO code, e.g. ``US``) or a financial
market (e.g. ``NYSE``).
"""

import logging
from datetime import datetime

import holidays
import pandas as pd

LOG = logging.getLogger("testgen")


def get_holiday_dates(holiday_codes: list[str], datetime_index: pd.DatetimeIndex) -> set[datetime]:
    years = list(range(datetime_index.year.min(), datetime_index.year.max() + 1))

    holiday_dates = set()
    if holiday_codes:
        for code in holiday_codes:
            code = code.strip().upper()
            found = False

            try:
                country_holidays = holidays.country_holidays(code, years=years)
                holiday_dates.update(country_holidays.keys())
                found = True
            except NotImplementedError:
                pass # Not a valid country code

            if not found:
                try:
                    financial_holidays = holidays.financial_holidays(code, years=years)
                    holiday_dates.update(financial_holidays.keys())
                    found = True
                except NotImplementedError:
                    pass # Not a valid financial code

            if not found:
                LOG.warning(f"Holiday code '{code}' could not be resolved as a country or financial market")

    return holiday_dates


def is_supported_holiday_code(code: str) -> bool:
    """Whether a holiday code resolves to a country or financial-market calendar.

    Applies the same normalization as :func:`get_holiday_dates` (strip + upper), so a code
    that passes here is one that resolver will actually honor.
    """
    normalized = code.strip().upper()
    if not normalized:
        return False
    for resolver in (holidays.country_holidays, holidays.financial_holidays):
        try:
            resolver(normalized)
        except NotImplementedError:
            continue
        else:
            return True
    return False
