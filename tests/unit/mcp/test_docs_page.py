"""The supported-tools page carries one bullet per entry, built from its docstring.

Only the opening sentence reaches the page, so this pins the extraction rule: entries stay
scannable without any docstring having to be laid out a particular way.
"""

import pytest

from deploy.build_mcp_docs import _short_description


@pytest.mark.unit
@pytest.mark.parametrize(
    ("docstring", "expected"),
    [
        pytest.param("One sentence only.", "One sentence only.", id="single-sentence"),
        pytest.param("First. Second sentence here.", "First.", id="stops-at-first-sentence"),
        pytest.param(
            "Summary line.\n    Detail continuing the same paragraph.",
            "Summary line.",
            id="stops-before-wrapped-detail",
        ),
        pytest.param("Summary.\n\n    Second paragraph.", "Summary.", id="excludes-later-paragraphs"),
        pytest.param("Uses ``list_test_runs``. Detail.", "Uses ``list_test_runs``.", id="keeps-code-references"),
        pytest.param("", "", id="empty"),
    ],
)
def test_short_description_returns_the_opening_sentence(docstring: str, expected: str) -> None:
    assert _short_description(docstring) == expected


@pytest.mark.unit
@pytest.mark.parametrize("abbreviation", ["e.g.", "i.e.", "etc.", "vs.", "approx."])
def test_abbreviations_do_not_end_the_sentence(abbreviation: str) -> None:
    """A period closing an abbreviation would otherwise truncate the summary mid-sentence."""
    docstring = f"Accepts a value, {abbreviation} the one shown, and returns it. Further detail."

    assert _short_description(docstring) == f"Accepts a value, {abbreviation} the one shown, and returns it."


@pytest.mark.unit
def test_summary_without_a_closing_period_falls_back_to_the_paragraph() -> None:
    """The paragraph bound keeps a period-less summary from absorbing later prose."""
    docstring = "Summary with no closing period\n\n    Second paragraph."

    assert _short_description(docstring) == "Summary with no closing period"
