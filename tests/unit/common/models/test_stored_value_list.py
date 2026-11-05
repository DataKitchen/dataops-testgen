import pytest

from testgen.common.models.test_definition import InvalidTestDefinitionFields, stored_value_list

pytestmark = pytest.mark.unit


def test_a_list_holding_only_the_empty_string_is_refused_where_it_is_stored_as_null():
    with pytest.raises(InvalidTestDefinitionFields) as error:
        stored_value_list("LOV_All", '"",""', "A", lambda: False)

    assert error.value.errors == {
        "baseline_value": "on Oracle the empty string is NULL, so the list must hold at least one other value"
    }


def test_the_empty_string_beside_another_value_is_kept_where_it_is_stored_as_null():
    assert stored_value_list("LOV_Match", '"",a', "A", lambda: False) == '"",a'


def test_a_list_holding_only_the_empty_string_is_kept_where_it_is_stored():
    assert stored_value_list("LOV_All", '""', "A", lambda: True) == '""'


def test_the_database_is_consulted_only_for_a_list_holding_only_the_empty_string():
    def consulted() -> bool:
        raise AssertionError("consulted for a list holding other values")

    assert stored_value_list("LOV_All", "a, b", "A", consulted) == "a,b"
