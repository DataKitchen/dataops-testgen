"""Guards the display names in shipped reference data.

Every test type and hygiene issue type must carry a usable ``test_name_short`` /
``anomaly_name``: display code falls back to the internal code when one is missing, and
lookups match on the name, so a missing or whitespace-padded name makes the type both
unreachable and wrong on screen.
"""
from pathlib import Path

import pytest
from yaml import safe_load

import testgen

pytestmark = pytest.mark.unit

TEMPLATE_DIR = Path(testgen.__file__).parent / "template"
TEST_TYPE_DIR = TEMPLATE_DIR / "dbsetup_test_types"
ISSUE_TYPE_DIR = TEMPLATE_DIR / "dbsetup_anomaly_types"


def _records(directory: Path, root_key: str) -> list[dict]:
    docs = [safe_load(path.read_text())[root_key] for path in sorted(directory.glob("*.yaml"))]
    assert docs, f"no reference data found in {directory}"
    return docs


def _test_types() -> list[dict]:
    return _records(TEST_TYPE_DIR, "test_types")


def _issue_types() -> list[dict]:
    return _records(ISSUE_TYPE_DIR, "profile_anomaly_types")


def test_every_test_type_has_a_display_name():
    missing = [tt["test_type"] for tt in _test_types() if not (tt.get("test_name_short") or "").strip()]
    assert not missing, f"test types with no test_name_short: {missing}"


def test_every_issue_type_has_a_display_name():
    missing = [it["id"] for it in _issue_types() if not (it.get("anomaly_name") or "").strip()]
    assert not missing, f"hygiene issue types with no anomaly_name: {missing}"


@pytest.mark.parametrize(
    "records,code_key,name_key",
    [
        (_test_types(), "test_type", "test_name_short"),
        (_issue_types(), "id", "anomaly_name"),
    ],
    ids=["test_types", "issue_types"],
)
def test_display_names_carry_no_stray_whitespace(records, code_key, name_key):
    """A padded name can never be matched by the string the catalog advertises."""
    padded = {r[code_key]: repr(r[name_key]) for r in records if r[name_key] != r[name_key].strip()}
    assert not padded, f"display names with leading/trailing whitespace: {padded}"


@pytest.mark.parametrize(
    "records,code_key,name_key",
    [
        (_test_types(), "test_type", "test_name_short"),
        (_issue_types(), "id", "anomaly_name"),
    ],
    ids=["test_types", "issue_types"],
)
def test_display_names_are_unambiguous(records, code_key, name_key):
    """Lookups match case-insensitively, so two names differing only by case would be
    unresolvable to whichever one the caller meant."""
    by_name: dict[str, list[str]] = {}
    for record in records:
        by_name.setdefault(record[name_key].strip().lower(), []).append(record[code_key])
    collisions = {name: codes for name, codes in by_name.items() if len(codes) > 1}
    assert not collisions, f"display names that collide when case-folded: {collisions}"
