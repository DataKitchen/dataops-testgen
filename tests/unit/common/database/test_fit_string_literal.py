import pytest

from testgen.common.database.database_service import get_flavor_service

pytestmark = pytest.mark.unit


def test_oracle_cuts_a_literal_to_the_length_it_accepts():
    """ORA-01704 rejects a string literal over 4,000 bytes, whatever the column it is written to
    holds, so the text has to be cut before it reaches the query."""
    assert len(get_flavor_service("oracle").fit_string_literal("a" * 5000)) == 4000


def test_a_cut_literal_says_it_was_cut():
    assert get_flavor_service("oracle").fit_string_literal("a" * 5000).endswith("...")


@pytest.mark.parametrize("length", [1, 3997, 4000])
def test_oracle_leaves_a_literal_it_accepts_whole(length):
    value = "a" * length
    assert get_flavor_service("oracle").fit_string_literal(value) == value


@pytest.mark.parametrize("flavor", ["postgresql", "bigquery", "snowflake", "mssql"])
def test_a_flavor_that_caps_nothing_leaves_every_literal_whole(flavor):
    value = "a" * 50_000
    assert get_flavor_service(flavor).fit_string_literal(value) == value


def test_a_cut_counts_bytes_rather_than_characters():
    """The cap is on the encoded length, and a cut landing inside a character drops it whole
    rather than writing half of one into the query."""
    cut = get_flavor_service("oracle").fit_string_literal("é" * 5000)

    assert len(cut.encode()) <= 4000
    assert "�" not in cut


def test_a_cut_never_leaves_a_backslash_escaping_the_marker():
    """Where the flavor reads a backslash as an escape the text reaches here with its backslashes
    already doubled, and a cut through a pair would leave one escaping what follows."""
    cut = get_flavor_service("oracle").fit_string_literal("\\\\" * 3000)

    assert (len(cut) - len(cut.rstrip("\\"))) % 2 == 0
