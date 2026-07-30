import math

import pytest

from testgen.common.profile_frequency import (
    build_frequent_patterns,
    build_frequent_values,
    format_frequent,
    frequent_entries,
    with_frequent_patterns,
)


def freq_row(value, value_ct, value_rank, other_distinct_ct=None, distinct_value_hash="h"):
    return {
        "value": value,
        "value_ct": value_ct,
        "value_rank": value_rank,
        "other_distinct_ct": other_distinct_ct,
        "distinct_value_hash": distinct_value_hash,
    }


def test_build_frequent_values_keeps_rank_order():
    rows = [freq_row("b", 9, 1), freq_row("a", 4, 2)]

    assert build_frequent_values(rows) == {
        "values": [{"value": "b", "ct": 9}, {"value": "a", "ct": 4}]
    }


@pytest.mark.parametrize(
    "value",
    [
        "Arkansas, USA\nLittle Rock",
        "a | b",
        "has^#^sentinel",
        "trailing space ",
        "emoji \U0001f642 astral",
    ],
)
def test_build_frequent_values_round_trips_values_that_break_a_delimited_encoding(value):
    assert build_frequent_values([freq_row(value, 1, 1)])["values"] == [{"value": value, "ct": 1}]


def test_build_frequent_values_reads_the_null_value_row_as_the_other_bucket():
    rows = [freq_row("a", 20, 1), freq_row(None, 6, 11, other_distinct_ct=6)]

    assert build_frequent_values(rows) == {
        "values": [{"value": "a", "ct": 20}],
        "other": {"distinct_ct": 6, "ct": 6},
    }


def test_build_frequent_values_omits_other_when_nothing_overflowed():
    assert "other" not in build_frequent_values([freq_row("a", 1, 1)])


def test_build_frequent_values_without_rows_is_none():
    assert build_frequent_values([]) is None


def test_build_frequent_values_drops_nul_bytes_postgres_rejects_in_json():
    assert build_frequent_values([freq_row("a\x00b", 1, 1)])["values"] == [{"value": "ab", "ct": 1}]


def pattern_row(*pairs, **extra):
    row = dict(extra)
    for slot, (value, ct) in enumerate(pairs):
        row[f"pattern_{slot}"] = value
        row[f"pattern_ct_{slot}"] = ct
    return row


def test_build_frequent_patterns_reads_the_numbered_slots():
    row = pattern_row(("AA-NN", 19), ("aaNNNN", 3))

    assert build_frequent_patterns(row) == {
        "values": [{"value": "AA-NN", "ct": 19}, {"value": "aaNNNN", "ct": 3}]
    }


def test_build_frequent_patterns_ignores_the_unfilled_trailing_slots():
    row = pattern_row(("AA-NN", 19), ("aa", 2), (None, None), (None, None), (None, None))

    assert build_frequent_patterns(row) == {
        "values": [{"value": "AA-NN", "ct": 19}, {"value": "aa", "ct": 2}]
    }


def test_build_frequent_patterns_without_slots_is_none():
    assert build_frequent_patterns({"record_ct": 5}) is None


def test_with_frequent_patterns_replaces_the_slots_with_one_field():
    row = pattern_row(("AA-NN", 2), record_ct=5, min_text="a")

    assembled = with_frequent_patterns(row)

    assert assembled == {
        "record_ct": 5,
        "min_text": "a",
        "frequent_patterns": {"values": [{"value": "AA-NN", "ct": 2}]},
    }


def test_frequent_entries_returns_value_count_pairs():
    frequent = {"values": [{"value": "a", "ct": 2}, {"value": "b", "ct": 1}]}

    assert frequent_entries(frequent) == [("a", 2), ("b", 1)]


def test_frequent_entries_of_nothing_is_empty():
    assert frequent_entries(None) == []


def test_format_frequent_renders_count_then_value():
    frequent = {"values": [{"value": "a", "ct": 2}, {"value": "b", "ct": 1}]}

    assert format_frequent(frequent) == "2 | a\n1 | b"


def test_format_frequent_renders_the_other_bucket_as_a_trailing_line():
    frequent = {"values": [{"value": "a", "ct": 20}], "other": {"distinct_ct": 6, "ct": 9}}

    assert format_frequent(frequent) == "20 | a\n9 | 6 other values"


def test_format_frequent_passes_through_the_pii_redaction_sentinel():
    assert format_frequent("[PII Redacted]") == "[PII Redacted]"


@pytest.mark.parametrize("absent", [None, math.nan])
def test_format_frequent_of_an_absent_field_is_empty(absent):
    assert format_frequent(absent) == ""
