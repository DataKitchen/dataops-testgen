"""Raw SQL in Python narrows test definitions to a version, and never restates the rule.

The template guard covers `template/*.sql`. These are the queries written inline in Python,
which that guard cannot see.
"""

import ast
from pathlib import Path

import pytest

import testgen

pytestmark = pytest.mark.unit

SOURCE_ROOT = Path(testgen.__file__).parent

# A query narrowing to one suite's definitions, as opposed to reaching them by primary key.
NARROWING = ("FROM test_definitions", "UPDATE test_definitions")

# Queries reached by primary key, or deliberately spanning every version, keyed by a fragment
# that identifies the one query. The reason is the point: an entry without one is an entry
# nobody re-examined.
EXEMPT = {
    ("common/models/monitor.py", "WHERE td.id = :monitor_id"): "reads one monitor by its own id",
    ("common/source_data_service.py", "WHERE d.id = :test_definition_id"): (
        "reads one definition by its own id"
    ),
    ("common/models/test_definition.py", "tt.id AS test_type_id"): (
        "get_source_data_context reads by id, behind a scoped get()"
    ),
    ("common/models/test_suite.py", "SELECT DISTINCT test_suite_id FROM test_definitions"): (
        "an existence check before deleting a suite; a row in any version counts"
    ),
    ("common/models/test_suite.py", "DELETE FROM test_definitions"): (
        "deleting a suite must take every version with it"
    ),
    ("ui/queries/test_result_queries.py", "test_definition_id = td.id"): (
        "joins definitions by id from a run's results"
    ),
}


def _python_sources() -> list[Path]:
    return [path for path in SOURCE_ROOT.rglob("*.py") if "testing" not in path.parts]


def _string_literals(path: Path) -> list[str]:
    """Every string literal in the file, f-strings rendered whole rather than in pieces."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:  # pragma: no cover - a file that does not parse fails elsewhere
        return []
    literals, inside_fstring = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            literals.append(ast.unparse(node))
            inside_fstring.update(id(child) for child in ast.walk(node) if child is not node)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in inside_fstring
        ):
            literals.append(node.value)
    return literals


def _narrowing_sources() -> dict[str, list[str]]:
    found = {}
    for path in _python_sources():
        relative = str(path.relative_to(SOURCE_ROOT))
        hits = [
            text
            for text in _string_literals(path)
            if any(keyword in text for keyword in NARROWING)
            and not any(
                fragment in text for (source, fragment) in EXEMPT if source == relative
            )
        ]
        if hits:
            found[relative] = hits
    return found


def test_narrowing_sources_are_found():
    # Guards the scan: an empty result would make the next test vacuously pass.
    assert len(_narrowing_sources()) >= 5


def test_every_raw_query_over_definitions_resolves_a_version():
    offenders = sorted(
        relative
        for relative, hits in _narrowing_sources().items()
        if not all("resolved_for_sql" in text or "version_id" in text for text in hits)
    )

    assert offenders == [], (
        "a query written in Python that narrows test definitions to a suite but not to a "
        "version reads or writes rows from versions the caller is not working in. Offenders: "
        + ", ".join(offenders)
    )


def test_nobody_restates_the_resolution_rule():
    """`frozen_at IS NULL` is the rule's signature — it belongs only where the rule is defined."""
    offenders = sorted(
        str(path.relative_to(SOURCE_ROOT))
        for path in _python_sources()
        if path.name != "suite_version.py"
        and any("frozen_at IS NULL" in text for text in _string_literals(path))
    )

    assert offenders == [], (
        "the draft/frozen/placeholder rule has one definition, SuiteVersion.resolved_for; "
        "raw SQL interpolates resolved_for_sql rather than rewriting it. Offenders: "
        + ", ".join(offenders)
    )
