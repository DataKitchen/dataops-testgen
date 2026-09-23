"""Tests that no stored credential leaves the server in a connections payload.

``format_connection`` starts from an unfiltered dump of every column, already decrypted by
the ORM, so what it withholds is the only thing standing between a stored credential and
the browser.
"""

from unittest.mock import patch

import pytest

from testgen.common.database.connection_service import MASKED_VALUE, is_pristine
from testgen.common.models.connection import Connection
from testgen.common.models.custom_types import EncryptedBytea
from testgen.ui.views import connections as connections_view

pytestmark = pytest.mark.unit


def _conn(**overrides) -> Connection:
    """Build a Connection without touching the DB."""
    defaults = {
        "sql_flavor": "postgresql",
        "sql_flavor_code": "postgresql",
        "connection_name": "My DB",
        "project_host": "localhost",
        "project_port": "5432",
        "project_db": "sales",
        "project_user": "analyst",
        "project_code": "demo",
    }
    return Connection(**{**defaults, **overrides})


def _format(connection: Connection) -> dict:
    with patch.object(connections_view, "FLAVOR_OPTIONS", []):
        return connections_view.format_connection(connection)


def test_encrypted_columns_are_read_off_the_column_types():
    encrypted = Connection.encrypted_columns()
    assert set(encrypted) == {
        column.name for column in Connection.__table__.columns if isinstance(column.type, EncryptedBytea)
    }
    # Pinned so a column dropping out of the derivation fails here rather than silently.
    assert set(encrypted) == {
        "project_pw_encrypted",
        "private_key",
        "private_key_passphrase",
        "service_account_key",
        "secrets",
    }


def test_format_connection_withholds_every_encrypted_column():
    populated = _conn(
        project_pw_encrypted="hunter2",
        private_key="-----BEGIN PRIVATE KEY-----",
        private_key_passphrase="phrase",  # noqa: S106
        service_account_key={"project_id": "gcp-proj", "private_key": "-----BEGIN-----"},
        secrets={"access_key_id": "AKIA"},
    )
    formatted = _format(populated)

    for column in Connection.encrypted_columns():
        if column == "secrets":
            continue
        assert formatted[column] == MASKED_VALUE, f"{column} reached the browser unmasked"
    assert "secrets" not in formatted


def test_format_connection_withholds_the_bigquery_service_account_key():
    """Regression: the decrypted service-account JSON was serialized to the browser in full."""
    formatted = _format(
        _conn(
            sql_flavor="bigquery",
            sql_flavor_code="bigquery",
            project_db="gcp-proj",
            service_account_key={"project_id": "gcp-proj", "private_key": "-----BEGIN PRIVATE KEY-----"},
        )
    )
    assert formatted["service_account_key"] == MASKED_VALUE
    # The form reads the Project ID from here instead of re-parsing the key.
    assert formatted["project_db"] == "gcp-proj"


def test_format_connection_drops_the_secrets_column_outright():
    assert "secrets" not in _format(_conn(secrets={"access_key_id": "AKIA"}))


def test_format_connection_leaves_an_empty_encrypted_column_alone():
    """An absent credential stays falsy so a form can tell that nothing is stored."""
    formatted = _format(_conn())
    assert not formatted.get("project_pw_encrypted")
    assert not formatted.get("service_account_key")


def test_is_pristine_matches_what_the_browser_echoes_back():
    """The masked value has to read as untouched, or saving would store the mask."""
    assert is_pristine("")
    assert is_pristine(MASKED_VALUE)
    assert not is_pristine("hunter2")
    assert not is_pristine(None)
    assert not is_pristine({"project_id": "gcp-proj"})


@pytest.mark.parametrize(
    "column",
    ["project_pw_encrypted", "private_key", "private_key_passphrase", "service_account_key"],
)
@pytest.mark.parametrize("untouched", ["", "   ", MASKED_VALUE])
def test_sanitize_treats_the_mask_and_an_empty_field_alike(column, untouched):
    """Otherwise the mask rides onto the model as a literal string on the next rerun."""
    page = connections_view.ConnectionsPage.__new__(connections_view.ConnectionsPage)
    assert page._sanitize_connection_input({column: untouched})[column] is None


def test_sanitize_keeps_a_freshly_typed_credential():
    page = connections_view.ConnectionsPage.__new__(connections_view.ConnectionsPage)
    assert page._sanitize_connection_input({"project_pw_encrypted": "hunter2"})["project_pw_encrypted"] == "hunter2"


@pytest.mark.parametrize(
    "column",
    ["project_pw_encrypted", "private_key", "private_key_passphrase", "service_account_key"],
)
def test_sanitize_trims_a_credential(column):
    """Stray whitespace around a pasted credential is not part of it."""
    page = connections_view.ConnectionsPage.__new__(connections_view.ConnectionsPage)
    assert page._sanitize_connection_input({column: "  hunter2\n"})[column] == "hunter2"


def test_format_connection_supplies_the_project_id_when_the_column_is_empty():
    """A BigQuery connection created outside this form carries it only inside the key."""
    formatted = _format(
        _conn(
            sql_flavor="bigquery",
            sql_flavor_code="bigquery",
            project_db=None,
            service_account_key={"project_id": "from-the-key", "private_key": "-----BEGIN-----"},
        )
    )
    assert formatted["project_db"] == "from-the-key"
    assert formatted["service_account_key"] == MASKED_VALUE


def test_format_connection_keeps_a_stored_project_id():
    formatted = _format(
        _conn(
            sql_flavor="bigquery",
            sql_flavor_code="bigquery",
            project_db="from-the-column",
            service_account_key={"project_id": "from-the-key"},
        )
    )
    assert formatted["project_db"] == "from-the-column"
