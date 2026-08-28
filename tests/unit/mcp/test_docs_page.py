"""The supported-tools page carries one bullet per entry, built from its docstring.

Only the opening sentence reaches the page, so this pins the extraction rule: entries stay
scannable without any docstring having to be laid out a particular way. Plugin labelling is
pinned alongside it, since the page mixes core and plugin entries in the same groups.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deploy.build_mcp_docs import _build_markdown, _inspect_plugins, _render_entry, _short_description
from testgen.utils.plugins import Plugin, PluginSpec


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


def _tool(name: str):
    def fn():
        """Does a thing."""

    fn.__name__ = name
    return fn


def _spec(tools: list, label: str | None = "[label]") -> type[PluginSpec]:
    class APlugin(PluginSpec):
        @classmethod
        def get_mcp_tools(cls):
            return tools

        @classmethod
        def get_doc_label(cls):
            return label

    return APlugin


def _discovers(package: str = "testgen_a_plugin"):
    return patch("deploy.build_mcp_docs.discover", return_value=[Plugin(package=package, version="1.0.0")])


@pytest.mark.unit
def test_inspect_plugins_reports_the_label_and_contributed_tools():
    with _discovers(), patch.object(Plugin, "load", return_value=_spec([_tool("a_tool")])):
        labels, tool_names = _inspect_plugins()

    assert labels == {"testgen_a_plugin": "[label]"}
    assert tool_names == {"a_tool"}


@pytest.mark.unit
def test_inspect_plugins_rejects_a_plugin_that_fails_to_load():
    with _discovers(), patch.object(Plugin, "load", side_effect=ImportError("shadowed by /site-packages/x")):
        with pytest.raises(RuntimeError, match="testgen_a_plugin"):
            _inspect_plugins()


@pytest.mark.unit
def test_inspect_plugins_rejects_a_plugin_that_exposes_no_spec():
    """A spec-less plugin contributes nothing, which is indistinguishable from having nothing to give."""
    with _discovers(), patch.object(Plugin, "load", return_value=PluginSpec):
        with pytest.raises(RuntimeError, match="exposes no PluginSpec"):
            _inspect_plugins()


@pytest.mark.unit
def test_build_markdown_rejects_a_contributed_tool_that_never_registered():
    """A tool can be dropped between the plugin handing it over and the server registering it."""
    mcp = SimpleNamespace(
        _tool_manager=SimpleNamespace(list_tools=lambda: []),
        _resource_manager=SimpleNamespace(list_resources=lambda: []),
        _prompt_manager=SimpleNamespace(list_prompts=lambda: []),
    )

    with _discovers(), patch.object(Plugin, "load", return_value=_spec([_tool("a_tool")])):
        with pytest.raises(RuntimeError, match="a_tool"):
            _build_markdown(mcp)
