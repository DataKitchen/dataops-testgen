import pytest

from testgen.common.odcs.physical_types import TypeMatch, compare_physical_types

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("declared", "recorded", "family"), [
    ("VARCHAR(255)", "varchar(255)", "postgresql"),
    ("varchar(255)", "character varying(255)", "postgresql"),
    ("integer", "int4", "postgresql"),
    ("numeric(10,2)", "decimal(10, 2)", "postgresql"),
    ("varchar", "character varying(255)", "postgresql"),
    ("STRING", "VARCHAR(16777216)", "snowflake"),
    ("TEXT", "VARCHAR", "snowflake"),
    ("DATETIME", "TIMESTAMP_NTZ", "snowflake"),
    ("TIMESTAMP", "timestamp_ntz", "snowflake"),
    ("REAL", "FLOAT", "snowflake"),
    ("DOUBLE", "FLOAT", "snowflake"),
    ("INTEGER", "INT64", "bigquery"),
    ("INTEGER", "NUMBER(38,0)", "snowflake"),
    ("BIGINT", "NUMBER(38,0)", "snowflake"),
    ("NUMBER(10)", "NUMBER(10,0)", "snowflake"),
    ("INTEGER", "NUMBER(38,0)", "oracle"),
    ("SMALLINT", "NUMBER(38,0)", "oracle"),
    ("NUMBER(*,0)", "NUMBER(38,0)", "oracle"),
    ("NUMBER(10)", "NUMBER(10,0)", "oracle"),
    ("VARCHAR2(50 BYTE)", "VARCHAR2(50)", "oracle"),
    ("VARCHAR2(50 CHAR)", "VARCHAR2(50 CHAR)", "oracle"),
    ("numeric(10)", "numeric(10,0)", "postgresql"),
    ("numeric(10)", "numeric(10,0)", "redshift"),
    ("decimal(10)", "decimal(10,0)", "mssql"),
    ("decimal(10)", "decimal(10,0)", "databricks"),
    ("BIGNUMERIC(40)", "BIGNUMERIC(40, 0)", "bigquery"),
    ("real", "float(24)", "mssql"),
    ("double precision", "float", "mssql"),
    ("FLOAT(10)", "real", "mssql"),
    ("FLOAT(25)", "float", "mssql"),
    ("FLOAT(10)", "real", "postgresql"),
    ("FLOAT(25)", "double precision", "postgresql"),
    ("FLOAT(10)", "real", "redshift"),
    ("NVARCHAR(MAX)", "nvarchar(max)", "mssql"),
    ("NVARCHAR(10)", "NVARCHAR(10)", "sap_hana"),
])
def test_equivalent_spellings_match(declared, recorded, family):
    assert compare_physical_types(declared, recorded, family) is TypeMatch.EQUIVALENT


@pytest.mark.parametrize(("declared", "recorded", "family"), [
    ("varchar(100)", "character varying(255)", "postgresql"),
    ("integer", "bigint", "postgresql"),
    ("timestamp", "timestamp with time zone", "postgresql"),
    ("TIMESTAMP_TZ", "TIMESTAMP_NTZ", "snowflake"),
    ("float", "real", "mssql"),
    ("double precision", "real", "mssql"),
    ("FLOAT(24)", "float", "mssql"),
    ("FLOAT(24)", "double precision", "postgresql"),
    ("TIMESTAMP", "timestamp_ltz", "snowflake"),
    ("INTEGER", "NUMBER(10,2)", "oracle"),
    ("INTEGER", "NUMBER(10,0)", "snowflake"),
    ("numeric(10)", "numeric(10,2)", "postgresql"),
    ("VARCHAR2(50 CHAR)", "VARCHAR2(50)", "oracle"),
])
def test_different_types_mismatch(declared, recorded, family):
    assert compare_physical_types(declared, recorded, family) is TypeMatch.MISMATCH


@pytest.mark.parametrize(("declared", "recorded", "family"), [
    ("varchar(255)", "varchar", "postgresql"),
    ("INTEGER", "NUMBER", "oracle"),
    ("not a type at all ((", "integer", "postgresql"),
    ("NVARCHAR(10)", "VARCHAR(10)", "sap_hana"),
    ("STRING", "VARCHAR(10)", "salesforce_data360"),
])
def test_a_comparison_that_cannot_be_made_is_unknown(declared, recorded, family):
    assert compare_physical_types(declared, recorded, family) is TypeMatch.UNKNOWN
