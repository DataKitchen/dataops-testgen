"""Tests for how the test-definitions page leaves managed definitions out of its bulk dialogs."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.test_definition import MANAGED_TEST_TYPES, TestDefinition
from testgen.ui.views import test_definitions as view

pytestmark = pytest.mark.unit


def test_managed_ids_returns_the_ids_of_managed_definitions():
    managed_id, other_id = str(uuid4()), str(uuid4())

    with patch.object(view, "select_test_definitions_minimal_where", return_value=[MagicMock(id=managed_id)]) as select:
        assert view._managed_ids([managed_id, other_id]) == {managed_id}

    expected = (TestDefinition.id.in_([managed_id, other_id]), TestDefinition.test_type.in_(MANAGED_TEST_TYPES))
    assert [str(clause) for clause in select.call_args.args] == [str(clause) for clause in expected]


def test_managed_ids_skips_the_query_for_an_empty_selection():
    with patch.object(view, "select_test_definitions_minimal_where") as select:
        assert view._managed_ids([]) == set()

    select.assert_not_called()


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, None),
        (1, "1 selected test is managed by TestGen and is left out."),
        (3, "3 selected tests are managed by TestGen and are left out."),
    ],
)
def test_the_left_out_note_counts_the_managed_tests(count, expected):
    assert view._managed_left_out_note(count) == expected
