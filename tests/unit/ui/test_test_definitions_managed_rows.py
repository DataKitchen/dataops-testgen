"""Tests for how the test-definitions page leaves managed definitions out of its bulk actions."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import MANAGED_TEST_TYPES
from testgen.common.models.test_definition import TestDefinition
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


@pytest.mark.parametrize(
    ("action", "count", "expected"),
    [
        (view.DELETE_ACTION, 1, "TestGen manages the selected test. It cannot be deleted."),
        (view.COPY_MOVE_ACTION, 2, "TestGen manages the selected tests. They cannot be copied or moved."),
        ("unlocked", 2, "TestGen manages the selected tests. They cannot be unlocked."),
    ],
)
def test_the_refusal_names_the_action(action, count, expected):
    assert view._managed_refusal(action, count) == expected


@pytest.mark.parametrize(
    ("attribute", "value", "action"),
    [
        ("test_active", True, "activated"),
        ("test_active", False, "deactivated"),
        ("lock_refresh", True, "locked"),
        ("lock_refresh", False, "unlocked"),
    ],
)
def test_a_status_change_on_only_managed_tests_is_refused(attribute, value, action):
    managed_id = str(uuid4())
    with patch.object(view, "_managed_ids", return_value={managed_id}):
        assert view._without_managed(attribute, value, [managed_id]) == (
            [],
            f"TestGen manages the selected test. It cannot be {action}.",
        )


def test_a_status_change_leaves_out_the_managed_tests_silently():
    managed_id, other_id = str(uuid4()), str(uuid4())
    with patch.object(view, "_managed_ids", return_value={managed_id}):
        assert view._without_managed("test_active", False, [managed_id, other_id]) == ([other_id], None)


def test_a_status_change_without_managed_tests_writes_every_test():
    ids = [str(uuid4()), str(uuid4())]
    with patch.object(view, "_managed_ids", return_value=set()):
        assert view._without_managed("lock_refresh", True, ids) == (ids, None)


def test_flagging_applies_to_managed_tests():
    ids = [str(uuid4())]
    with patch.object(view, "_managed_ids") as managed_ids:
        assert view._without_managed("flagged", True, ids) == (ids, None)

    managed_ids.assert_not_called()


def test_managed_count_counts_the_managed_tests_the_filters_match():
    suite = MagicMock(id=uuid4())
    version_id = uuid4()
    with patch.object(view, "select_test_definitions_minimal_where", return_value=[MagicMock(), MagicMock()]) as select:
        assert view.get_managed_count(suite, table_name="orders", version_id=version_id) == 2

    expected = (
        TestDefinition.test_suite_id == suite.id,
        TestDefinition.table_name == "orders",
        TestDefinition.test_type.in_(MANAGED_TEST_TYPES),
    )
    assert [str(clause) for clause in select.call_args.args] == [str(clause) for clause in expected]
    assert select.call_args.kwargs == {"version_id": version_id}
