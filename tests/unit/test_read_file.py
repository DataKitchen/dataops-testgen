import textwrap

import pytest

from testgen.common.read_file import replace_templated_functions


@pytest.fixture
def query():
    return textwrap.dedent("""
        SELECT <%DATEDIFF_YEAR;'{COL_NAME}'::DATE;'1970-01-01'%>
        FROM ATABLE
        WHERE <%DATEDIFF_MONTH;'{COL_NAME}'::DATE;'1970-01-01'%> > 36
    """)


@pytest.mark.unit
def test_replace_templated_functions(query):
    fn = replace_templated_functions(query, "postgresql")

    expected = textwrap.dedent("""
        SELECT DATE_PART('year', '1970-01-01'::TIMESTAMP) - DATE_PART('year', '{COL_NAME}'::DATE::TIMESTAMP)
        FROM ATABLE
        WHERE (DATE_PART('year', '1970-01-01'::TIMESTAMP) - DATE_PART('year', '{COL_NAME}'::DATE::TIMESTAMP)) * 12 + (DATE_PART('month', '1970-01-01'::TIMESTAMP) - DATE_PART('month', '{COL_NAME}'::DATE::TIMESTAMP)) > 36
    """)

    assert fn == expected


@pytest.mark.unit
def test_replace_templated_missing_arg(query):
    query = query.replace(";'1970-01-01'", "")
    with pytest.raises(
        ValueError,
        match="Templated function call missing required arguments: <%DATEDIFF_YEAR;'{COL_NAME}'::DATE%>",
    ):
        replace_templated_functions(query, "postgresql")
