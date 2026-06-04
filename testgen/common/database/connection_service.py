"""Shared connection domain helpers — moved out of the Streamlit connections page
so MCP and any future caller can reuse identical test/normalize logic without
forking SQL templates or per-flavor rules.

Two pieces live here, both flavor-aware and both operating on a ``Connection`` by
column / flag (no user-facing labels — those are presentation):

* ``ConnectionStatus`` + ``test_connection_status`` — open an external connection
  and report success / failure with driver-text details.
* ``normalize_auth_fields`` — pre-save scrub of mutually-exclusive credential
  columns so flipping auth modes doesn't leave orphan values behind.
* ``apply_connection_defaults`` — pre-save fill of flavor-dependent defaults the
  caller didn't supply.

The MCP-facing connection-parameter contract (field labels, modes, requirement
rules, validation) is presentation/input vocabulary and lives in
``mcp/tools/common.py``; flavor display labels live in ``common/flavors.py``.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from sqlalchemy.exc import DatabaseError, DBAPIError

from testgen.common.database.database_service import empty_cache, get_flavor_service
from testgen.common.models.connection import DEFAULT_MAX_QUERY_CHARS, Connection
from testgen.ui.services.database_service import fetch_from_target_db

try:
    from pyodbc import Error as PyODBCError
except ImportError:
    PyODBCError = None

LOG = logging.getLogger("testgen")


# ---------------------------------------------------------------------------
# ConnectionStatus + test runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    message: str
    successful: bool
    details: str | None = field(default=None)
    # Streamlit's reactive system suppresses re-renders when a frozen dataclass
    # compares equal to its previous value. A random per-instance field forces
    # ``__eq__`` to differ so repeated "Test Connection" clicks producing the
    # same error message still re-render the alert. This field has no consumer
    # outside the UI re-render path; do NOT delete it as cleanup.
    _: float = field(default_factory=random.random)


def is_open_ssl_error(error: Exception) -> bool:
    return (
        bool(error.args)
        and len(error.args) > 1
        and isinstance(error.args[1], list)
        and len(error.args[1]) > 0
        and type(error.args[1][0]).__name__ == "OpenSSLError"
    )


def test_connection_status(connection: Connection) -> ConnectionStatus:
    """Open the connection, run the flavor's smoke query, classify the outcome."""
    # Drop pooled engines so the next checkout reflects any credential changes.
    empty_cache()
    try:
        flavor_service = get_flavor_service(connection.sql_flavor)
        results = fetch_from_target_db(connection, flavor_service.test_query)
        connection_successful = len(results) == 1 and next(iter(results[0].values())) == 1

        if not connection_successful:
            return ConnectionStatus(message="Error completing a query to the database server.", successful=False)
        return ConnectionStatus(message="The connection was successful.", successful=True)
    except KeyError:
        return ConnectionStatus(
            message="Error attempting the connection. ",
            details="Complete all the required fields.",
            successful=False,
        )
    except DatabaseError as error:
        LOG.exception("Error testing database connection")
        return ConnectionStatus(message="Error attempting the connection.", details=str(error.orig), successful=False)
    except DBAPIError as error:
        LOG.exception("Error testing database connection")
        details = str(error.orig)
        if PyODBCError and isinstance(error.orig, PyODBCError) and error.orig.args:
            details = error.orig.args[1]
        return ConnectionStatus(message="Error attempting the connection.", details=details, successful=False)
    except (TypeError, ValueError) as error:
        LOG.exception("Error testing database connection")
        details = str(error)
        if is_open_ssl_error(error):
            details = error.args[0]
        return ConnectionStatus(message="Error attempting the connection.", details=details, successful=False)
    except Exception:
        details = "Something went wrong while testing the connection."
        if connection.connect_by_key and not connection.private_key:
            details = "The private key is missing."
        LOG.exception("Error testing database connection")
        return ConnectionStatus(message="Error attempting the connection.", details=details, successful=False)


# ---------------------------------------------------------------------------
# Auth-path normalization
# ---------------------------------------------------------------------------


def normalize_auth_fields(connection: Connection) -> None:
    """Clear credential columns the active auth mode doesn't use.

    Mirrors the UI's pre-save scrub at ``ui/views/connections.py`` so flipping
    auth modes doesn't leave stale opposite-mode values behind. Databricks OAuth
    stores the client secret in ``project_pw_encrypted`` despite
    ``connect_by_key=True``, so it sticks with the password path.
    """
    code = connection.sql_flavor_code

    uses_private_key = bool(connection.connect_by_key) and code != "databricks"
    if uses_private_key:
        connection.project_pw_encrypted = None
    else:
        connection.private_key = None
        connection.private_key_passphrase = None

    if connection.connect_with_identity:
        connection.project_user = None
        connection.project_pw_encrypted = None


# ---------------------------------------------------------------------------
# Flavor-dependent defaults
# ---------------------------------------------------------------------------


def apply_connection_defaults(connection: Connection) -> None:
    """Fill flavor-dependent defaults for fields the caller didn't supply."""
    if connection.max_query_chars is None:
        # Salesforce Data 360's Hyper engine has a lower expression-depth limit
        connection.max_query_chars = 15000 if connection.sql_flavor_code == "salesforce_data360" else DEFAULT_MAX_QUERY_CHARS
