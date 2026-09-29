"""Shared connection domain helpers, reusable from the connections pages and from MCP
without forking SQL templates or per-flavor rules.

Flavor-aware helpers operating on a ``Connection`` by column / flag (no user-facing
labels — those are presentation):

* ``ConnectionStatus`` + ``test_connection_status`` — open an external connection
  and report success / failure with driver-text details.
* ``enforce_connection_rules`` — raise on a connection that cannot be saved as posted,
  then scrub the credential columns its auth mode doesn't use.
* ``apply_connection_defaults`` — pre-save fill of flavor-dependent defaults the
  caller didn't supply.

Wire-protocol helpers operating on a posted payload before it reaches a ``Connection``.
A credential field reaches the browser as ``MASKED_VALUE`` and comes back either
untouched, typed over, or carrying ``CLEAR_SENTINEL`` to empty what is stored:

* ``is_pristine`` — whether a posted credential field came back untouched.
* ``merge_posted_secrets`` — fold a posted ``secrets`` set over the stored one, so a
  payload carrying only the keys someone typed does not drop the rest.

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
from testgen.common.database.flavor.flavor_service import FlavorConnectionError, resolve_connection_params
from testgen.common.flavors import fixed_max_threads
from testgen.common.models.connection import DEFAULT_MAX_QUERY_CHARS, Connection
from testgen.ui.services.database_service import target_db_session

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
        with target_db_session(connection, table_group=None) as session:
            results = session(flavor_service.test_query)
            if not (len(results) == 1 and next(iter(results[0].values())) == 1):
                return ConnectionStatus(message="Error completing a test query against the data source.", successful=False)
            details = flavor_service.test_connection_details(
                session.connection, resolve_connection_params(connection.to_dict())
            )
        return ConnectionStatus(message="The connection was successful.", details=details, successful=True)
    except FlavorConnectionError as error:
        # The flavor wrote this for the user, so it is shown instead of a generic failure.
        LOG.info(f"Connection test failed: {error}")
        return ConnectionStatus(message="Error attempting the connection.", details=str(error), successful=False)
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


CLEAR_SENTINEL = "<clear>"
"""Posted in a credential field to mean "empty the stored value", as distinct from leaving it alone."""

MASKED_VALUE = "***"
"""Stands in for a stored credential in any payload sent to the browser."""


def is_pristine(value: object) -> bool:
    """True when a posted credential field was left as delivered rather than typed into."""
    return value in ("", MASKED_VALUE)


def merge_posted_secrets(posted: dict, stored: Connection | None = None) -> None:
    """Fold a posted ``secrets`` entry into ``stored``'s, rewriting ``posted`` in place.

    An untouched value -- blank, the mask, or ``None`` -- keeps the stored secret,
    ``CLEAR_SENTINEL`` drops it, anything else replaces it. Nothing stored is kept when the
    payload changes the ``sql_flavor_code``. A payload carrying no ``secrets`` entry is left alone.
    """
    if "secrets" not in posted:
        return

    # A secret stored for another connection type fails validation for this one, and the form has
    # no field that could clear it.
    same_type = stored is not None and posted.get("sql_flavor_code", stored.sql_flavor_code) == stored.sql_flavor_code
    merged = dict((stored.secrets if same_type else None) or {})
    for key, raw in (posted["secrets"] or {}).items():
        value = raw.strip() if isinstance(raw, str) else raw
        if value == CLEAR_SENTINEL:
            merged.pop(key, None)
        elif value is not None and not is_pristine(value):
            merged[key] = value
    posted["secrets"] = merged or None


def enforce_connection_rules(connection: Connection) -> None:
    """Enforce the rules a connection must satisfy to be saved or used.

    First drops the ``parameters`` and ``secrets`` values the flavor's auth mode does not read.
    Raises ``ValueError`` on the first rule a connection breaks: a flavor's ``parameters``
    or ``secrets`` not matching its declared shape or missing what its auth mode needs, or a
    combination of auth flags that cannot work. Then clears the credential columns the chosen
    auth mode does not use, so flipping between modes leaves no stale opposite-mode values
    behind. Databricks OAuth stores the client secret in ``project_pw_encrypted`` despite
    ``connect_by_key=True``, so it sticks with the password path. Finally pins ``max_threads``
    for a flavor that fixes it.
    """
    code = connection.sql_flavor_code

    flavor_service = get_flavor_service(connection.sql_flavor)
    connection.parameters, connection.secrets = flavor_service.scrub_settings(
        connection.parameters, connection.secrets, code
    )
    flavor_service.validate_settings(connection.parameters, connection.secrets, code)

    if (threads := fixed_max_threads(code)) is not None:
        connection.max_threads = threads

    if connection.connect_with_identity and connection.connect_with_service_principal:
        raise ValueError(
            "connect_with_identity and connect_with_service_principal are mutually exclusive; "
            "only one Entra ID auth mode can be active."
        )
    if connection.connect_with_service_principal and code not in ("azure_mssql", "synapse_mssql", "onelake_mssql"):
        raise ValueError(
            "connect_with_service_principal is only supported for the Azure SQL Database "
            "(azure_mssql), Azure Synapse Analytics (synapse_mssql), and OneLake (onelake_mssql) flavors."
        )
    if connection.connect_with_service_principal and connection.connect_by_url:
        # URL-mode connect skips the ODBC driver-keyword machinery where
        # ``Authentication=ActiveDirectoryServicePrincipal`` is set, so SPN + URL
        # silently degrades to SQL login.
        raise ValueError(
            "connect_with_service_principal cannot be combined with connect_by_url; "
            "Service Principal auth requires the Host / Port / Database fields, not a URL."
        )
    if connection.connect_with_service_principal:
        halves = (connection.project_user or "").split("@")
        if len(halves) != 2 or not all(part.strip() for part in halves):
            raise ValueError(
                "connect_with_service_principal requires project_user to be "
                "``<client-id>@<tenant-id>`` with non-empty parts."
            )

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
