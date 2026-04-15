import os
import typing
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


MIXPANEL_URL: str = "https://api.mixpanel.com"
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

ANALYTICS_JOB_SOURCE: str = getenv("TG_JOB_SOURCE", "CLI")
"""
Identifies the job trigger for analytics purposes.
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

MCP_PORT: int = int(getenv("TG_MCP_PORT", "8510"))
"""
Port for the MCP server.

from env variable: `TG_MCP_PORT`
defaults to: `8510`
"""

MCP_HOST: str = getenv("TG_MCP_HOST", "0.0.0.0")  # noqa: S104
"""
Host for the MCP server.

from env variable: `TG_MCP_HOST`
defaults to: `0.0.0.0`
"""

MCP_ENABLED: bool = getenv("TG_MCP_ENABLED", "no").lower() in ("yes", "true")
"""
Enable the MCP server when running `testgen run-app all`.

from env variable: `TG_MCP_ENABLED`
defaults to: `Yes`
"""
