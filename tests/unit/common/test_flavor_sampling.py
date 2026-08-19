"""Per-flavor sampleable object types.

Profiling skips sampling for object types a flavor's sample clause cannot handle
(see run_profiling._compute_sampling_params). These tests lock in the per-flavor
sampleable_object_types and the object-type signal the skip depends on.
"""
import pytest

from testgen.common.database.column_chars import ColumnChars, ObjectType
from testgen.common.database.database_service import get_flavor_service

pytestmark = pytest.mark.unit


# Verified live: TABLESAMPLE errors on a view for these flavors, so only physical relations
# are sampleable; views/external/other are profiled in full.
def test_mssql_samples_only_base_tables():
    # SQL Server has no materialized views, so the sampleable set is just base tables.
    assert get_flavor_service("mssql").sampleable_object_types("mssql") == {ObjectType.TABLE}
    # azure_mssql / synapse_mssql share the mssql family and inherit the same set.
    assert get_flavor_service("mssql").sampleable_object_types("azure_mssql") == {ObjectType.TABLE}


def test_onelake_disables_sampling():
    # Fabric SQL analytics endpoints reject TABLESAMPLE; the empty set signals
    # "no object type is sampleable" and _compute_sampling_params skips out.
    assert get_flavor_service("mssql").sampleable_object_types("onelake_mssql") == frozenset()


def test_postgresql_samples_tables_and_materialized_views():
    assert get_flavor_service("postgresql").sampleable_object_types("postgresql") == {
        ObjectType.TABLE,
        ObjectType.MATERIALIZED_VIEW,
    }


@pytest.mark.parametrize("flavor", ["redshift", "snowflake", "databricks", "oracle", "bigquery"])
def test_sampleable_unrestricted_where_sampling_works_on_views(flavor):
    # None = no restriction. Row-based samplers, or engines that accept the sample clause on
    # views (verified live for snowflake/databricks/oracle).
    assert get_flavor_service(flavor).sampleable_object_types(flavor) is None


def test_object_type_enum_values_match_ddf_strings():
    # The DDF emits these literal strings; the skip compares column.object_type against them.
    assert ObjectType.TABLE == "TABLE"
    assert ObjectType.VIEW == "VIEW"
    assert ObjectType.MATERIALIZED_VIEW == "MATERIALIZED_VIEW"
    assert ObjectType.EXTERNAL == "EXTERNAL"
    assert ObjectType.OTHER == "OTHER"


def test_column_chars_object_type_defaults_none():
    # Flavors whose DDF does not supply object_type leave it None.
    assert ColumnChars(schema_name="s", table_name="t", column_name="c").object_type is None
