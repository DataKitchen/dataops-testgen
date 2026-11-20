"""Templates read a table group's tables only through the table filter placeholders.

A table group can filter each of its tables to a subset of records. A template that names a table
outside the placeholders reads every record of it, so its results disagree with the rest of the run.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

import testgen

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"

# The schema scripts query TestGen's own tables, never a table group's.
EXCLUDED_DIRS = ("dbsetup", "dbupgrade", "dbupgrade_helpers")

_QUOTE = r'(?:["`]|\{QUOTE\})'
_SCHEMA = r"\{(?:TARGET_SCHEMA|SCHEMA_NAME|DATA_SCHEMA|MATCH_SCHEMA_NAME)\}"
_TABLE = r"\{(TABLE_NAME|DATA_TABLE|MATCH_TABLE_NAME)\}"
_TABLE_REF = re.compile(
    rf"(?:\b(?:FROM|JOIN)\s+|,\s*)(?P<open>\{{(?:MATCH_)?TABLE_FILTER_OPEN\}})?"
    rf"(?:(?:{_QUOTE}?{_SCHEMA}{_QUOTE}?\.)?{_QUOTE}{_TABLE}{_QUOTE}|`{_SCHEMA}\.{_TABLE}`)",
    re.IGNORECASE,
)


def _template_texts() -> Iterator[tuple[str, str]]:
    """Yield (location, SQL text) for every SQL file and every string in a test or issue type YAML file."""
    for path in sorted(TEMPLATE_ROOT.rglob("*")):
        relative = path.relative_to(TEMPLATE_ROOT)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.suffix == ".sql":
            yield str(relative), path.read_text()
        elif path.suffix == ".yaml":
            yield from _yaml_strings(str(relative), yaml.safe_load(path.read_text()))


def _yaml_strings(location: str, node: object) -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield location, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _yaml_strings(f"{location}:{key}", value)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _yaml_strings(f"{location}[{index}]", value)


def _table_refs() -> list[tuple[str, re.Match]]:
    return [(location, match) for location, text in _template_texts() for match in _TABLE_REF.finditer(text)]


def test_table_refs_exist():
    # Guards the scan itself: an empty list would make the next tests vacuously pass.
    assert len(_table_refs()) > 1500


def test_every_table_ref_opens_a_table_filter():
    offenders = sorted({location for location, match in _table_refs() if not match.group("open")})

    assert offenders == [], (
        "a template reads a table outside {TABLE_FILTER_OPEN} ... {TABLE_FILTER_CLOSE}, so it ignores "
        "the table group's filter for it. Offenders: " + ", ".join(offenders)
    )


def test_match_tables_take_the_match_placeholders():
    offenders = sorted({
        location
        for location, match in _table_refs()
        if match.group("open") and match.group("open").startswith("{MATCH_") != ("MATCH_TABLE_NAME" in match.group(0))
    })

    assert offenders == [], "a match table takes {MATCH_TABLE_FILTER_OPEN}, and only it does: " + ", ".join(offenders)


@pytest.mark.parametrize("prefix", ["", "MATCH_"])
def test_every_table_filter_open_is_closed(prefix: str):
    offenders = sorted(
        location
        for location, text in _template_texts()
        if text.count(f"{{{prefix}TABLE_FILTER_OPEN}}")
        != text.count(f"{{{prefix}TABLE_FILTER_CLOSE}}") + text.count(f"{{{prefix}TABLE_FILTER_CLOSE_UNALIASED}}")
    )

    assert offenders == [], f"unbalanced {prefix}TABLE_FILTER placeholders: " + ", ".join(offenders)
