"""Tests for the per-flavor encrypted ``connections.secrets`` column.

Covers the shape check, the partial-payload merge, and the carrier that hands a decrypted
set to connect time. Masking is covered in ``tests/unit/ui/test_connection_masking.py``.
"""

from unittest.mock import MagicMock, patch

import pytest

from testgen.common.database.connection_service import (
    CLEAR_SENTINEL,
    MASKED_VALUE,
    merge_posted_secrets,
)
from testgen.common.database.flavor.flavor_service import (
    ConnectionField,
    FlavorService,
    ResolvedConnectionParams,
    resolve_connection_params,
)
from testgen.common.models.connection import Connection

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


class _SecretiveFlavor(FlavorService):
    """Flavor declaring a secrets shape, which no shipping flavor does."""

    secrets_schema = (
        ConnectionField(key="access_key_id", label="Access Key ID", required=True),
        ConnectionField(key="session_token", label="Session Token"),
    )

    def get_connection_string(self, params: ResolvedConnectionParams) -> str:  # noqa: ARG002
        return ""


# ---------------------------------------------------------------------------
# validate_secrets
# ---------------------------------------------------------------------------


def test_validate_secrets_accepts_a_complete_shape():
    _SecretiveFlavor().validate_secrets({"access_key_id": "AKIA", "session_token": "tok"})


def test_validate_secrets_accepts_only_the_required_entry():
    _SecretiveFlavor().validate_secrets({"access_key_id": "AKIA"})


def test_validate_secrets_rejects_an_undeclared_key_by_name():
    with pytest.raises(ValueError, match="'nope' is not a connection secret"):
        _SecretiveFlavor().validate_secrets({"access_key_id": "AKIA", "nope": "x"})


@pytest.mark.parametrize("value", [None, "", "   "])
def test_validate_secrets_rejects_a_blank_required_entry_by_label(value):
    with pytest.raises(ValueError, match="Access Key ID is required."):
        _SecretiveFlavor().validate_secrets({"access_key_id": value})


def test_validate_secrets_rejects_a_missing_required_entry_by_label():
    with pytest.raises(ValueError, match="Access Key ID is required."):
        _SecretiveFlavor().validate_secrets({})


@pytest.mark.parametrize("secrets", [None, {}])
def test_validate_secrets_accepts_nothing_for_a_flavor_declaring_none(secrets):
    """Every flavor shipping today declares no secrets, so both shapes have to pass."""
    FlavorService().validate_secrets(secrets)


def test_validate_secrets_rejects_a_stray_key_for_a_flavor_declaring_none():
    with pytest.raises(ValueError, match="'anything' is not a connection secret"):
        FlavorService().validate_secrets({"anything": "x"})


# ---------------------------------------------------------------------------
# merge_posted_secrets
# ---------------------------------------------------------------------------


def test_merge_leaves_a_payload_without_secrets_untouched():
    posted = {"project_host": "db.example.com"}
    merge_posted_secrets(posted, _conn(secrets={"access_key_id": "AKIA"}))
    assert "secrets" not in posted


def test_merge_keeps_a_stored_secret_the_payload_omits():
    posted = {"secrets": {"session_token": "fresh"}}
    merge_posted_secrets(posted, _conn(secrets={"access_key_id": "AKIA", "session_token": "old"}))
    assert posted["secrets"] == {"access_key_id": "AKIA", "session_token": "fresh"}


@pytest.mark.parametrize("untouched", ["", "   ", MASKED_VALUE])
def test_merge_keeps_a_stored_secret_the_payload_leaves_blank(untouched):
    posted = {"secrets": {"access_key_id": untouched}}
    merge_posted_secrets(posted, _conn(secrets={"access_key_id": "AKIA"}))
    assert posted["secrets"] == {"access_key_id": "AKIA"}


def test_merge_replaces_a_stored_secret_the_payload_supplies():
    posted = {"secrets": {"access_key_id": "AKIA-NEW"}}
    merge_posted_secrets(posted, _conn(secrets={"access_key_id": "AKIA-OLD"}))
    assert posted["secrets"] == {"access_key_id": "AKIA-NEW"}


def test_merge_trims_a_supplied_secret():
    posted = {"secrets": {"access_key_id": "  AKIA  "}}
    merge_posted_secrets(posted, _conn())
    assert posted["secrets"] == {"access_key_id": "AKIA"}


def test_merge_drops_a_secret_the_payload_clears():
    posted = {"secrets": {"session_token": CLEAR_SENTINEL}}
    merge_posted_secrets(posted, _conn(secrets={"access_key_id": "AKIA", "session_token": "old"}))
    assert posted["secrets"] == {"access_key_id": "AKIA"}


def test_merge_yields_none_when_nothing_survives():
    """A flavor storing no secrets keeps a NULL column rather than an empty object."""
    posted = {"secrets": {}}
    merge_posted_secrets(posted, _conn())
    assert posted["secrets"] is None


def test_merge_without_a_stored_connection_takes_the_payload():
    posted = {"secrets": {"access_key_id": "AKIA", "session_token": ""}}
    merge_posted_secrets(posted)
    assert posted["secrets"] == {"access_key_id": "AKIA"}


def test_merge_tolerates_a_connection_with_no_stored_secrets():
    posted = {"secrets": {"access_key_id": "AKIA"}}
    merge_posted_secrets(posted, _conn(secrets=None))
    assert posted["secrets"] == {"access_key_id": "AKIA"}


# ---------------------------------------------------------------------------
# Connect-time delivery
# ---------------------------------------------------------------------------


def test_resolve_connection_params_carries_secrets_through():
    resolved = resolve_connection_params(
        {"sql_flavor": "postgresql", "secrets": {"access_key_id": "AKIA"}}
    )
    assert resolved.secrets == {"access_key_id": "AKIA"}


def test_resolve_connection_params_defaults_secrets_to_an_empty_mapping():
    """Every flavor shipping today stores none, so the carrier has to tolerate NULL."""
    assert resolve_connection_params({"sql_flavor": "postgresql"}).secrets == {}
    assert resolve_connection_params({"sql_flavor": "postgresql", "secrets": None}).secrets == {}


def test_a_connections_secrets_reach_resolve_through_to_dict():
    connection = _conn(secrets={"access_key_id": "AKIA"})
    assert resolve_connection_params(connection.to_dict()).secrets == {"access_key_id": "AKIA"}


# ---------------------------------------------------------------------------
# enforce_connection_rules wiring
# ---------------------------------------------------------------------------


def test_enforce_connection_rules_validates_secrets():
    from testgen.common.database import connection_service

    flavor_service = MagicMock()
    with patch.object(connection_service, "get_flavor_service", return_value=flavor_service):
        connection = _conn(parameters={"a": 1}, secrets={"b": 2})
        connection_service.enforce_connection_rules(connection)

    flavor_service.validate_parameters.assert_called_once_with({"a": 1})
    flavor_service.validate_secrets.assert_called_once_with({"b": 2})


def test_enforce_connection_rules_surfaces_a_secrets_failure():
    from testgen.common.database import connection_service

    flavor_service = MagicMock()
    flavor_service.validate_secrets.side_effect = ValueError("Access Key ID is required.")
    with (
        patch.object(connection_service, "get_flavor_service", return_value=flavor_service),
        pytest.raises(ValueError, match="Access Key ID is required."),
    ):
        connection_service.enforce_connection_rules(_conn())
