import pandas as pd


def _make_freshness_history(
    update_timestamps: list[str],
    check_interval_minutes: int = 120,
) -> pd.DataFrame:
    """Build a sawtooth freshness history from a list of update timestamps.

    Between updates, the signal grows by check_interval_minutes each step.
    At each update, the signal resets to 0.
    """
    updates = sorted(pd.Timestamp(ts) for ts in update_timestamps)
    rows: list[tuple[pd.Timestamp, float]] = []
    for i in range(len(updates) - 1):
        start = updates[i]
        end = updates[i + 1]
        # First segment starts at the exact update time with signal=0 (the update event).
        # Later segments start one check_interval after the update, with signal equal to
        # that interval — simulating the first monitoring check after the update landed.
        t = start if i == 0 else start + pd.Timedelta(minutes=check_interval_minutes)
        signal = 0.0 if i == 0 else float(check_interval_minutes)
        while t < end:
            rows.append((t, signal))
            t += pd.Timedelta(minutes=check_interval_minutes)
            signal += check_interval_minutes
        rows.append((end, 0.0))

    df = pd.DataFrame(rows, columns=["timestamp", "result_signal"])
    df = df.set_index("timestamp")
    return df
