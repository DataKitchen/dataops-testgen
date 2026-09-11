from types import SimpleNamespace
from uuid import uuid4

import pytest

from testgen.commands.run_observability_exporter import (
    _get_event_data,
    _get_input_parameters,
    _get_processed_profiling_table_set,
    calculate_chunk_size,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def test_outcome():
    yield {
        "name": "Unique_Pct_test_gen_test_party_planners_address",
        "status": "PASSED",
        "description": "Tests for statistically-significant shift in percentage of unique values vs. baseline data.",
        "metadata": {
            "test_type": "Unique_Pct",
            "schema_name": "test_gen",
            "table_name": "test_party_planners",
            "column_name": "address",
        },
    }


@pytest.mark.parametrize(
    "test_outcomes_length",
    [1, 100, 10000],
)
def test_calculate_chunk_size(test_outcome, test_outcomes_length):
    # test configuration
    test_outcomes = []
    for _i in range(test_outcomes_length):
        test_outcomes.append(test_outcome)

    # test run
    chunk_size = calculate_chunk_size(test_outcomes)

    # test assertions
    assert 100 < chunk_size < 500


@pytest.mark.parametrize(
    "profiling_table_set, expected_outcome",
    (
        (None, []),
        ("'table_a'", ["table_a"]),
        ("'table_a','table_b','table_c'", ["table_a", "table_b", "table_c"]),
    ),
)
def test_get_processed_profiling_table_set(profiling_table_set, expected_outcome):
    actual_outcome = _get_processed_profiling_table_set(profiling_table_set)
    assert expected_outcome == actual_outcome


@pytest.mark.parametrize(
    "input_parameters, expected_outcome",
    (
        (None, []),
        ("", []),
        ("Threshold_Value=12 ", [{"name": "Threshold_Value", "value": "12"}]),
        (
            "Baseline_Ct=45707, Baseline_Value_Ct=45687, Threshold_Value=2 ",
            [
                {"name": "Baseline_Ct", "value": "45707"},
                {"name": "Baseline_Value_Ct", "value": "45687"},
                {"name": "Threshold_Value", "value": "2"},
            ],
        ),
        (
            "Baseline_Value=('Anna Thompson','Robert Smith','David Hamilton','Ashlee Martin','Mandy Evans','Miguel Lee'), Threshold_Value=0",
            [
                {
                    "name": "Baseline_Value",
                    "value": "('Anna Thompson','Robert Smith','David Hamilton','Ashlee Martin','Mandy Evans','Miguel Lee')",
                },
                {"name": "Threshold_Value", "value": "0"},
            ],
        ),
        (
            "Baseline_Value=('Anna Thompson','Robert Smith')",
            [{"name": "Baseline_Value", "value": "('Anna Thompson','Robert Smith')"}],
        ),
        (
            "Threshold_Value=0,Baseline_Value=('Anna Thompson','Robert Smith','David Hamilton','Ashlee Martin','Mandy Evans','Miguel Lee')",
            [
                {"name": "Threshold_Value", "value": "0"},
                {
                    "name": "Baseline_Value",
                    "value": "('Anna Thompson','Robert Smith','David Hamilton','Ashlee Martin','Mandy Evans','Miguel Lee')",
                },
            ],
        ),
        (
            "Baseline_Value=('No','Yes'), Threshold_Value=0",
            [{"name": "Baseline_Value", "value": "('No','Yes')"}, {"name": "Threshold_Value", "value": "0"}],
        ),
    ),
)
def test_get_input_parameters(input_parameters, expected_outcome):
    actual_outcome = _get_input_parameters(input_parameters)
    assert actual_outcome == expected_outcome


def _event(**overrides):
    defaults = {
        "sql_flavor": "postgresql",
        "dataset_key": "dataset-key",
        "dataset_name": "dataset-name",
        "schema": "public",
        "connection_name": "conn",
        "project_db": "db",
        "table_groups_id": uuid4(),
        "project_code": "DEFAULT",
        "profile_use_sampling": "Y",
        "profile_sample_percent": 30,
        "profile_sample_minimum_count": 15000,
        "profiling_include_mask": "%",
        "profiling_exclude_mask": "tmp%",
        "profiling_table_set": "",
    }
    return SimpleNamespace(**{**defaults, **overrides})


def _table_group_config(event):
    return _get_event_data(event)["component_integrations"]["integrations"]["testgen"]["table_group_configuration"]


def test_sample_percentage_is_exported_as_a_string():
    """The column is an integer, but Observability receives the percent as a string."""
    config = _table_group_config(_event(profile_sample_percent=30))

    assert config["sample_percentage"] == "30"


def test_sample_percentage_is_null_when_unset():
    """A NULL percent stays null rather than becoming the string "None"."""
    config = _table_group_config(_event(profile_sample_percent=None))

    assert config["sample_percentage"] is None


def test_sample_settings_are_null_when_sampling_is_off():
    config = _table_group_config(_event(profile_use_sampling="N"))

    assert config["uses_sampling"] is False
    assert config["sample_percentage"] is None
    assert config["sample_minimum_count"] is None
