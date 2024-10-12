import pandas as pd


def to_int(value: float | int) -> int:
    if pd.notnull(value):
        return int(value)
    return 0
