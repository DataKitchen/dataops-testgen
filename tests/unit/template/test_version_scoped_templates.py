"""Raw SQL that narrows test definitions to a suite also narrows them to a version.

A suite can hold several versions of its definitions, so a predicate on the suite alone reads
or writes rows belonging to versions the run is not executing.
"""

from pathlib import Path

import testgen

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"

# The schema scripts own the column rather than querying through it.
EXCLUDED_DIRS = ("dbsetup", "dbupgrade")

# A template narrows to a suite either by its id or by project code plus name.
SUITE_PARAMS = (":TEST_SUITE_ID", ":TEST_SUITE")

# A template takes the version as a bound parameter where its caller knows the suite id, and as
# an interpolated resolution where it only knows the suite by name.
VERSION_MARKERS = (":VERSION_ID", "{VERSION_RESOLUTION}")


def _suite_scoped_templates() -> list[Path]:
    paths = []
    for sql_path in TEMPLATE_ROOT.rglob("*.sql"):
        relative = sql_path.relative_to(TEMPLATE_ROOT)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        body = sql_path.read_text()
        if "test_definitions" in body and any(param in body for param in SUITE_PARAMS):
            paths.append(sql_path)
    return paths


def test_suite_scoped_templates_exist():
    # Guards the scan itself: an empty list would make the next test vacuously pass.
    assert len(_suite_scoped_templates()) > 25


def test_every_suite_scoped_template_binds_the_version():
    offenders = sorted(
        str(path.relative_to(TEMPLATE_ROOT))
        for path in _suite_scoped_templates()
        if not any(marker in path.read_text() for marker in VERSION_MARKERS)
    )

    assert offenders == [], (
        "a template that narrows test definitions to a suite but not to a version reads or "
        "writes rows from versions the run is not executing. Offenders: " + ", ".join(offenders)
    )
