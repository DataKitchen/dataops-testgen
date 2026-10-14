"""Reference implementation of the value hashes profiling and the comparison tests compute in SQL.

Every flavor's SQL must produce exactly these values for the same data.
"""

import calendar
import hashlib
import math
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Context, Decimal

# Test types generated only from a profile that computed value hashes
VALUE_HASH_TEST_TYPES = frozenset({
    "Match_Hash_Text",
    "Match_Hash_Num",
    "Match_Hash_Date",
    "Match_Keyed_Hash_Text",
    "Match_Keyed_Hash_Num",
    "Match_Keyed_Hash_Date",
    "Match_Epoch_Sum",
})

# The least magnitude whose canonical number, rounded to six places, reaches 10^32
DECIMAL_BOUND = Decimal("99999999999999999999999999999999.9999995")


def canonical_text(value: str | int | Decimal | float | date | datetime) -> str:
    """Return a value's canonical text: text as is; a number rounded half away from zero to six
    decimal places, times 10^6, as integer text, a float first rounded to nine places; a date or
    timestamp as ``YYYY-MM-DD HH:MM:SS`` in UTC, truncated.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise TypeError("bool values are not hashed")
    if isinstance(value, int | Decimal | float):
        number = Decimal(value)
        if isinstance(value, float):
            number = number.quantize(Decimal("1e-9"), context=_WIDE)
        return str(int(number.quantize(Decimal("1e-6"), context=_WIDE).scaleb(6, context=_WIDE)))
    wall_clock = _utc_wall_clock(value)
    # Formatted by hand: strftime does not zero-pad years below 1000 on every platform
    return f"{wall_clock.year:04d}-{wall_clock:%m-%d %H:%M:%S}"


def is_hashable(value: object) -> bool:
    """Whether a value contributes to the hashes: not NULL, and a number only when finite and below
    10^29 in magnitude for a float, and for another number when it rounds to six places below 10^32."""
    if value is None:
        return False
    if isinstance(value, float):
        return math.isfinite(value) and abs(value) < 1e29
    if isinstance(value, Decimal):
        return value.is_finite() and value.copy_abs() < DECIMAL_BOUND
    if isinstance(value, int) and not isinstance(value, bool):
        return abs(value) < 10**32
    return True


def hash_integer(text: str) -> int:
    """Return the first 56 bits of the MD5 of a text's UTF-8 bytes."""
    return int(_md5_hex(text)[:14], 16)


def multiset_hash(values: Iterable) -> int | None:
    """Return the sum of the hashes of the non-null values, or None when there are none."""
    hashes = [hash_integer(canonical_text(value)) for value in values if is_hashable(value)]
    return sum(hashes) if hashes else None


def keyed_hash(rows: Iterable[tuple]) -> int | None:
    """Return the keyed hash of ``(key, value)`` rows: the sum over rows with a value of the hash of
    the MD5 hex of the key's canonical text followed by the MD5 hex of the value's.
    """
    hashes = [
        hash_integer(_md5_hex(canonical_text(key)) + _md5_hex(canonical_text(value)))
        for key, value in rows
        if is_hashable(value) and is_hashable(key)
    ]
    return sum(hashes) if hashes else None


def epoch_sum(values: Iterable[date | datetime]) -> int | None:
    """Return the sum of the non-null dates as whole seconds since 1970-01-01 UTC, or None when there are none."""
    seconds = [calendar.timegm(_utc_wall_clock(value).timetuple()) for value in values if value is not None]
    return sum(seconds) if seconds else None


_WIDE = Context(prec=80, rounding=ROUND_HALF_UP)


def _md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def _utc_wall_clock(value: date | datetime) -> datetime:
    if not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value
