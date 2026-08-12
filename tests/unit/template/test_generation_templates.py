"""Guards on the generation templates as a whole, not on any single test type."""

from pathlib import Path

import testgen

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"

# Directories holding the per-test-type generation templates plus the shared
# selection template. get_test_types.sql is the one intentional exception: it is
# where the generation-set filter belongs.
GENERATION_DIRS = ("generation", "gen_query_tests", "gen_funny_cat_tests")


def _generation_templates() -> list[Path]:
    paths = []
    for sql_path in TEMPLATE_ROOT.rglob("*.sql"):
        parts = sql_path.relative_to(TEMPLATE_ROOT).parts
        if any(part in GENERATION_DIRS for part in parts):
            paths.append(sql_path)
    return paths


def test_generation_templates_exist():
    # Guards the glob itself: an empty list would make the next test vacuously pass.
    assert len(_generation_templates()) > 20


def test_only_get_test_types_filters_by_generation_set():
    offenders = sorted(
        str(path.relative_to(TEMPLATE_ROOT))
        for path in _generation_templates()
        if path.name != "get_test_types.sql" and "generation_sets" in path.read_text()
    )

    assert offenders == [], (
        "get_test_types.sql already filters by generation set; a per-template guard is "
        "redundant and drifts. Offenders: " + ", ".join(offenders)
    )
