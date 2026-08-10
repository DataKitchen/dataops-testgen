"""Generation-set names: lookup, membership, and selection policy.

Shared by ``run_test_generation``, the Generate Tests dialog, the REST API, the MCP
tools, and the CLI so every entry point applies the same validation and defaulting.
Raises stdlib exceptions — the MCP, API, and CLI layers translate those into their
own user-facing errors.

Set names are read from the ``generation_sets`` table at runtime and never enumerated
here: plugins contribute their own sets, and their names must not appear in this
package. ``Standard`` and ``Monitor`` are the two names this package owns.
"""

from sqlalchemy import text

from testgen.common.models import get_current_session
from testgen.common.models.test_suite import TestSuite

MONITOR_GENERATION_SET = "Monitor"
DEFAULT_GENERATION_SET = "Standard"


def list_generation_sets(*, include_monitor: bool = False) -> list[str]:
    """Every generation set defined in the database, alphabetically."""
    rows = get_current_session().execute(
        text("SELECT DISTINCT generation_set FROM generation_sets ORDER BY generation_set")
    ).all()
    names = [row[0] for row in rows]
    if include_monitor:
        return names
    return [name for name in names if name != MONITOR_GENERATION_SET]


def get_generation_set_members() -> dict[str, list[str]]:
    """Map each selectable generation set to the test types it generates."""
    rows = get_current_session().execute(
        text(
            "SELECT generation_set, test_type FROM generation_sets "
            "WHERE generation_set <> :monitor "
            "ORDER BY generation_set, test_type"
        ),
        {"monitor": MONITOR_GENERATION_SET},
    ).all()

    members: dict[str, list[str]] = {}
    for generation_set, test_type in rows:
        members.setdefault(generation_set, []).append(test_type)
    return members


def resolve_generation_sets(test_suite: TestSuite, requested: list[str] | None) -> list[str]:
    """Resolve the generation sets a run should use.

    ``None`` means the caller did not ask, and falls back to the suite's stored sets
    and then to ``Standard``. An empty list means the caller asked for nothing, which
    is an error: an unmatched set generates no test types, and the stale-delete would
    then remove every unlocked auto-generated test in the suite.
    """
    available = list_generation_sets()

    if requested is not None:
        if isinstance(requested, str):
            raise TypeError("generation_sets must be a list of generation set names, not a string.")

        if not requested:
            raise ValueError("At least one generation set is required.")

        if MONITOR_GENERATION_SET in requested:
            raise ValueError(
                f"'{MONITOR_GENERATION_SET}' cannot be used for a regular test suite. "
                f"Available generation sets: {', '.join(available)}."
            )

        if unknown := sorted({name for name in requested if name not in available}):
            raise ValueError(
                f"Unknown generation sets: {', '.join(unknown)}. "
                f"Available generation sets: {', '.join(available)}."
            )

        return list(dict.fromkeys(requested))

    stored = [name for name in (test_suite.generation_sets or []) if name in available]
    return stored or [DEFAULT_GENERATION_SET]
