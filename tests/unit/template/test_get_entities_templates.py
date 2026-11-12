"""The CLI's listing templates read every kind of test suite but monitors."""

from pathlib import Path

import pytest

import testgen

pytestmark = pytest.mark.unit

GET_ENTITIES = Path(testgen.__file__).parent / "template" / "get_entities"


@pytest.mark.parametrize(
    "template", sorted(path.name for path in GET_ENTITIES.glob("*.sql") if "suite_type" in path.read_text())
)
def test_a_listing_that_filters_by_suite_type_includes_contracts(template):
    assert "suite_type IN ('standard', 'contract')" in (GET_ENTITIES / template).read_text()
