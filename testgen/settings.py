import os
import typing

IS_DEBUG_LOG_LEVEL: bool = os.getenv("TESTGEN_DEBUG_LOG_LEVEL", "no").lower() == "yes"
"""
When set, logs will be at debug level.
defaults to: `no`
"""

IS_DEBUG: bool = os.getenv("TESTGEN_DEBUG", "no").lower() == "yes"
"""
When True invalidates the cache with the bootstrapped application
causing the changes to the routing and plugins to take effect on every
render.

from env variable: `TESTGEN_DEBUG`
defaults to: `True`
"""

LOG_TO_FILE: bool = os.getenv("TESTGEN_LOG_TO_FILE", "yes").lower() == "yes"
"""
When set, rotating file logs will be generated.
defaults to: `True`
"""

LOG_FILE_PATH: str = os.getenv("TESTGEN_LOG_FILE_PATH", "/var/lib/testgen/log")
"""
When set, rotating file logs will be generated under this path.

"""

LOG_FILE_MAX_QTY: str = os.getenv("TESTGEN_LOG_FILE_MAX_QTY", "90")
"""
Maximum log files to keep, defaults to 90 days (one file per day).
"""

APP_ENCRYPTION_SALT: str = os.getenv("TG_DECRYPT_SALT")
"""
Salt used to encrypt and decrypt user secrets. Only allows ascii
characters.

A minimun length of 16 characters is recommended.

from env variable: `TG_DECRYPT_SALT`
"""

APP_ENCRYPTION_SECRET: str = os.getenv("TG_DECRYPT_PASSWORD")
"""
Secret passcode used in combination with `APP_ENCRYPTION_SALT` to
encrypt and decrypt user secrets. Only allows ascii characters.

from env variable: `TG_DECRYPT_PASSWORD`
"""

USERNAME: str = os.getenv("TESTGEN_USERNAME")
"""
Username to log into the web application

from env variable: `TESTGEN_USERNAME`
"""

PASSWORD: str = os.getenv("TESTGEN_PASSWORD")
"""
Password to log into the web application

from env variable: `TESTGEN_PASSWORD`
"""

DATABASE_USER: str = os.getenv("TG_METADATA_DB_USER", USERNAME)
"""
User to connect to the testgen application postgres database.

from env variable: `TG_METADATA_DB_USER`
defaults to: `environ[USERNAME]`
"""

DATABASE_PASSWORD: str = os.getenv("TG_METADATA_DB_PASSWORD", PASSWORD)
"""
Password to connect to the testgen application postgres database.

from env variable: `TG_METADATA_DB_PASSWORD`
defaults to: `environ[PASSWORD]`
"""

DATABASE_ADMIN_USER: str = os.getenv("DATABASE_ADMIN_USER", DATABASE_USER)
"""
User with admin privileges in the testgen application postgres database
used to create roles, users, database and schema. Required if the user
in `TG_METADATA_DB_USER` does not have the required privileges.

from env variable: `DATABASE_ADMIN_USER`
defaults to: `environ[DATABASE_USER]`
"""

DATABASE_ADMIN_PASSWORD: str = os.getenv("DATABASE_ADMIN_PASSWORD", DATABASE_PASSWORD)
"""
Password for the admin user to connect to the testgen application
postgres database.

from env variable: `DATABASE_ADMIN_PASSWORD`
defaults to: `environ[DATABASE_PASSWORD]`
"""

DATABASE_EXECUTE_USER: str = os.getenv("DATABASE_EXECUTE_USER", "testgen_execute")
"""
User to be created into the testgen application postgres database. Will
be granted:

_ read/write to tables `test_results`, `test_suites` and `test_definitions`
_ read_only to all other tables

from env variable: `DATABASE_EXECUTE_USER`
defaults to: `testgen_execute`
"""

DATABASE_REPORT_USER: str = os.getenv("DATABASE_REPORT_USER", "testgen_report")
"""
User to be created into the testgen application postgres database. Will
be granted read_only access to all tables.

from env variable: `DATABASE_REPORT_USER`
defaults to: `testgen_report`
"""

DATABASE_HOST: str = os.getenv("TG_METADATA_DB_HOST", "localhost")
"""
Hostname where the testgen application postgres database is running in.

from env variable: `TG_METADATA_DB_HOST`
defaults to: `localhost`
"""

DATABASE_PORT: str = os.getenv("TG_METADATA_DB_PORT", "5432")
"""
Port at which the testgen application postgres database is exposed by
the host.

from env variable: `TG_METADATA_DB_PORT`
defaults to: `5432`
"""

DATABASE_NAME: str = os.getenv("TG_METADATA_DB_NAME", "datakitchen")
"""
Name of the database in postgres on which to store testgen metadata.

from env variable: `TG_METADATA_DB_NAME`
defaults to: `datakitchen`
"""

DATABASE_SCHEMA: str = os.getenv("TG_METADATA_DB_SCHEMA", "testgen")
"""
Name of the schema inside the postgres database on which to store
testgen metadata.

from env variable: `TG_METADATA_DB_SCHEMA`
defaults to: `testgen`
"""

PROJECT_KEY: str = os.getenv("PROJECT_KEY", "DEFAULT")
"""
Code used to uniquely identify the auto generated project.

from env variable: `PROJECT_KEY`
defaults to: `DEFAULT`
"""

PROJECT_NAME: str = os.getenv("PROJECT_NAME", "Demo")
"""
Name to assign to the auto generated project.

from env variable: `DEFAULT_PROJECT_NAME`
defaults to: `Demo`
"""

PROJECT_SQL_FLAVOR: str = os.getenv("PROJECT_SQL_FLAVOR", "postgresql")
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

PROJECT_CONNECTION_NAME: str = os.getenv("PROJECT_CONNECTION_NAME", "default")
"""
Name assigned to identify the connection to the project database.

from env variable: `PROJECT_CONNECTION_NAME`
defaults to: `default`
"""

PROJECT_CONNECTION_MAX_THREADS: int = int(os.getenv("PROJECT_CONNECTION_MAX_THREADS", "4"))
"""
Maximum number of concurrent queries executed when fetching data from
the project database.

from env variable: `PROJECT_CONNECTION_MAX_THREADS`
defaults to: `4`
"""

PROJECT_CONNECTION_MAX_QUERY_CHAR: int = int(os.getenv("PROJECT_CONNECTION_MAX_QUERY_CHAR", "5000"))
"""
Determine how many tests are grouped together in a single query.
Increase for better performance or decrease to better isolate test
failures. Accepted values are 500 to 14 000.

from env variable: `PROJECT_CONNECTION_MAX_QUERY_CHAR`
defaults to: `5000`
"""

PROJECT_QC_SCHEMA: str = os.getenv("PROJECT_QC_SCHEMA", "qc")
"""
Name of the schema to be created in the project database.

from env variable: `PROJECT_QC_SCHEMA`
defaults to: `qc`
"""

PROJECT_DATABASE_NAME: str = os.getenv("PROJECT_DATABASE_NAME", "demo_db")
"""
Name of the database the auto generated project will run test
against.

from env variable: `PROJECT_DATABASE_NAME`
defaults to: `demo_db`
"""

PROJECT_DATABASE_SCHEMA: str = os.getenv("PROJECT_DATABASE_SCHEMA", "demo")
"""
Name of the schema inside the project database the tests will be run
against.

from env variable: `PROJECT_DATABASE_SCHEMA`
defaults to: `demo`
"""

PROJECT_DATABASE_USER: str = os.getenv("PROJECT_DATABASE_USER", DATABASE_USER)
"""
User to be used by the auto generated project to connect to the database
under testing.

from env variable: `PROJECT_DATABASE_USER`
defaults to: `environ[DATABASE_USER]`
"""

PROJECT_DATABASE_PASSWORD: str = os.getenv("PROJECT_DATABASE_PASSWORD", DATABASE_PASSWORD)
"""
Password to be used by the auto generated project to connect to the
database under testing.

from env variable: `PROJECT_DATABASE_USER`
defaults to: `environ[DATABASE_PASSWORD]`
"""

PROJECT_DATABASE_HOST: str = os.getenv("PROJECT_DATABASE_HOST", DATABASE_HOST)
"""
Hostname where the database under testing is running in.

from env variable: `PROJECT_DATABASE_HOST`
defaults to: `environ[DATABASE_HOST]`
"""

PROJECT_DATABASE_PORT: str = os.getenv("PROJECT_DATABASE_PORT", DATABASE_PORT)
"""
Port at which the database under testing is exposed by the host.

from env variable: `PROJECT_DATABASE_PORT`
defaults to: `environ[DATABASE_PORT]`
"""

SKIP_DATABASE_CERTIFICATE_VERIFICATION: bool = os.getenv("TG_TARGET_DB_TRUST_SERVER_CERTIFICATE", "no").lower() == "yes"
"""
When True for supported SQL flavors, set up the SQLAlchemy connection to
trust the database server certificate.

from env variable: `TG_TARGET_DB_TRUST_SERVER_CERTIFICATE`
defaults to: `True`
"""

DEFAULT_TABLE_GROUPS_NAME: str = os.getenv("DEFAULT_TABLE_GROUPS_NAME", "default")
"""
Name assigned to the auto generated table group.

from env variable: `DEFAULT_TABLE_GROUPS_NAME`
defaults to: `default`
"""

DEFAULT_TEST_SUITE_KEY: str = os.getenv("DEFAULT_TEST_SUITE_NAME", "default-suite-1")
"""
Key to be assgined to the auto generated test suite.

from env variable: `DEFAULT_TEST_SUITE_NAME`
defaults to: `default-suite-1`
"""

DEFAULT_TEST_SUITE_DESCRIPTION: str = os.getenv("DEFAULT_TEST_SUITE_DESCRIPTION", "default_suite_desc")
"""
Description for the auto generated test suite.

from env variable: `DEFAULT_TEST_SUITE_DESCRIPTION`
defaults to: `default_suite_desc`
"""

DEFAULT_PROFILING_TABLE_SET = os.getenv("DEFAULT_PROFILING_TABLE_SET", "")
"""
Comma separated list of specific table names to include when running
profiling for the project database.

from env variable: `DEFAULT_PROFILING_TABLE_SET`
"""

DEFAULT_PROFILING_INCLUDE_MASK = os.getenv("DEFAULT_PROFILING_INCLUDE_MASK", "%")
"""
A SQL filter supported by the project database's `LIKE` operator for
table names to include.

from env variable: `DEFAULT_PROFILING_INCLUDE_MASK`
defaults to: `%`
"""

DEFAULT_PROFILING_EXCLUDE_MASK = os.getenv("DEFAULT_PROFILING_EXCLUDE_MASK", "tmp%")
"""
A SQL filter supported by the project database's `LIKE` operator for
table names to exclude.

from env variable: `DEFAULT_PROFILING_EXCLUDE_MASK`
defaults to: `tmp%`
"""

DEFAULT_PROFILING_ID_COLUMN_MASK = os.getenv("DEFAULT_PROFILING_ID_COLUMN_MASK", "%id")
"""
A SQL filter supported by the project database's `LIKE` operator
representing ID columns.

from env variable: `DEFAULT_PROFILING_ID_COLUMN_MASK`
defaults to: `%id`
"""

DEFAULT_PROFILING_SK_COLUMN_MASK = os.getenv("DEFAULT_PROFILING_SK_COLUMN_MASK", "%sk")
"""
A SQL filter supported by the project database's `LIKE` operator
representing surrogate key columns.

from env variable: `DEFAULT_PROFILING_SK_COLUMN_MASK`
defaults to: `%sk`
"""

DEFAULT_PROFILING_USE_SAMPLING: str = os.getenv("DEFAULT_PROFILING_USE_SAMPLING", "N")
"""
Toggle on to base profiling on a sample of records instead of the full
table. Accepts `Y` or `N`

from env variable: `DEFAULT_PROFILING_USE_SAMPLING`
defaults to: `N`
"""

OBSERVABILITY_API_URL: str = os.getenv("OBSERVABILITY_API_URL", "")
"""
API URL of your instance of Observability where to send events to for
the project.

You can configure this from the UI settings page.

from env variable: `OBSERVABILITY_API_URL`
"""

OBSERVABILITY_API_KEY: str = os.getenv("OBSERVABILITY_API_KEY", "")
"""
Authentication key with permissions to send events created in your
instance of Observability.

You can configure this from the UI settings page.

from env variable: `OBSERVABILITY_API_KEY`
"""

OBSERVABILITY_VERIFY_SSL: bool = os.getenv("TG_EXPORT_TO_OBSERVABILITY_VERIFY_SSL", "yes").lower() in ["yes", "true"]
"""
When False, exporting events to your instance of Observabilty will skip
SSL verification.

from env variable: `TG_EXPORT_TO_OBSERVABILITY_VERIFY_SSL`
defaults to: `True`
"""

OBSERVABILITY_EXPORT_LIMIT: int = int(os.getenv("TG_OBSERVABILITY_EXPORT_MAX_QTY", "5000"))
"""
When exporting to your instance of Observabilty, the maximum number of
events that will be sent to the events API on a single export.

from env variable: `TG_OBSERVABILITY_EXPORT_MAX_QTY`
defaults to: `5000`
"""

OBSERVABILITY_DEFAULT_COMPONENT_TYPE: str = os.getenv("OBSERVABILITY_DEFAULT_COMPONENT_TYPE", "dataset")
"""
When exporting to your instance of Observabilty, the type of event that
will be sent to the events API.

from env variable: `OBSERVABILITY_DEFAULT_COMPONENT_TYPE`
defaults to: `dataset`
"""

OBSERVABILITY_DEFAULT_COMPONENT_KEY: str = os.getenv("OBSERVABILITY_DEFAULT_COMPONENT_KEY", "default")
"""
When exporting to your instance of Observabilty, the key sent to the
events API to identify the components.

from env variable: `OBSERVABILITY_DEFAULT_COMPONENT_KEY`
defaults to: `default`
"""

CHECK_FOR_LATEST_VERSION: typing.Literal["pypi", "docker", "no"] = typing.cast(
    typing.Literal["pypi", "docker", "no"],
    os.getenv("TG_RELEASE_CHECK", os.getenv("TG_DOCKER_RELEASE_CHECK_ENABLED", "pypi")).lower(),
)
"""
When set to, enables calling Docker Hub API to fetch the latest released
image tag. The fetched tag is displayed in the UI menu.

from env variable: `TG_DOCKER_RELEASE_CHECK_ENABLED`
choices: `pypi`, `docker`, `no`
defaults to: `pypi`
"""

DOCKER_HUB_REPOSITORY: str = os.getenv(
    "TESTGEN_DOCKER_HUB_REPO",
    "datakitchen/dataops-testgen",
)
"""
URL to the docker hub repository containing the dataops testgen image.
Used to check for new releases when `CHECK_FOR_LATEST_VERSION` is set to
`docker`.

from env variable: `TESTGEN_DOCKER_HUB_URL`
defaults to: datakitchen/dataops-testgen
"""

DOCKER_HUB_USERNAME: str | None = os.getenv("TESTGEN_DOCKER_HUB_USERNAME", None)
"""
Username to authenticate against Docker Hub API before fetching the list
of tags. Required if `DOCKER_HUB_REPOSITORY` is a private repository.

from env variable: `TESTGEN_DOCKER_HUB_USERNAME`
defaults to: None
"""

DOCKER_HUB_PASSWORD: str | None = os.getenv("TESTGEN_DOCKER_HUB_PASSWORD", None)
"""
Password to authenticate against Docker Hub API before fetching the list
of tags. Required if `DOCKER_HUB_REPOSITORY` is a private repository.

from env variable: `TESTGEN_DOCKER_HUB_PASSWORD`
defaults to: None
"""

VERSION: str = os.getenv("TESTGEN_VERSION", "unknown")
"""
Current deployed version. The value is displayed in the UI menu.

from env variable: `TESTGEN_VERSION`
defaults to: `unknown`
"""

SSL_CERT_FILE: str = os.getenv("SSL_CERT_FILE", "")
SSL_KEY_FILE: str = os.getenv("SSL_KEY_FILE", "")
"""
File paths for SSL certificate and private key to support HTTPS.
Both files must be provided.
"""
