"""Minimal SQLAlchemy dialect for Salesforce Data 360.

Wraps the ``salesforce-cdp-connector`` DB-API 2.0 module so that
SQLAlchemy's ``create_engine`` / ``engine.connect()`` flow works.

The connector speaks PostgreSQL-compatible SQL (Tableau Hyper engine)
but uses HTTP + OAuth instead of a wire protocol, so we inherit from
``DefaultDialect`` rather than ``PGDialect`` to avoid unwanted
introspection queries.
"""

import time

import jwt
from salesforcecdpconnector import authentication_helper as _auth_helper
from salesforcecdpconnector.constants import (
    AUTH_PARAM_ASSERTION,
    AUTH_PARAM_CLIENT_CREDENTIALS_GRANT_TYPE,
    AUTH_PARAM_CLIENT_ID,
    AUTH_PARAM_CLIENT_SECRET,
    AUTH_PARAM_GRANT_TYPE,
    AUTH_PARAM_JWT_GRANT_TYPE,
    AUTH_RESPONSE_ACCESS_TOKEN,
    AUTH_RESPONSE_INSTANCE_URL,
)
from salesforcecdpconnector.exceptions import Error as _CdpError
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.pool import StaticPool


def _format_oauth_failure(grant_label: str, response) -> str:
    """Extract Salesforce's ``error`` / ``error_description`` from an OAuth failure.

    The stock connector discards the response body and surfaces only the HTTP
    status, which leaves users without an actionable signal (e.g. ``user
    hasn't approved this consumer`` vs ``invalid assertion`` vs ``invalid
    grant``). This pulls the body fields out so the error reaches the UI.
    """
    detail = ""
    try:
        body = response.json()
        description = body.get("error_description")
        code = body.get("error")
        if description and code:
            detail = f": {code} — {description}"
        elif description:
            detail = f": {description}"
        elif code:
            detail = f": {code}"
        else:
            detail = f": {response.text[:300]}"
    except ValueError:
        if response.text:
            detail = f": {response.text[:300]}"
    return f"Salesforce {grant_label} authentication failed (HTTP {response.status_code}){detail}"


def _token_by_jwt_bearer_flow(self, login_url, username, client_id, private_key):
    payload = {
        "iss": client_id,
        "exp": int(time.time()) + 3600,
        "aud": login_url,
        "sub": username,
    }
    encoded = jwt.encode(payload, private_key, algorithm="RS256")
    params = {AUTH_PARAM_GRANT_TYPE: AUTH_PARAM_JWT_GRANT_TYPE, AUTH_PARAM_ASSERTION: encoded}
    response = self.session.post(url=login_url + "/services/oauth2/token", params=params)
    if response.status_code == 200:
        access_code = response.json()
        return self._exchange_token(access_code[AUTH_RESPONSE_INSTANCE_URL], access_code[AUTH_RESPONSE_ACCESS_TOKEN])
    raise _CdpError(_format_oauth_failure("JWT Bearer", response))


def _token_by_client_creds_flow(self, login_url, client_id, client_secret):
    params = {
        AUTH_PARAM_GRANT_TYPE: AUTH_PARAM_CLIENT_CREDENTIALS_GRANT_TYPE,
        AUTH_PARAM_CLIENT_ID: client_id,
        AUTH_PARAM_CLIENT_SECRET: client_secret,
    }
    response = self.session.post(url=login_url + "/services/oauth2/token", params=params)
    if response.status_code == 200:
        access_code = response.json()
        return self._exchange_token(access_code[AUTH_RESPONSE_INSTANCE_URL], access_code[AUTH_RESPONSE_ACCESS_TOKEN])
    raise _CdpError(_format_oauth_failure("Client Credentials", response))


# Replace the connector's auth methods at import time. The stock methods build
# the same request but throw away the response body on failure. The patched
# methods preserve SF's ``error_description`` so the cause is visible in the
# Test Connection UI and in application logs.
_auth_helper.AuthenticationHelper._token_by_jwt_bearer_flow = _token_by_jwt_bearer_flow
_auth_helper.AuthenticationHelper._token_by_client_creds_flow = _token_by_client_creds_flow


class _DBAPIShim:
    """Shim module that satisfies SQLAlchemy's ``dialect.dbapi()`` contract.

    SQLAlchemy expects ``dbapi.connect(**kwargs)`` to return a DB-API
    connection.  We delegate to ``SalesforceCDPConnection``.
    """

    # Re-export the connector's exception hierarchy so SQLAlchemy can
    # catch errors through the standard ``dbapi.Error`` path.
    from salesforcecdpconnector.exceptions import (
        DatabaseError,
        Error,
        InterfaceError,
        InternalError,
        NotSupportedError,
        OperationalError,
        ProgrammingError,
    )

    paramstyle = "format"  # SQLAlchemy needs *some* value; we never actually bind params

    @staticmethod
    def connect(**kwargs):
        from salesforcecdpconnector.connection import SalesforceCDPConnection

        conn = SalesforceCDPConnection(**kwargs)
        # Patch the cursor factory to add missing DB-API attributes
        _original_cursor = conn.cursor

        def _patched_cursor():
            cursor = _original_cursor()
            if not hasattr(cursor, "rowcount"):
                cursor.rowcount = -1
            if not hasattr(cursor, "lastrowid"):
                cursor.lastrowid = None
            return cursor

        conn.cursor = _patched_cursor
        return conn


class SalesforceData360Dialect(DefaultDialect):
    name = "salesforce_data360"
    supports_alter = False
    supports_transactions = False
    supports_native_boolean = True
    supports_statement_cache = False
    supports_default_values = False
    supports_empty_insert = False
    postfetch_lastrowid = False
    implicit_returning = False

    @classmethod
    def dbapi(cls):
        return _DBAPIShim

    @classmethod
    def import_dbapi(cls):
        return _DBAPIShim

    def create_connect_args(self, _url):
        # All auth params arrive via connect_args; the URL is a dummy
        # ``salesforce_data360://`` placeholder.
        return ([], {})

    def do_ping(self, _dbapi_connection):
        return True

    def initialize(self, connection):
        # Skip server-version detection and other introspection that
        # DefaultDialect.initialize() performs.
        pass

    def get_pool_class(self, _url):
        return StaticPool
