from testgen.common.profile_top_values import parse_top_freq_values, parse_top_patterns

# --- parse_top_freq_values ---


def test_parse_top_freq_values_three_rows():
    raw = "| Mexico | 182\n| USA | 176\n| Canada | 144"
    assert parse_top_freq_values(raw) == [("Mexico", 182), ("USA", 176), ("Canada", 144)]


def test_parse_top_freq_values_with_other_values_aggregate_row():
    # The profiling pipeline emits a synthetic "Other Values (N)" row when distinct count > 10.
    raw = "| a | 5\n| b | 4\n| Other Values (8) | 20"
    assert parse_top_freq_values(raw) == [("a", 5), ("b", 4), ("Other Values (8)", 20)]


def test_parse_top_freq_values_value_containing_separator():
    # rpartition: count is always rightmost, so a value with " | " in it parses correctly.
    raw = "| user | password | 42"
    assert parse_top_freq_values(raw) == [("user | password", 42)]


def test_parse_top_freq_values_none_input():
    assert parse_top_freq_values(None) == []


def test_parse_top_freq_values_empty_input():
    assert parse_top_freq_values("") == []


def test_parse_top_freq_values_skips_unparseable_count():
    raw = "| good | 10\n| bad | not_a_number\n| also_good | 5"
    assert parse_top_freq_values(raw) == [("good", 10), ("also_good", 5)]


def test_parse_top_freq_values_skips_rows_without_separator():
    raw = "alone\n| good | 5"
    assert parse_top_freq_values(raw) == [("good", 5)]


def test_parse_top_freq_values_trims_whitespace_around_value():
    raw = "|   spacey   | 7"
    assert parse_top_freq_values(raw) == [("spacey", 7)]


def test_parse_top_freq_values_tolerates_missing_leading_marker():
    raw = "alone | 9"
    assert parse_top_freq_values(raw) == [("alone", 9)]


# --- parse_top_patterns ---


def test_parse_top_patterns_three_pairs():
    raw = "326 | Aaaaaa | 176 | AAA | 50 | aaa"
    assert parse_top_patterns(raw) == [("Aaaaaa", 326), ("AAA", 176), ("aaa", 50)]


def test_parse_top_patterns_email_shape():
    raw = "200 | aaa@aaa.aaa"
    assert parse_top_patterns(raw) == [("aaa@aaa.aaa", 200)]


def test_parse_top_patterns_none_input():
    assert parse_top_patterns(None) == []


def test_parse_top_patterns_empty_input():
    assert parse_top_patterns("") == []


def test_parse_top_patterns_skips_pair_with_unparseable_count():
    raw = "10 | good | xx | bad | 5 | also_good"
    assert parse_top_patterns(raw) == [("good", 10), ("also_good", 5)]


def test_parse_top_patterns_dangling_odd_segment_ignored():
    # An odd number of segments — the trailing count without a pattern is dropped.
    raw = "10 | Aaa | 99"
    assert parse_top_patterns(raw) == [("Aaa", 10)]


def test_parse_top_patterns_trims_pattern_whitespace():
    raw = "5 |   NNNN-NN-NN  "
    assert parse_top_patterns(raw) == [("NNNN-NN-NN", 5)]
