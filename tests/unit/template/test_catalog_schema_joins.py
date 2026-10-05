"""Nothing joins the catalog on its schema.

``data_table_chars`` / ``data_column_chars`` hold one row per table, and that row's ``schema_name``
records whichever schema was last refreshed. Every other table keeps the schema it was written
against: profiling rows never move, a run's results keep the schema that run targeted, and stored
test definitions keep the one they were generated for. Matching the catalog on schema as well as on
identity therefore stops finding rows the moment a run targets somewhere else -- silently, since a
missing row and no data are indistinguishable.

Comparing two schema columns is not wrong in itself: two profiling-derived tables agree by
construction. So this takes an inventory rather than guessing which side is the catalog. Every
comparison in the package is counted and has to be accounted for below with the reason it is safe,
and anything unaccounted for fails. Adding one to an accounted file fails too, so a new join cannot
ride in under an existing entry.
"""

import re
from pathlib import Path

import pytest

import testgen

pytestmark = pytest.mark.unit

PACKAGE_ROOT = Path(testgen.__file__).parent

# Collapsing whitespace first so a predicate split over several lines is still seen.
COMPARISON = re.compile(r"[\w.]+\.schema_name\s*==?\s*[\w.]+\.schema_name")

ACCOUNTED: dict[str, tuple[int, str]] = {
    "common/models/hygiene_issue.py": (4, "hygiene issues to profiling results, and to each other"),
    "common/models/profile_result.py": (1, "hygiene issues to profiling results"),
    "common/models/profiling_run.py": (1, "hygiene issues to profiling results"),
    "template/dbupgrade/0169_incremental_upgrade.sql": (1, "test results to test definitions; applied, immutable"),
    "template/gen_funny_cat_tests/gen_Constant.sql": (1, "two profiling-derived CTEs"),
    "template/gen_funny_cat_tests/gen_Distinct_Value_Ct.sql": (1, "two profiling-derived CTEs"),
    "template/generation/delete_overridden_autogen_tests.sql": (1, "test definitions to test definitions"),
    "template/get_entities/get_profile_screen.sql": (3, "profiling results to a profiling-derived CTE"),
    "template/profiling/functional_tabletype_stage.sql": (1, "profiling results to a profiling-derived subquery"),
    "template/profiling/functional_tabletype_update.sql": (1, "staging to profiling results, same run"),
    "template/profiling/profile_anomalies_screen_column.sql": (1, "profiling results to muted hygiene issues"),
    "template/profiling/profile_anomalies_screen_multi_column.sql": (2, "profiling results to muted hygiene issues"),
    "template/profiling/profile_anomalies_screen_table.sql": (1, "profiling results to muted hygiene issues"),
    "template/profiling/profile_anomalies_screen_table_dates.sql": (1, "profiling results to muted hygiene issues"),
    "template/profiling/profile_anomalies_screen_variants.sql": (1, "profiling results to muted hygiene issues"),
}


def _sources() -> list[tuple[str, Path]]:
    found = sorted(PACKAGE_ROOT.rglob("*.sql")) + sorted(PACKAGE_ROOT.rglob("*.py"))
    return [
        (str(p.relative_to(PACKAGE_ROOT)), p) for p in found if "__pycache__" not in str(p)
    ]


def _count(path: Path) -> int:
    return len(COMPARISON.findall(re.sub(r"\s+", " ", path.read_text(errors="ignore"))))


@pytest.mark.parametrize("relative,path", _sources(), ids=lambda v: v if isinstance(v, str) else "")
def test_schema_comparisons_are_accounted_for(relative, path):
    found = _count(path)
    expected, _reason = ACCOUNTED.get(relative, (0, ""))

    assert found == expected, (
        f"{relative} compares schema to schema {found} time(s), accounted for {expected}. "
        "A join that matches the catalog on schema stops finding rows once a run targets another "
        "schema; if this one is safe, add it to ACCOUNTED with the reason."
    )


def test_every_accounted_file_still_exists():
    """An entry left behind after a file moves would silently account for nothing."""
    missing = [entry for entry in ACCOUNTED if not (PACKAGE_ROOT / entry).exists()]

    assert not missing, f"accounted files no longer exist: {missing}"
