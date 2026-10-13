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

# Measure columns no profiling query writes, so there is no acquisition to declare.
UNWRITTEN_MEASURES = {"mixed_case_ct"}


def test_every_measure_column_declares_how_it_is_acquired():
    columns = {column.name for column in ProfileResult.__table__.columns}

    assert set(ProfileResult.measure_acquisition) == columns - NOT_MEASURES - UNWRITTEN_MEASURES
