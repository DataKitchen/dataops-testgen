"""The supported-tools page carries one bullet per entry, built from its docstring.

Only the opening sentence reaches the page, so this pins the extraction rule: entries stay
scannable without any docstring having to be laid out a particular way. Plugin labelling is
pinned alongside it, since the page mixes core and plugin entries in the same groups.
"""

from types import SimpleNamespace

import pytest

from deploy.build_mcp_docs import _render_entry, _short_description


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


_LABELS = {"testgen_a_plugin": "[label]"}


def _entry(module: str) -> SimpleNamespace:
    return SimpleNamespace(name="a_tool", description="Does a thing.", fn=SimpleNamespace(__module__=module))


@pytest.mark.unit
def test_core_entry_is_unlabelled() -> None:
    assert _render_entry(_entry("testgen.mcp.tools.projects"), _LABELS) == "- **`a_tool`** — Does a thing."


@pytest.mark.unit
def test_entry_carries_its_plugin_label() -> None:
    """The originating package is the only signal — an entry declares nothing about itself."""
    assert _render_entry(_entry("testgen_a_plugin.mcp.members"), _LABELS) == "- **`a_tool`** — Does a thing. [label]"


@pytest.mark.unit
def test_entry_from_a_plugin_that_declares_no_label_is_unlabelled() -> None:
    assert _render_entry(_entry("testgen_b_plugin.mcp.things"), _LABELS) == "- **`a_tool`** — Does a thing."


@pytest.mark.unit
def test_entry_without_a_function_is_unlabelled() -> None:
    """Resources are addressed by URI and expose no function to attribute to a package."""
    resource = SimpleNamespace(uri="testgen://glossary", name="glossary", description="Glossary.")

    assert _render_entry(resource, _LABELS) == "- **`testgen://glossary`** — Glossary."
