"""Which connections a run's schema overrides apply to."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.database.table_group_service import unsupported_schema_override
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, SqlFlavorCode
from testgen.common.run_overrides import MATCH_SCHEMA_OVERRIDE_UNSUPPORTED, SCHEMA_OVERRIDE_UNSUPPORTED

pytestmark = pytest.mark.unit

MODULE = "testgen.common.database.table_group_service"

# Flavors whose tables a schema does not qualify: the file codes, whose declarations land in one
# fixed schema, and Data 360, whose objects are named on their own.
UNSUPPORTED_CODES = [SqlFlavorCode.FILES, SqlFlavorCode.S3, SqlFlavorCode.AZURE_BLOB, SqlFlavorCode.SALESFORCE_DATA360]


def _connection(sql_flavor_code):
    connection = MagicMock()
    connection.sql_flavor_code = sql_flavor_code
    connection.sql_flavor = FLAVOR_CODE_TO_FAMILY[sql_flavor_code]
    return connection


def _refusal(sql_flavor_code, **overrides):
    with patch(f"{MODULE}.Connection.get_by_table_group", return_value=_connection(sql_flavor_code)):
        return unsupported_schema_override(uuid4(), **overrides)


@pytest.mark.parametrize("sql_flavor_code", [SqlFlavorCode.POSTGRESQL, SqlFlavorCode.DUCKDB])
@pytest.mark.parametrize("override", ["schema_name", "match_schema_name"])
def test_a_schema_qualified_flavor_takes_either_override(sql_flavor_code, override):
    assert _refusal(sql_flavor_code, **{override: "reference_2026_09_11"}) is None


@pytest.mark.parametrize("sql_flavor_code", UNSUPPORTED_CODES)
def test_a_flavor_whose_tables_a_schema_does_not_qualify_refuses_the_schema_override(sql_flavor_code):
    """Accepting it would run against one location while validation checked another."""
    assert _refusal(sql_flavor_code, schema_name="reference_2026_09_11") == SCHEMA_OVERRIDE_UNSUPPORTED


@pytest.mark.parametrize("sql_flavor_code", UNSUPPORTED_CODES)
def test_the_same_flavors_refuse_the_match_schema_override(sql_flavor_code):
    assert _refusal(sql_flavor_code, match_schema_name="reference_2026_09_11") == MATCH_SCHEMA_OVERRIDE_UNSUPPORTED


@pytest.mark.parametrize("sql_flavor_code", UNSUPPORTED_CODES)
def test_a_run_that_overrides_no_schema_is_not_refused(sql_flavor_code):
    """Table name overrides apply to every flavor, so a run carrying only those still runs."""
    assert _refusal(sql_flavor_code) is None


def test_a_table_group_with_no_connection_is_not_refused():
    with patch(f"{MODULE}.Connection.get_by_table_group", return_value=None):
        assert unsupported_schema_override(uuid4(), schema_name="reference_2026_09_11") is None


@pytest.mark.unit
def test_a_run_with_no_schema_override_reads_no_connection():
    """Every test run submission reaches this, so the connection is only looked up when there is
    an override whose support depends on it."""
    with patch(f"{MODULE}.Connection.get_by_table_group") as get_by_table_group:
        assert unsupported_schema_override(uuid4()) is None

    get_by_table_group.assert_not_called()
