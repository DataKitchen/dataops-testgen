import pytest

from testgen.common.database.database_service import get_flavor_service

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("column_type", ["char(3)", "CHAR(10)", "nchar"])
def test_sql_server_reads_fixed_length_text_without_its_padding(column_type):
    assert get_flavor_service("mssql").text_value('"col"', column_type) == 'RTRIM("col")'


@pytest.mark.parametrize("column_type", ["varchar(10)", "nvarchar", "text", "int", None])
def test_sql_server_reads_other_columns_as_they_are(column_type):
    assert get_flavor_service("mssql").text_value('"col"', column_type) == '"col"'


@pytest.mark.parametrize("flavor", ["postgresql", "redshift", "redshift_spectrum"])
def test_postgresql_and_redshift_read_char_without_its_padding(flavor):
    assert get_flavor_service(flavor).text_value('"col"', "char(3)") == 'RTRIM("col")'
    assert get_flavor_service(flavor).text_value('"col"', "varchar(3)") == '"col"'


@pytest.mark.parametrize("flavor", ["snowflake", "oracle", "duckdb"])
def test_other_flavors_read_fixed_length_text_as_it_is(flavor):
    assert get_flavor_service(flavor).text_value('"col"', "char(3)") == '"col"'
