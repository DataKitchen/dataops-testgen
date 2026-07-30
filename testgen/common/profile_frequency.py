"""Assembly of the frequency analysis fields on ``profile_results``.

``frequent_values`` and ``frequent_patterns`` share one JSON shape::

    {"values": [{"value": "Arkansas, USA", "ct": 452}, ...],
     "other": {"distinct_ct": 37, "ct": 119}}

``values`` is ordered most frequent first. ``other`` summarizes the values past the
end of ``values`` and is present only on ``frequent_values``, only when the column
held more distinct values than the flavor query returns.

Frequency analysis returns one row per value, so it is assembled from a row sequence.
Pattern analysis rides along on the wide per-column result under numbered slot fields,
so it is assembled from that single row.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

LOG = logging.getLogger("testgen")

PATTERN_SLOTS = 5
"""Number of pattern slots the wide per-column query carries."""

PATTERN_SLOT_PREFIX = "pattern_"


def _json_text(value: object) -> str:
    # PostgreSQL rejects NUL bytes inside JSON strings, as it does in text.
    return str(value).replace("\x00", "")


def build_frequent_values(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Assemble the frequency analysis result set into ``frequent_values``.

    Expects the rows in rank order, each carrying ``value``, ``value_ct`` and
    ``other_distinct_ct``. The row with a NULL ``value`` summarizes the values past
    the ones returned individually and becomes the ``other`` key.
    """
    if not rows:
        return None

    frequent: dict[str, Any] = {
        "values": [
            {"value": _json_text(row["value"]), "ct": int(row["value_ct"])}
            for row in rows
            if row["value"] is not None
        ]
    }

    if other := next((row for row in rows if row["value"] is None), None):
        frequent["other"] = {"distinct_ct": int(other["other_distinct_ct"]), "ct": int(other["value_ct"])}

    return frequent


def build_frequent_patterns(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Assemble the pattern slots on a wide per-column result into ``frequent_patterns``.

    Slots are numbered from 0 in rank order; empty slots carry no entry.
    """
    values = []
    for slot in range(PATTERN_SLOTS):
        pattern = row.get(f"{PATTERN_SLOT_PREFIX}{slot}")
        count = row.get(f"{PATTERN_SLOT_PREFIX}ct_{slot}")
        if pattern is None and count is None:
            continue
        # A slot carries a pattern and its count together. Half a slot means the two were
        # read separately, so the pair cannot be trusted and neither half is kept.
        if pattern is None or count is None:
            LOG.warning(
                "Discarding pattern slot %s for %s.%s: pattern=%r count=%r",
                slot,
                row.get("table_name"),
                row.get("column_name"),
                pattern,
                count,
            )
            continue
        values.append({"value": _json_text(pattern), "ct": int(count)})
    return {"values": values} if values else None


def frequent_entries(frequent: Mapping[str, Any] | None) -> list[tuple[str, int]]:
    """Return the entries of a frequency analysis field as ``[(value, count), ...]``."""
    if not frequent:
        return []
    return [(entry["value"], entry["ct"]) for entry in frequent.get("values", ())]


def format_frequent(frequent: Mapping[str, Any] | str | None) -> str:
    """Render a frequency analysis field as one ``count | value`` line per entry.

    A field carrying the PII redaction sentinel is passed through, since masking replaces
    the whole value with a string.
    """
    if isinstance(frequent, str):
        return frequent
    # A DataFrame column holds NaN rather than None where the field is absent.
    if not isinstance(frequent, Mapping):
        return ""

    lines = [f"{count} | {value}" for value, count in frequent_entries(frequent)]
    if other := frequent.get("other"):
        lines.append(f"{other['ct']} | {other['distinct_ct']} other values")
    return "\n".join(lines)


def with_frequent_patterns(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a wide per-column result with its pattern slots assembled into one field."""
    assembled = {column: value for column, value in row.items() if not column.startswith(PATTERN_SLOT_PREFIX)}
    assembled["frequent_patterns"] = build_frequent_patterns(row)
    return assembled
