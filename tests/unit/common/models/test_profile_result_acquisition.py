from testgen.common.models.profile_result import ProfileResult

# Columns that identify, classify or annotate a profile row rather than measure the column.
NOT_MEASURES = {
    "id",
    "profile_run_id",
    "table_groups_id",
    "schema_name",
    "table_name",
    "column_name",
    "position",
    "project_code",
    "connection_id",
    "run_date",
    "general_type",
    "column_type",
    "db_data_type",
    "functional_data_type",
    "functional_table_type",
    "key_column_name",
    "datatype_suggestion",
    "pii_flag",
    "percentile_method",
    "sample_ratio",
    "query_error",
}


def test_every_measure_column_is_declared():
    columns = {column.name for column in ProfileResult.__table__.columns}

    assert set(ProfileResult.measures) == columns - NOT_MEASURES
