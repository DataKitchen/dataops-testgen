import pytest

from testgen.common.database.database_service import FinalParam, replace_params

pytestmark = pytest.mark.unit


def test_a_value_is_expanded_by_a_later_param():
    assert replace_params("{A}", {"A": "x {B}", "B": "y"}) == "x y"


def test_a_final_value_is_expanded_by_no_param():
    params = {"A": FinalParam("{B} {C}"), "B": FinalParam("b"), "C": "c"}
    assert replace_params("{A} {B} {C}", params) == "{B} {C} b c"


def test_a_final_value_lands_where_an_earlier_value_put_its_placeholder():
    assert replace_params("{A}", {"A": "x {B}", "B": FinalParam("y")}) == "x y"
