import math
from uuid import UUID

import pandas as pd


def to_int(value: float | int) -> int:
    if pd.notnull(value):
        return int(value)
    return 0


def truncate(value: float) -> int:
    if 0 < value < 1:
        return 1
    return math.trunc(value)


def is_uuid4(value: str) -> bool:
    try:
        uuid = UUID(value, version=4)
    except Exception:
        return False
    
    return str(uuid) == value
