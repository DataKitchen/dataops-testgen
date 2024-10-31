import pytest

from testgen.common.read_file import replace_templated_functions


@pytest.mark.unit
def test_replace_templated_functions():
    fn = replace_templated_functions(
        "SELECT {{DKFN_DATEDIFF_YEAR;;'{COL_NAME}'::DATE;;'1970-01-01'}} FROM ATABLE WHERE {{DKFN_DATEDIFF_MONTH;;'{COL_NAME}'::DATE;;'1970-01-01'}} > 36",
        "postgresql",
    )
    assert (
        fn
        == "SELECT DATE_PART('year', '1970-01-01'::TIMESTAMP) - DATE_PART('year', '{COL_NAME}'::DATE::TIMESTAMP) FROM ATABLE WHERE (DATE_PART('year', '1970-01-01'::TIMESTAMP) - DATE_PART('year', '{COL_NAME}'::DATE::TIMESTAMP)) * 12 + (DATE_PART('month', '1970-01-01'::TIMESTAMP) - DATE_PART('month', '{COL_NAME}'::DATE::TIMESTAMP)) > 36"
    )
