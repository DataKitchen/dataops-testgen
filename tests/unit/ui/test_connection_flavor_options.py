"""Flavor options the connections page hands to its frontend component."""

import importlib

import pytest

pytestmark = pytest.mark.unit


def load_connections(monkeypatch, release_check: str):
    """Import the connections view with the deployment mode set, since the field help is
    computed once at import."""
    from testgen import settings

    monkeypatch.setattr(settings, "CHECK_FOR_LATEST_VERSION", release_check)
    module = importlib.import_module("testgen.ui.views.connections")
    return importlib.reload(module)


def duckdb_option(connections):
    return next(option for option in connections.FLAVOR_OPTIONS if option.value == "duckdb")


def test_duckdb_appears_in_the_database_type_picker(monkeypatch):
    connections = load_connections(monkeypatch, "pypi")
    option = duckdb_option(connections)
    assert option.label == "DuckDB"
    assert option.flavor == "duckdb"
    assert option.icon


def test_a_pip_install_describes_the_database_file_without_a_container_caveat(monkeypatch):
    connections = load_connections(monkeypatch, "pypi")
    help_text = duckdb_option(connections).field_help["database_file"]
    assert help_text == "Path to the DuckDB database file"


def test_a_container_install_says_the_path_is_read_inside_the_container(monkeypatch):
    connections = load_connections(monkeypatch, "docker")
    help_text = duckdb_option(connections).field_help["database_file"]
    assert help_text == (
        "Path to the DuckDB database file. It must be a path inside the TestGen container, "
        "so the file has to be on a mounted volume."
    )


def test_flavors_without_deployment_specific_help_carry_none(monkeypatch):
    connections = load_connections(monkeypatch, "docker")
    postgresql = next(o for o in connections.FLAVOR_OPTIONS if o.value == "postgresql")
    assert postgresql.field_help == {}


def test_duckdb_tells_the_form_its_thread_count_is_not_configurable(monkeypatch):
    """The form hides the Max Threads control on this, so it has to travel with the option."""
    connections = load_connections(monkeypatch, "pypi")
    assert duckdb_option(connections).fixed_max_threads == 1


def test_a_server_flavor_leaves_the_thread_count_to_the_form(monkeypatch):
    connections = load_connections(monkeypatch, "pypi")
    snowflake = next(o for o in connections.FLAVOR_OPTIONS if o.value == "snowflake")
    assert snowflake.fixed_max_threads is None


# --- Table group schema label ------------------------------------------------


def flavor_option(connections, value):
    return next(option for option in connections.FLAVOR_OPTIONS if option.value == value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("files", None),
        ("salesforce_data360", "Data Space"),
        ("duckdb", "Schema"),
        ("postgresql", "Schema"),
    ],
)
def test_the_flavor_option_carries_the_schema_label_to_the_form(monkeypatch, value, expected):
    connections = load_connections(monkeypatch, "pypi")
    assert flavor_option(connections, value).schema_label == expected
