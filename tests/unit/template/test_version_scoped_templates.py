"""Raw SQL that narrows test definitions to a suite also narrows them to a version.

A suite can hold several versions of its definitions, so a predicate on the suite alone reads
or writes rows belonging to versions the run is not executing.
"""

import re
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


# A write is where an unscoped predicate does damage rather than merely reading too much, so
# these are checked one statement at a time: a file-level scan is satisfied by any one
# statement binding the version, on behalf of every other statement in the same file.
_WRITES_DEFINITIONS = re.compile(
    r"\b(UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+test_definitions\b", re.IGNORECASE
)
_LINE_COMMENT = re.compile(r"--[^\n]*")


def _statements(body: str) -> list[str]:
    """The template's statements. Comments are stripped first so a ';' inside one cannot split."""
    return [
        statement
        for statement in _LINE_COMMENT.sub("", body).split(";")
        if statement.strip()
    ]


def test_every_statement_that_writes_definitions_binds_the_version():
    offenders = []
    for path in _suite_scoped_templates():
        for index, statement in enumerate(_statements(path.read_text()), start=1):
            if not _WRITES_DEFINITIONS.search(statement):
                continue
            if any(marker in statement for marker in VERSION_MARKERS):
                continue
            offenders.append(f"{path.relative_to(TEMPLATE_ROOT)} statement {index}")

    assert offenders == [], (
        "a statement that writes test definitions without narrowing to a version reaches rows "
        "on versions the run is not executing, including superseded frozen ones. Offenders: "
        + ", ".join(sorted(offenders))
    )


def test_the_statement_scan_sees_more_than_one_statement_per_file():
    # Guards the splitter: a regression that returned the whole file as one statement would make
    # the check above collapse back into the file-level one it exists to replace.
    multi = [path for path in _suite_scoped_templates() if len(_statements(path.read_text())) > 1]
    assert multi, "no multi-statement suite-scoped template found; the splitter is not working"
