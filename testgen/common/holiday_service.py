"""Holiday calendar utilities: resolve and validate country / financial-market holiday codes.

Holiday codes name the calendars excluded from prediction baselines — used as SARIMAX
exogenous regressors and in freshness business-time gap calculations. Each code resolves
via the ``holidays`` package as either a country (ISO code, e.g. ``US``) or a financial
market (MIC, e.g. ``XNYS``).
"""

import logging
import re
from datetime import datetime

import holidays
import pandas as pd
from holidays import registry

LOG = logging.getLogger("testgen")

# Codes surfaced at the top of the calendar picker, ahead of the alphabetical list.
_PINNED_HOLIDAY_CODES = ("US", "XNYS")


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


def list_holiday_calendars() -> list[dict[str, str]]:
    """Selectable holiday calendars as ``{"label", "value"}``, pinned entries first then alphabetical.

    ``label`` is the display name; ``value`` is the code :func:`get_holiday_dates` resolves (an ISO
    alpha-2 country code or a market MIC). Sourced from the ``holidays`` package registry so the
    options always match the codes the resolver honors.
    """
    labels_by_code = {
        entity[1]: _calendar_label(entity[0])
        for entity in (*registry.COUNTRIES.values(), *registry.FINANCIAL.values())
    }
    pinned = [
        {"value": code, "label": labels_by_code[code]}
        for code in _PINNED_HOLIDAY_CODES
        if code in labels_by_code
    ]
    rest = sorted(
        (
            {"value": code, "label": label}
            for code, label in labels_by_code.items()
            if code not in _PINNED_HOLIDAY_CODES
        ),
        key=lambda calendar: calendar["label"].lower(),
    )
    return [*pinned, *rest]


def _calendar_label(camel_case_name: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", camel_case_name)
    return re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)


def list_market_holiday_codes() -> list[str]:
    """Canonical MICs for every financial-market calendar in the registry, alphabetically."""
    return sorted(entity[1] for entity in registry.FINANCIAL.values())


# Every representation the holidays package accepts (display name, ISO codes, market aliases),
# upper-cased, mapped to the canonical code the picker and stored data use.
_CANONICAL_BY_CODE = {
    representation.upper(): entity[1]
    for entity in (*registry.COUNTRIES.values(), *registry.FINANCIAL.values())
    for representation in (entity[0], *entity[1:])
}


def canonicalize_holiday_code(code: str) -> str:
    """Return the canonical code (ISO alpha-2 / market MIC) for a holiday code, name, or alias.

    Applies the same normalization as :func:`is_supported_holiday_code`. Unrecognized input is
    returned upper-cased and otherwise unchanged.
    """
    normalized = code.strip().upper()
    return _CANONICAL_BY_CODE.get(normalized, normalized)
