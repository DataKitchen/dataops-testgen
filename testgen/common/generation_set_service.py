"""Generation-set names: lookup, membership, and selection policy.

Shared by ``run_test_generation``, the Generate Tests dialog, the REST API, the MCP
tools, and the CLI so every entry point applies the same validation and defaulting.
Raises stdlib exceptions — the MCP, API, and CLI layers translate those into their
own user-facing errors.

Set names are read from the ``generation_sets`` table at runtime and never enumerated
here: plugins contribute their own sets, and their names must not appear in this
package. ``Standard``, ``Table Comparison``, ``Monitor``, and ``Contract`` are the names this
package owns, and ``GENERATION_SET_DESCRIPTIONS`` describes the ones a user picks; a plugin
describes its own sets through ``PluginSpec.get_generation_set_descriptions``.
"""

from sqlalchemy import text

from testgen.common.enums import SuiteType
from testgen.common.models import get_current_session
from testgen.common.models.test_suite import TestSuite

MONITOR_GENERATION_SET = "Monitor"
CONTRACT_GENERATION_SET = "Contract"
DEFAULT_GENERATION_SET = "Standard"
TABLE_COMPARISON_GENERATION_SET = "Table Comparison"

GENERATION_SET_DESCRIPTIONS: dict[str, str] = {
    DEFAULT_GENERATION_SET: (
        "General-purpose tests for every table: completeness, uniqueness, formats, value ranges, and recency."
    ),
    TABLE_COMPARISON_GENERATION_SET: (
        "Tests that each column's counts, sums, extremes, hashes, and frequent values equal their baseline, "
        "to confirm a table still matches its source after a copy or a migration."
    ),
    CONTRACT_GENERATION_SET: (
        "The tests a data contract states: required columns, uniqueness, allowed values and patterns, "
        "minimums, recency, and row counts."
    ),
}


_CORE_SET_ORDER = (CONTRACT_GENERATION_SET, DEFAULT_GENERATION_SET, TABLE_COMPARISON_GENERATION_SET)


def order_generation_sets(names: list[str]) -> list[str]:
    """``names`` in the order a user picks from: ``Contract``, ``Standard``, and ``Table Comparison``
    first, then every other set alphabetically."""
    return sorted(
        names,
        key=lambda name: (_CORE_SET_ORDER.index(name), "") if name in _CORE_SET_ORDER else (len(_CORE_SET_ORDER), name),
    )


def list_generation_sets(*, include_monitor: bool = False, include_contract: bool = False) -> list[str]:
    """Every generation set defined in the database, alphabetically.

    ``Contract`` is excluded unless ``include_contract``: only a contract suite may use it.
    """
    rows = get_current_session().execute(
        text("SELECT DISTINCT generation_set FROM generation_sets ORDER BY generation_set")
    ).all()
    names = [row[0] for row in rows]
    excluded = set()
    if not include_contract:
        excluded.add(CONTRACT_GENERATION_SET)
    if not include_monitor:
        excluded.add(MONITOR_GENERATION_SET)
    return [name for name in names if name not in excluded]


def available_generation_sets(test_suite: TestSuite) -> list[str]:
    """The generation sets ``test_suite`` may use: ``Contract`` too for a contract suite."""
    return list_generation_sets(include_contract=test_suite.suite_type == SuiteType.CONTRACT)


def get_generation_set_members(*, include_contract: bool = False) -> dict[str, list[str]]:
    """Map each selectable generation set to the test types it generates, ``Contract`` only when asked."""
    excluded = [MONITOR_GENERATION_SET] if include_contract else [MONITOR_GENERATION_SET, CONTRACT_GENERATION_SET]
    rows = get_current_session().execute(
        text(
            "SELECT generation_set, test_type FROM generation_sets "
            "WHERE NOT (generation_set = ANY(:excluded)) "
            "ORDER BY generation_set, test_type"
        ),
        {"excluded": excluded},
    ).all()

    members: dict[str, list[str]] = {}
    for generation_set, test_type in rows:
        members.setdefault(generation_set, []).append(test_type)
    return members


def get_generation_set_test_types(generation_set: str) -> list[str]:
    """The test types one generation set generates, the Monitor and Contract sets included."""
    return list(
        get_current_session().scalars(
            text("SELECT test_type FROM generation_sets WHERE generation_set = :generation_set ORDER BY test_type"),
            {"generation_set": generation_set},
        )
    )


def get_overriding_test_types() -> dict[str, list[str]]:
    """Map each overridden test type to the active test types that override it.

    Generation deletes an unlocked auto-generated test when an overriding test type
    generates on the same column in the same run, so a test type can be dropped from a
    suite even while its own generation set stays selected.
    """
    rows = get_current_session().execute(
        text(
            "SELECT overrides, test_type FROM test_types "
            "WHERE overrides IS NOT NULL AND active = 'Y' "
            "ORDER BY overrides, test_type"
        )
    ).all()

    overriding: dict[str, list[str]] = {}
    for overridden_type, overriding_type in rows:
        overriding.setdefault(overridden_type, []).append(overriding_type)
    return overriding


def resolve_generation_sets(test_suite: TestSuite, requested: list[str] | None) -> list[str]:
    """Resolve the generation sets a run should use.

    ``None`` means the caller did not ask, and falls back to the suite's stored sets
    and then to the default: ``Contract`` for a contract suite, ``Standard`` for any other.
    An empty list means the caller asked for nothing, which is an error: an unmatched set
    generates no test types, and the stale-delete would then remove every unlocked
    auto-generated test in the suite.

    Only a contract suite may use ``Contract``, and no suite may use ``Monitor``.
    """
    is_contract = test_suite.suite_type == SuiteType.CONTRACT
    available = available_generation_sets(test_suite)
    default = CONTRACT_GENERATION_SET if is_contract else DEFAULT_GENERATION_SET

    if requested is not None:
        if isinstance(requested, str):
            raise TypeError("generation_sets must be a list of generation set names, not a string.")

        if not requested:
            raise ValueError("At least one generation set is required.")

        if CONTRACT_GENERATION_SET in requested and not is_contract:
            raise ValueError(
                f"'{CONTRACT_GENERATION_SET}' can only be used for a contract. "
                f"Available generation sets: {', '.join(available)}."
            )

        if MONITOR_GENERATION_SET in requested:
            raise ValueError(
                f"'{MONITOR_GENERATION_SET}' is reserved for monitor suites. "
                f"Available generation sets: {', '.join(available)}."
            )

        if unknown := sorted({name for name in requested if name not in available}):
            raise ValueError(
                f"Unknown generation sets: {', '.join(unknown)}. "
                f"Available generation sets: {', '.join(available)}."
            )

        return list(dict.fromkeys(requested))

    stored = [name for name in (test_suite.generation_sets or []) if name in available]
    return stored or [default]
