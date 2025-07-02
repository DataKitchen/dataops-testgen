## TestGen Configuration

This document describes the environment variables supported by TestGen.

#### `TESTGEN_DEBUG_LOG_LEVEL`

Sets logs to the debug level.

default: `no`

#### `TESTGEN_DEBUG`

Invalidates the cache with the bootstrapped application causing the changes to the routing and plugins to take effect
on every render.

Also, changes the logging level for the `testgen.ui` logger from `INFO` to `DEBUG`.

default: `no`

#### `TESTGEN_LOG_TO_FILE`

Enables generation of rotating file logs.

default: `yes`

#### `TESTGEN_LOG_FILE_PATH`

File path under which to generate rotating file logs, when `TESTGEN_LOG_TO_FILE` is turned on.

default: `/var/lib/testgen/log`

#### `TESTGEN_LOG_FILE_MAX_QTY`

Maximum log files to keep (one file per day), when `TESTGEN_LOG_TO_FILE` is turned on.

default: `90`

#### `TG_DECRYPT_SALT`

Salt used to encrypt and decrypt user secrets. Only allows ascii characters.

A minimun length of 16 characters is recommended.

#### `TG_DECRYPT_PASSWORD`

Secret passcode used in combination with `TG_DECRYPT_SALT` to encrypt and decrypt user secrets. Only allows ascii characters.

#### `TESTGEN_USERNAME`

Username to log into the web application.

#### `TESTGEN_PASSWORD`

Password to log into the web application.

#### `TG_METADATA_DB_USER`

User to connect to the testgen application postgres database.

default: `os.environ["TESTGEN_USERNAME"]`

#### `TG_METADATA_DB_PASSWORD`

Password to connect to the testgen application postgres database.

default: `os.environ["TESTGEN_PASSWORD"]`

#### `DATABASE_ADMIN_USER`

User with admin privileges in the testgen application postgres database used to create roles, users, database and schema. Required if the user in `TG_METADATA_DB_USER` does not have the required privileges.

default: `os.environ["TG_METADATA_DB_USER"]` |

#### `DATABASE_ADMIN_PASSWORD`

Password for the admin user to connect to the testgen application postgres database.

default: `os.environ["TG_METADATA_DB_PASSWORD"]`

#### `DATABASE_EXECUTE_USER`

User to be created into the testgen application postgres database.

Will be granted:
- read/write to tables `test_results`, `test_suites` and `test_definitions`
- read only to all other tables.

default: `testgen_execute`

#### `DATABASE_REPORT_USER`

User to be created into the testgen application postgres database. Will be granted read_only access to all tables.

default: `testgen_report`

#### `TG_METADATA_DB_HOST`

Hostname where the testgen application postgres database is running in.

default: `localhost`

#### `TG_METADATA_DB_PORT`

Port at which the testgen application postgres database is exposed by the host.

default: `5432`

#### `TG_METADATA_DB_NAME`

Name of the database in postgres on which to store testgen metadata.

default: `datakitchen`

#### `TG_METADATA_DB_SCHEMA`

Name of the schema inside the postgres database on which to store testgen metadata.

default: `testgen`

#### `PROJECT_KEY`

Code used to uniquely identify the auto generated project.

default: `DEFAULT`

#### `DEFAULT_PROJECT_NAME`

Name to assign to the auto generated project.

default: `Demo`

#### `PROJECT_SQL_FLAVOR`

SQL flavor of the database the auto generated project will run tests against.

Supported flavors:
- `redshift`
- `snowflake`
- `mssql`
- `postgresql`

default: `postgresql`

#### `PROJECT_CONNECTION_NAME`

Name assigned to identify the connection to the project database.

default: `default`

#### `PROJECT_CONNECTION_MAX_THREADS`

Maximum number of concurrent queries executed when fetching data from the project database.

default: `4`

#### `PROJECT_CONNECTION_MAX_QUERY_CHAR`

Determine how many tests are grouped together in a single query. Increase for better performance or decrease to better isolate test failures. Accepted values are 500 to 14 000.

default: `5000`

#### `PROJECT_DATABASE_NAME`

Name of the database the auto generated project will run test against.

default: `demo_db`

#### `PROJECT_DATABASE_SCHEMA`

Name of the schema inside the project database the tests will be run against.

default: `demo`

#### `PROJECT_DATABASE_USER`

User to be used by the auto generated project to connect to the database under testing.

default: `os.environ["TG_METADATA_DB_USER"]`

#### `PROJECT_DATABASE_USER`

Password to be used by the auto generated project to connect to the database under testing.

default: `os.environ["TG_METADATA_DB_PASSWORD"]`

#### `PROJECT_DATABASE_HOST`

Hostname where the database under testing is running in.

default: `os.environ["TG_METADATA_DB_HOST"]`

#### `PROJECT_DATABASE_PORT`

Port at which the database under testing is exposed by the host.
default: `os.environ["TG_METADATA_DB_PORT"]`

#### `TG_TARGET_DB_TRUST_SERVER_CERTIFICATE`

For supported SQL flavors, set up the SQLAlchemy connection to trust the database server certificate.

default: `no`

#### `DEFAULT_TABLE_GROUPS_NAME`

Name assigned to the auto generated table group.

default: `default`

#### `DEFAULT_TEST_SUITE_NAME`

Key to be assgined to the auto generated test suite.

default: `default-suite-1`

#### `DEFAULT_TEST_SUITE_DESCRIPTION`

Description for the auto generated test suite.

default: `default_suite_desc`

#### `DEFAULT_PROFILING_TABLE_SET`

Comma separated list of specific table names to include when running profiling for the project database.

#### `DEFAULT_PROFILING_INCLUDE_MASK`

A SQL filter supported by the project database's `LIKE` operator for table names to include.

default: `%%`

#### `DEFAULT_PROFILING_EXCLUDE_MASK`

A SQL filter supported by the project database's `LIKE` operator for table names to exclude.

default: `tmp%%`

#### `DEFAULT_PROFILING_ID_COLUMN_MASK`

A SQL filter supported by the project database's `LIKE` operator representing ID columns.

default: `%%id`

#### `DEFAULT_PROFILING_SK_COLUMN_MASK`

A SQL filter supported by the project database's `LIKE` operator representing surrogate key columns.

default: `%%sk`

#### `DEFAULT_PROFILING_USE_SAMPLING`

Toggle on to base profiling on a sample of records instead of the full table. Accepts `Y` or `N`.

default: `N`

#### `OBSERVABILITY_API_URL`

API URL of your instance of Observability where to send events to for the project.

#### `OBSERVABILITY_API_KEY`

Authentication key with permissions to send events created in your instance of Observability.

#### `TG_EXPORT_TO_OBSERVABILITY_VERIFY_SSL`

Exporting events to your instance of Observabilty verifies SSL certificate.

default: `yes`

#### `TG_OBSERVABILITY_EXPORT_MAX_QTY`

When exporting to your instance of Observabilty, the maximum number of events that will be sent to the events API on a single export.

default: `5000`

#### `OBSERVABILITY_DEFAULT_COMPONENT_TYPE`

When exporting to your instance of Observabilty, the type of event that will be sent to the events API.

default: `dataset`

#### `OBSERVABILITY_DEFAULT_COMPONENT_KEY`

When exporting to your instance of Observabilty, the key sent to the events API to identify the components.
default: `default`
