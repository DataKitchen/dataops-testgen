import os
import typing
from enum import StrEnum
from pathlib import Path


def _load_config() -> dict[str, str]:
    """Load ``$TG_TESTGEN_HOME/config.env`` (default ``~/.testgen/config.env``)."""
    home = Path(os.environ["TG_TESTGEN_HOME"]) if "TG_TESTGEN_HOME" in os.environ else Path.home() / ".testgen"
    config_path = home / "config.env"
    config: dict[str, str] = {}
    if config_path.is_file():
        for line in config_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if key:
                config[key] = value
    return config


_config = _load_config()


def getenv(key: str, default: str | None = None) -> str | None:
    """Look up *key* in environment first, then config file, then *default*."""
    return os.environ.get(key) or _config.get(key) or default


IS_DEBUG_LOG_LEVEL: bool = getenv("TESTGEN_DEBUG_LOG_LEVEL", "no").lower() in ("yes", "true")
"""
When set, logs will be at debug level.
defaults to: `no`
"""

IS_DEBUG: bool = getenv("TESTGEN_DEBUG", "no").lower() in ("yes", "true")
"""
When True invalidates the cache with the bootstrapped application
causing the changes to the routing and plugins to take effect on every
render.

from env variable: `TESTGEN_DEBUG`
defaults to: `True`
"""

LOG_TO_FILE: bool = getenv("TESTGEN_LOG_TO_FILE", "yes").lower() in ("yes", "true")
"""
When set, rotating file logs will be generated.
defaults to: `True`
"""

LOG_FILE_PATH: str = getenv("TESTGEN_LOG_FILE_PATH", "/var/lib/testgen/log")
"""
When set, rotating file logs will be generated under this path.

"""

LOG_FILE_MAX_QTY: str = getenv("TESTGEN_LOG_FILE_MAX_QTY", "90")
"""
Maximum log files to keep, defaults to 90 days (one file per day).
"""

APP_ENCRYPTION_SALT: str = getenv("TG_DECRYPT_SALT")
"""
Salt used to encrypt and decrypt user secrets. Only allows ascii
characters.

A minimun length of 16 characters is recommended.

from env variable: `TG_DECRYPT_SALT`
"""

APP_ENCRYPTION_SECRET: str = getenv("TG_DECRYPT_PASSWORD")
"""
Secret passcode used in combination with `APP_ENCRYPTION_SALT` to
encrypt and decrypt user secrets. Only allows ascii characters.

from env variable: `TG_DECRYPT_PASSWORD`
"""

USERNAME: str = getenv("TESTGEN_USERNAME")
"""
Username to log into the web application

from env variable: `TESTGEN_USERNAME`
"""

PASSWORD: str = getenv("TESTGEN_PASSWORD")
"""
Password to log into the web application

from env variable: `TESTGEN_PASSWORD`
"""

DATABASE_USER: str = getenv("TG_METADATA_DB_USER", USERNAME)
"""
User to connect to the testgen application postgres database.

from env variable: `TG_METADATA_DB_USER`
defaults to: `environ[USERNAME]`
"""

DATABASE_PASSWORD: str = getenv("TG_METADATA_DB_PASSWORD", PASSWORD)
"""
Password to connect to the testgen application postgres database.

from env variable: `TG_METADATA_DB_PASSWORD`
defaults to: `environ[PASSWORD]`
"""

DATABASE_ADMIN_USER: str = getenv("DATABASE_ADMIN_USER", DATABASE_USER)
"""
User with admin privileges in the testgen application postgres database
used to create roles, users, database and schema. Required if the user
in `TG_METADATA_DB_USER` does not have the required privileges.

from env variable: `DATABASE_ADMIN_USER`
defaults to: `environ[DATABASE_USER]`
"""

DATABASE_ADMIN_PASSWORD: str = getenv("DATABASE_ADMIN_PASSWORD", DATABASE_PASSWORD)
"""
Password for the admin user to connect to the testgen application
postgres database.

from env variable: `DATABASE_ADMIN_PASSWORD`
defaults to: `environ[DATABASE_PASSWORD]`
"""

DATABASE_EXECUTE_USER: str = getenv("DATABASE_EXECUTE_USER", "testgen_execute")
"""
User to be created into the testgen application postgres database. Will
be granted:

_ read/write to tables `test_results`, `test_suites` and `test_definitions`
_ read_only to all other tables

from env variable: `DATABASE_EXECUTE_USER`
defaults to: `testgen_execute`
"""

DATABASE_REPORT_USER: str = getenv("DATABASE_REPORT_USER", "testgen_report")
"""
User to be created into the testgen application postgres database. Will
be granted read_only access to all tables.

from env variable: `DATABASE_REPORT_USER`
defaults to: `testgen_report`
"""

DATABASE_HOST: str = getenv("TG_METADATA_DB_HOST", "localhost")
"""
Hostname where the testgen application postgres database is running in.

from env variable: `TG_METADATA_DB_HOST`
defaults to: `localhost`
"""

DATABASE_PORT: str = getenv("TG_METADATA_DB_PORT", "5432")
"""
Port at which the testgen application postgres database is exposed by
the host.

from env variable: `TG_METADATA_DB_PORT`
defaults to: `5432`
"""

DATABASE_NAME: str = getenv("TG_METADATA_DB_NAME", "datakitchen")
"""
Name of the database in postgres on which to store testgen metadata.

from env variable: `TG_METADATA_DB_NAME`
defaults to: `datakitchen`
"""

DATABASE_SCHEMA: str = getenv("TG_METADATA_DB_SCHEMA", "testgen")
"""
Name of the schema inside the postgres database on which to store
testgen metadata.

from env variable: `TG_METADATA_DB_SCHEMA`
defaults to: `testgen`
"""

_metadata_db_sslmode = getenv("TG_METADATA_DB_SSLMODE")

DATABASE_SSLMODE: str | None = _metadata_db_sslmode.lower() if _metadata_db_sslmode else None
"""
libpq sslmode for the testgen application postgres database: `disable`,
`allow`, `prefer`, `require`, `verify-ca` or `verify-full`. When unset,
libpq's own default applies, which negotiates TLS where the server offers
it but does not verify the server certificate.

`verify-ca` and `verify-full` need a certificate authority, which
`DATABASE_SSLROOTCERT` supplies.

from env variable: `TG_METADATA_DB_SSLMODE`
defaults to: unset
"""

DATABASE_SSLROOTCERT: str = getenv("TG_METADATA_DB_SSLROOTCERT", "system")
"""
Certificate authority used to verify the application postgres database's
server certificate. Either a path to a PEM bundle or `system` for the
operating system's trust store, which carries the authorities that the
managed postgres services chain to.

`system` pairs only with `verify-full`, so `verify-ca` needs a PEM path.
A PEM path suits any mode, and `require` verifies the certificate chain
against it in the same way as `verify-ca`.

from env variable: `TG_METADATA_DB_SSLROOTCERT`
defaults to: `system`
"""


def _database_ssl_connect_args() -> dict[str, str]:
    if not DATABASE_SSLMODE:
        return {}
    args = {"sslmode": DATABASE_SSLMODE}
    # libpq accepts sslrootcert=system only alongside verify-full, and rejects the
    # combination outright rather than ignoring it. A file path suits any mode, and
    # libpq verifies the chain against it, so require plus a mounted authority
    # verifies as verify-ca does.
    if DATABASE_SSLROOTCERT != "system" or DATABASE_SSLMODE == "verify-full":
        args["sslrootcert"] = DATABASE_SSLROOTCERT
    return args


DATABASE_SSL_CONNECT_ARGS: dict[str, str] = _database_ssl_connect_args()
"""
libpq connect arguments carrying the application database's TLS
configuration. Empty when `DATABASE_SSLMODE` is unset.
"""

PROJECT_KEY: str = getenv("PROJECT_KEY", "DEFAULT")
"""
Code used to uniquely identify the auto generated project.

from env variable: `PROJECT_KEY`
defaults to: `DEFAULT`
"""

PROJECT_NAME: str = getenv("PROJECT_NAME", "Demo")
"""
Name to assign to the auto generated project.

from env variable: `DEFAULT_PROJECT_NAME`
defaults to: `Demo`
"""

PROJECT_SQL_FLAVOR: str = getenv("PROJECT_SQL_FLAVOR", "postgresql")
"""
SQL flavor of the database the auto generated project will run tests
against.

Supported flavors are:
_ redshift
_ snowflake
_ mssql
_ postgresql

from env variable: `PROJECT_SQL_FLAVOR`
defaults to: `postgresql`
"""

PROJECT_CONNECTION_NAME: str = getenv("PROJECT_CONNECTION_NAME", "default")
"""
Name assigned to identify the connection to the project database.

from env variable: `PROJECT_CONNECTION_NAME`
defaults to: `default`
"""

PROJECT_CONNECTION_MAX_THREADS: int = int(getenv("PROJECT_CONNECTION_MAX_THREADS", "4"))
"""
Maximum number of concurrent queries executed when fetching data from
the project database.

from env variable: `PROJECT_CONNECTION_MAX_THREADS`
defaults to: `4`
"""

PROJECT_CONNECTION_MAX_QUERY_CHAR: int = int(getenv("PROJECT_CONNECTION_MAX_QUERY_CHAR", "5000"))
"""
Determine how many tests are grouped together in a single query.
Increase for better performance or decrease to better isolate test
failures. Accepted values are 500 to 14 000.

from env variable: `PROJECT_CONNECTION_MAX_QUERY_CHAR`
defaults to: `5000`
"""

PROJECT_DATABASE_NAME: str = getenv("PROJECT_DATABASE_NAME", "demo_db")
"""
Name of the database the auto generated project will run test
against.

from env variable: `PROJECT_DATABASE_NAME`
defaults to: `demo_db`
"""

PROJECT_DATABASE_SCHEMA: str = getenv("PROJECT_DATABASE_SCHEMA", "demo")
"""
Name of the schema inside the project database the tests will be run
against.

from env variable: `PROJECT_DATABASE_SCHEMA`
defaults to: `demo`
"""

PROJECT_DATABASE_USER: str = getenv("PROJECT_DATABASE_USER", DATABASE_USER)
"""
User to be used by the auto generated project to connect to the database
under testing.

from env variable: `PROJECT_DATABASE_USER`
defaults to: `environ[DATABASE_USER]`
"""

PROJECT_DATABASE_PASSWORD: str = getenv("PROJECT_DATABASE_PASSWORD", DATABASE_PASSWORD)
"""
Password to be used by the auto generated project to connect to the
database under testing.

from env variable: `PROJECT_DATABASE_USER`
defaults to: `environ[DATABASE_PASSWORD]`
"""

PROJECT_DATABASE_HOST: str = getenv("PROJECT_DATABASE_HOST", DATABASE_HOST)
"""
Hostname where the database under testing is running in.

from env variable: `PROJECT_DATABASE_HOST`
defaults to: `environ[DATABASE_HOST]`
"""

PROJECT_DATABASE_PORT: str = getenv("PROJECT_DATABASE_PORT", DATABASE_PORT)
"""
Port at which the database under testing is exposed by the host.

from env variable: `PROJECT_DATABASE_PORT`
defaults to: `environ[DATABASE_PORT]`
"""

SKIP_DATABASE_CERTIFICATE_VERIFICATION: bool = getenv("TG_TARGET_DB_TRUST_SERVER_CERTIFICATE", "no").lower() in ("yes", "true")
"""
When True for supported SQL flavors, set up the SQLAlchemy connection to
trust the database server certificate.

from env variable: `TG_TARGET_DB_TRUST_SERVER_CERTIFICATE`
defaults to: `True`
"""

DEFAULT_TABLE_GROUPS_NAME: str = getenv("DEFAULT_TABLE_GROUPS_NAME", "default")
"""
Name assigned to the auto generated table group.

from env variable: `DEFAULT_TABLE_GROUPS_NAME`
defaults to: `default`
"""

DEFAULT_TEST_SUITE_KEY: str = getenv("DEFAULT_TEST_SUITE_NAME", "default-suite-1")
"""
Key to be assgined to the auto generated test suite.

from env variable: `DEFAULT_TEST_SUITE_NAME`
defaults to: `default-suite-1`
"""

DEFAULT_TEST_SUITE_DESCRIPTION: str = getenv("DEFAULT_TEST_SUITE_DESCRIPTION", "default_suite_desc")
"""
Description for the auto generated test suite.

from env variable: `DEFAULT_TEST_SUITE_DESCRIPTION`
defaults to: `default_suite_desc`
"""

DEFAULT_PROFILING_TABLE_SET = getenv("DEFAULT_PROFILING_TABLE_SET", "")
"""
Comma separated list of specific table names to include when running
profiling for the project database.

from env variable: `DEFAULT_PROFILING_TABLE_SET`
"""

DEFAULT_PROFILING_INCLUDE_MASK = getenv("DEFAULT_PROFILING_INCLUDE_MASK", "%")
"""
A SQL filter supported by the project database's `LIKE` operator for
table names to include.

from env variable: `DEFAULT_PROFILING_INCLUDE_MASK`
defaults to: `%`
"""

DEFAULT_PROFILING_EXCLUDE_MASK = getenv("DEFAULT_PROFILING_EXCLUDE_MASK", "tmp%")
"""
A SQL filter supported by the project database's `LIKE` operator for
table names to exclude.

from env variable: `DEFAULT_PROFILING_EXCLUDE_MASK`
defaults to: `tmp%`
"""

DEFAULT_PROFILING_ID_COLUMN_MASK = getenv("DEFAULT_PROFILING_ID_COLUMN_MASK", "%id")
"""
A SQL filter supported by the project database's `LIKE` operator
representing ID columns.

from env variable: `DEFAULT_PROFILING_ID_COLUMN_MASK`
defaults to: `%id`
"""

DEFAULT_PROFILING_SK_COLUMN_MASK = getenv("DEFAULT_PROFILING_SK_COLUMN_MASK", "%sk")
"""
A SQL filter supported by the project database's `LIKE` operator
representing surrogate key columns.

from env variable: `DEFAULT_PROFILING_SK_COLUMN_MASK`
defaults to: `%sk`
"""

DEFAULT_PROFILING_USE_SAMPLING: str = getenv("DEFAULT_PROFILING_USE_SAMPLING", "N")
"""
Toggle on to base profiling on a sample of records instead of the full
table. Accepts `Y` or `N`

from env variable: `DEFAULT_PROFILING_USE_SAMPLING`
defaults to: `N`
"""

OBSERVABILITY_API_URL: str = getenv("OBSERVABILITY_API_URL", "")
"""
API URL of your instance of Observability where to send events to for
the project.

You can configure this from the UI settings page.

from env variable: `OBSERVABILITY_API_URL`
"""

OBSERVABILITY_API_KEY: str = getenv("OBSERVABILITY_API_KEY", "")
"""
Authentication key with permissions to send events created in your
instance of Observability.

You can configure this from the UI settings page.

from env variable: `OBSERVABILITY_API_KEY`
"""

OBSERVABILITY_VERIFY_SSL: bool = getenv("TG_EXPORT_TO_OBSERVABILITY_VERIFY_SSL", "yes").lower() in ("yes", "true")
"""
When False, exporting events to your instance of Observability will skip
SSL verification.

from env variable: `TG_EXPORT_TO_OBSERVABILITY_VERIFY_SSL`
defaults to: `True`
"""

OBSERVABILITY_EXPORT_LIMIT: int = int(getenv("TG_OBSERVABILITY_EXPORT_MAX_QTY", "5000"))
"""
When exporting to your instance of Observability, the maximum number of
events that will be sent to the events API on a single export.

from env variable: `TG_OBSERVABILITY_EXPORT_MAX_QTY`
defaults to: `5000`
"""

OBSERVABILITY_DEFAULT_COMPONENT_TYPE: str = getenv("OBSERVABILITY_DEFAULT_COMPONENT_TYPE", "dataset")
"""
When exporting to your instance of Observability, the type of event that
will be sent to the events API.

from env variable: `OBSERVABILITY_DEFAULT_COMPONENT_TYPE`
defaults to: `dataset`
"""

OBSERVABILITY_DEFAULT_COMPONENT_KEY: str = getenv("OBSERVABILITY_DEFAULT_COMPONENT_KEY", "default")
"""
When exporting to your instance of Observability, the key sent to the
events API to identify the components.

from env variable: `OBSERVABILITY_DEFAULT_COMPONENT_KEY`
defaults to: `default`
"""

CHECK_FOR_LATEST_VERSION: typing.Literal["pypi", "docker"] = typing.cast(
    typing.Literal["pypi", "docker"],
    getenv("TG_RELEASE_CHECK", "pypi").lower(),
)
"""
Specifies whether the latest version check should be based on PyPI or DockerHub.
"""

DOCKER_HUB_REPOSITORY: str = getenv(
    "TESTGEN_DOCKER_HUB_REPO",
    "datakitchen/dataops-testgen",
)
"""
URL to the docker hub repository containing the dataops testgen image.
Used to check for new releases when `CHECK_FOR_LATEST_VERSION` is set to
`docker`.
"""

VERSION: str = getenv("TESTGEN_VERSION", None)
"""
Current deployed version. The value is displayed in the UI menu.
"""

SUPPORT_EMAIL: str = getenv("TESTGEN_SUPPORT_EMAIL", "open-source-support@datakitchen.io")
"""
Email for contacting DataKitchen support.
"""

SSL_CERT_FILE: str = getenv("SSL_CERT_FILE", "")
SSL_KEY_FILE: str = getenv("SSL_KEY_FILE", "")
"""
File paths for SSL certificate and private key to support HTTPS.
Both files must be provided.
"""


def _ssl_files_present() -> bool:
    return bool(SSL_CERT_FILE) and os.path.isfile(SSL_CERT_FILE) and bool(SSL_KEY_FILE) and os.path.isfile(SSL_KEY_FILE)


_ui_tls_env = getenv("TG_UI_TLS_ENABLED", "").lower()
UI_TLS_ENABLED: bool = _ui_tls_env in ("yes", "true") if _ui_tls_env else _ssl_files_present()
"""
Enable TLS for the Streamlit UI server.
When not set, auto-detects from SSL_CERT_FILE / SSL_KEY_FILE presence.

from env variable: `TG_UI_TLS_ENABLED`
defaults to: auto-detect
"""

_api_tls_env = getenv("TG_API_TLS_ENABLED", "").lower()
API_TLS_ENABLED: bool = _api_tls_env in ("yes", "true") if _api_tls_env else _ssl_files_present()
"""
Enable TLS for the API/MCP server (uvicorn).
When not set, auto-detects from SSL_CERT_FILE / SSL_KEY_FILE presence.

from env variable: `TG_API_TLS_ENABLED`
defaults to: auto-detect
"""


MIXPANEL_URL: str = getenv("TG_MIXPANEL_URL", "https://api.mixpanel.com")
MIXPANEL_TIMEOUT: int = 3
MIXPANEL_TOKEN: str = "973680ddf8c2b512e6f6d1f2959149eb"
"""
Mixpanel configuration
"""

INSTANCE_ID: str | None = getenv("TG_INSTANCE_ID", None)
"""
Random ID that uniquely identifies the instance.
"""

ANALYTICS_ENABLED: bool = getenv("TG_ANALYTICS", "yes").lower() in ("yes", "true")
"""
Disables sending usage data when set to any value except "true" and "yes". Defaults to "yes"
"""

DISABLE_FEEDBACK_POPUP: bool = getenv("TG_DISABLE_FEEDBACK_POPUP", "no").lower() in ("yes", "true")
"""
When set to "yes" or "true", suppresses the periodic feedback popup entirely.

from env variable: `TG_DISABLE_FEEDBACK_POPUP`
defaults to: `no`
"""

JOB_POLL_INTERVAL: int = int(getenv("TG_JOB_POLL_INTERVAL", "5"))
"""
Seconds between polls for pending job executions.
from env variable: 'TG_JOB_POLL_INTERVAL'
defaults to: 5
"""

JOB_PAUSE_CHECK_INTERVAL: int = int(getenv("TG_JOB_PAUSE_CHECK_INTERVAL", "5"))
"""
Seconds a running job caches the answer to "have I been asked to stop" before asking the
database again. Bounds how long a job takes to notice the request.

from env variable: 'TG_JOB_PAUSE_CHECK_INTERVAL'
defaults to: 5
"""

JOB_SHUTDOWN_TIMEOUT: int = int(getenv("TG_JOB_SHUTDOWN_TIMEOUT", "60"))
"""
Seconds the scheduler waits for running jobs to stop before it exits anyway. Must stay below
the runtime's stop grace period, or the container is killed mid-wait and jobs that would have
stopped cleanly are cut instead. A job that outlives this is left for the next start to settle.

from env variable: 'TG_JOB_SHUTDOWN_TIMEOUT'
defaults to: 60
"""

JOB_TERMINATE_TIMEOUT: int = int(getenv("TG_JOB_TERMINATE_TIMEOUT", "10"))
"""
Seconds a canceled job's process is given to exit after SIGTERM before it is killed.
A job process that installs no handler is terminated by the signal itself, so this bounds the
cases that do: a handler that runs cleanup, or a process the kernel cannot deliver to promptly.

from env variable: 'TG_JOB_TERMINATE_TIMEOUT'
defaults to: 10
"""

ACCESS_TOKEN_EXPIRES_IN: int = 3600  # 1 hour
REFRESH_TOKEN_EXPIRES_IN: int = 2_592_000  # 30 days
"""
Lifetime of OAuth access and refresh tokens.
"""

PAT_DEFAULT_LIFETIME_SECONDS: int = 31_536_000  # 365 days
"""
Default maximum lifetime a personal access token can be created with.
"""

PAT_MAX_LIFETIME_SECONDS: int = 63_072_000  # 2 years (730 days)
"""
Absolute ceiling on the admin-configurable personal access token maximum lifetime.
The configured maximum cannot exceed this.
"""

JWT_HASHING_KEY_B64: str = getenv("TG_JWT_HASHING_KEY")
"""
Random key used to sign/verify the authentication token
"""

ISSUE_REPORT_SOURCE_DATA_LOOKUP_LIMIT: int = getenv("TG_ISSUE_REPORT_SOURCE_DATA_LOOKUP_LIMIT", 50)
"""
Limit the number of records used to generate the PDF with test results and hygiene issue reports.
"""

EMAIL_FROM_ADDRESS: str | None = getenv("TG_EMAIL_FROM_ADDRESS")
"""
Email: Sender address
"""

SMTP_ENDPOINT: str | None = getenv("TG_SMTP_ENDPOINT")
"""
Email: SMTP endpoint
"""

SMTP_PORT: int | None = int(getenv("TG_SMTP_PORT", 0)) or None
"""
Email: SMTP port
"""

SMTP_USERNAME: str | None = getenv("TG_SMTP_USERNAME")
"""
Email: SMTP username
"""

SMTP_PASSWORD: str | None = getenv("TG_SMTP_PASSWORD")
"""
Email: SMTP password
"""


class SMTPSecurity(StrEnum):
    """How the SMTP connection that sends notification emails is secured."""
    SSL = "ssl"
    STARTTLS = "starttls"
    NONE = "none"


SMTP_SECURITY: str = getenv("TG_SMTP_SECURITY", SMTPSecurity.SSL).lower()
"""
Email: how the SMTP connection is secured.

`ssl` wraps the connection in TLS from the first byte, which servers on port 465
expect. `starttls` opens the connection in plaintext and issues the STARTTLS
command to upgrade it, which servers on port 587 or 25 expect. `none` leaves the
connection unencrypted.

Typed as `str` rather than `SMTPSecurity` so that an unrecognized value is
reported when email is sent, naming the values that are accepted, instead of
raising on import and failing every `testgen` command.

from env variable: `TG_SMTP_SECURITY`
defaults to: `ssl`
"""

SMTP_CLIENT_CERT_FILE: str = getenv("TG_SMTP_CLIENT_CERT_FILE", "")
SMTP_CLIENT_KEY_FILE: str = getenv("TG_SMTP_CLIENT_KEY_FILE", "")
"""
Email: file paths for the TLS client certificate and private key presented to the
SMTP server, for a relay that authorizes the sender by certificate rather than by
username and password. Both files must be provided.

from env variables: `TG_SMTP_CLIENT_CERT_FILE`, `TG_SMTP_CLIENT_KEY_FILE`
defaults to: unset
"""

SMTP_CLIENT_KEY_PASSWORD: str = getenv("TG_SMTP_CLIENT_KEY_PASSWORD", "")
"""
Email: passphrase for `TG_SMTP_CLIENT_KEY_FILE`, when the key is encrypted.

Passed to OpenSSL exactly as set. An empty value must not be turned into `None`,
which makes OpenSSL prompt for a passphrase on the terminal and block the send.
An unencrypted key ignores the value; an encrypted key with none set fails to load.

from env variable: `TG_SMTP_CLIENT_KEY_PASSWORD`
defaults to: unset
"""

WEBHOOK_ALLOWED_HOSTS: str | None = getenv("TG_WEBHOOK_ALLOWED_HOSTS")
"""
Webhook: comma-separated allow-list of hostnames or CIDR ranges permitted as
webhook destination targets, in addition to the default public ranges.

Empty by default. Entries take priority over the reserved-range refusal rules,
so an internal chat server or a pipeline gate can be reached explicitly without
opening the whole internal network.
"""

MCP_ENABLED: bool = getenv("TG_MCP_ENABLED", "yes").lower() in ("yes", "true")
"""
Enable the MCP server when running `testgen run-app all`.

from env variable: `TG_MCP_ENABLED`
defaults to: `yes`
"""

MCP_SOURCE_DATA_PROTECTION: str = getenv("TG_MCP_SOURCE_DATA_PROTECTION", "off")
"""
Protection level for source-derived data values returned by the MCP server.
`strict` withholds them; `off` allows them. An unrecognized value resolves to
`strict`, so a typo cannot silently disable the protection. Changing this
requires an MCP server restart.

from env variable: `TG_MCP_SOURCE_DATA_PROTECTION`
defaults to: `off`
"""

UI_PORT: int = int(getenv("TG_UI_PORT", "8501"))
"""
Port for the UI server.

from env variable: `TG_UI_PORT`
defaults to: `8501`
"""

API_PORT: int = int(getenv("TG_API_PORT", "8530"))
"""
Port for the API server.

from env variable: `TG_API_PORT`
defaults to: `8530`
"""

API_HOST: str = getenv("TG_API_HOST", "0.0.0.0")  # noqa: S104
"""
Host for the API server.

from env variable: `TG_API_HOST`
defaults to: `0.0.0.0`
"""

def _default_base_url() -> str:
    scheme = "https" if API_TLS_ENABLED else "http"
    return f"{scheme}://localhost:{API_PORT}"


BASE_URL: str = getenv("TG_BASE_URL", "") or _default_base_url()
"""
Externally-reachable base URL for the API/MCP/OAuth server.

from env variable: `TG_BASE_URL`
defaults to: computed from API_TLS_ENABLED and API_PORT
"""


def _default_ui_base_url() -> str:
    scheme = "https" if UI_TLS_ENABLED else "http"
    return f"{scheme}://localhost:{UI_PORT}"


UI_BASE_URL: str = getenv("TG_UI_BASE_URL", "") or _default_ui_base_url()
"""
Externally-reachable base URL for the Streamlit UI (used in email links, PDFs).

from env variable: `TG_UI_BASE_URL`
defaults to: computed from UI_TLS_ENABLED and UI_PORT
"""

MCP_EXTRA_ALLOWED_HOSTS: list[str] = [
    h.strip() for h in (getenv("TG_MCP_EXTRA_ALLOWED_HOSTS", "") or "").split(",") if h.strip()
]
"""
Extra Host header values accepted by MCP DNS rebinding protection (comma-separated).
BASE_URL's hostname and loopback are always allowed; this adds more for multi-domain
deployments or reverse proxies that rewrite Host. Entries without a port (`tg.example.com`)
are allowed both with an automatic `:*` port wildcard and bare, so gateways that send an
Origin with no port are accepted; entries with a port are matched literally
(`tg.example.com:8080`) or with explicit wildcard (`tg.example.com:*`).
Only affects MCP routes — the parent FastAPI app does not validate Host headers.

from env variable: `TG_MCP_EXTRA_ALLOWED_HOSTS`
defaults to: empty (BASE_URL hostname + loopback only)
"""

API_MAX_REQUEST_BODY_BYTES: int = int(
    getenv("TG_API_MAX_REQUEST_BODY_BYTES", str(10 * 1024 * 1024))
)
"""
Reject HTTP requests larger than this with 413 Payload Too Large.

from env variable: `TG_API_MAX_REQUEST_BODY_BYTES`
defaults to: 10485760 (10 MiB)
"""

API_GRACEFUL_SHUTDOWN_TIMEOUT: int = int(getenv("TG_API_GRACEFUL_SHUTDOWN_TIMEOUT", "30"))
"""
Seconds uvicorn waits for in-flight requests on SIGTERM before force-closing.
Long blocking SQL queries that don't honor asyncio cancellation may be cut mid-flight;
align with the target DB's statement_timeout.

from env variable: `TG_API_GRACEFUL_SHUTDOWN_TIMEOUT`
defaults to: 30
"""

API_HSTS_HEADER: str = getenv("TG_API_HSTS_HEADER", "")
"""
Override HSTS (Strict-Transport-Security) header value. When empty, HSTS is emitted
only when API_TLS_ENABLED with value 'max-age=63072000; includeSubDomains'. Setting
this forces emission regardless of TLS (useful when TLS terminates at a reverse proxy).

from env variable: `TG_API_HSTS_HEADER`
defaults to: empty (auto from API_TLS_ENABLED)
"""

API_CSP_HEADER: str = getenv("TG_API_CSP_HEADER", "frame-ancestors 'none'")
"""
Content-Security-Policy header value. Default restricts framing only; broader policies
risk breaking Redoc at /api/docs which loads CDN assets.

from env variable: `TG_API_CSP_HEADER`
defaults to: `frame-ancestors 'none'`
"""

API_REFERRER_POLICY: str = getenv("TG_API_REFERRER_POLICY", "no-referrer")
"""
Referrer-Policy header value.

from env variable: `TG_API_REFERRER_POLICY`
defaults to: `no-referrer`
"""

DUCKDB_EXTENSION_DIRECTORY: str = getenv("TG_DUCKDB_EXTENSION_DIRECTORY", "")
"""
Directory holding the DuckDB extensions bundled into the container image. Set by the image so
that the bundle location is written once rather than duplicated in code; not a value to change.
Empty on a pip install, where DuckDB falls back to its own location under the user's home.

from env variable: `TG_DUCKDB_EXTENSION_DIRECTORY`
defaults to: empty
"""

