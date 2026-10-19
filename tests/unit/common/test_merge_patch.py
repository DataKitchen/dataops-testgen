import pytest

from testgen.common.merge_patch import apply_merge_patch

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "target, patch, expected",
    [
        # RFC 7386 Appendix A
        ({"a": "b"}, {"a": "c"}, {"a": "c"}),
        ({"a": "b"}, {"b": "c"}, {"a": "b", "b": "c"}),
        ({"a": "b"}, {"a": None}, {}),
        ({"a": "b", "b": "c"}, {"a": None}, {"b": "c"}),
        ({"a": ["b"]}, {"a": "c"}, {"a": "c"}),
        ({"a": "c"}, {"a": ["b"]}, {"a": ["b"]}),
        ({"a": {"b": "c"}}, {"a": {"b": "d", "c": None}}, {"a": {"b": "d"}}),
        ({"a": [{"b": "c"}]}, {"a": [1]}, {"a": [1]}),
        (["a", "b"], ["c", "d"], ["c", "d"]),
        ({"a": "b"}, ["c"], ["c"]),
        ({"a": "foo"}, None, None),
        ({"a": "foo"}, "bar", "bar"),
        ({"e": None}, {"a": 1}, {"e": None, "a": 1}),
        ([1, 2], {"a": "b", "c": None}, {"a": "b"}),
        ({}, {"a": {"bb": {"ccc": None}}}, {"a": {"bb": {}}}),
    ],
)
def test_merge_patch_follows_the_rfc_examples(target, patch, expected):
    assert apply_merge_patch(target, patch) == expected


def test_one_field_changes_and_every_other_section_stays():
    document = {"name": "Orders", "team": {"name": "Data"}, "schema": [{"name": "orders"}]}

    assert apply_merge_patch(document, {"support": [{"channel": "#orders"}]}) == {**document, "support": [{"channel": "#orders"}]}


def test_a_list_is_replaced_rather_than_merged():
    document = {"schema": [{"name": "orders"}, {"name": "customers"}]}

    assert apply_merge_patch(document, {"schema": [{"name": "orders", "description": "Order facts"}]}) == {
        "schema": [{"name": "orders", "description": "Order facts"}]
    }


def test_the_target_is_not_mutated():
    document = {"team": {"name": "Data"}}

    apply_merge_patch(document, {"team": {"name": "Platform"}})

    assert document == {"team": {"name": "Data"}}
