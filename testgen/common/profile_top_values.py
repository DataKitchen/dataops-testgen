"""Parsers for the ``top_freq_values`` and ``top_patterns`` fields written by profiling.

Both fields are stored as delimited strings on ``profile_results``. This module
splits them back into structured rows; format quirks (separators, leading markers,
values containing the separator) are handled here so they only need fixing in one
place.
"""


def parse_top_freq_values(raw: str | None) -> list[tuple[str, int]]:
    """Parse ``top_freq_values`` text into ``[(value, count), ...]``.

    Stored format: ``| value | count\\n| value | count ...`` — each row begins with
    ``| ``, value and count are separated by `` | ``, rows are joined by ``\\n``.
    Uses :py:meth:`str.rpartition` so values containing `` | `` parse correctly
    (the count is always the rightmost segment).
    """
    if not raw:
        return []
    body = raw[2:] if raw.startswith("| ") else raw
    rows: list[tuple[str, int]] = []
    for part in body.split("\n| "):
        if " | " not in part:
            continue
        value, _, count = part.rpartition(" | ")
        try:
            rows.append((value.strip(), int(count.strip())))
        except ValueError:
            continue
    return rows


def parse_top_patterns(raw: str | None) -> list[tuple[str, int]]:
    """Parse ``top_patterns`` text into ``[(pattern, count), ...]``.

    Stored format: alternating ``count | pattern | count | pattern ...`` (SQL
    templates emit segments separated by `` | ``; the odd-indexed segment is the
    pattern, the even-indexed is the count).
    """
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(" | ")]
    rows: list[tuple[str, int]] = []
    for index in range(0, len(parts) - 1, 2):
        try:
            count = int(parts[index])
        except ValueError:
            continue
        pattern = parts[index + 1]
        rows.append((pattern, count))
    return rows
