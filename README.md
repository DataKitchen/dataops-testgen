# DataOps Data Quality TestGen 
![apache 2.0 license Badge](https://img.shields.io/badge/License%20-%20Apache%202.0%20-%20blue) ![PRs Badge](https://img.shields.io/badge/PRs%20-%20Welcome%20-%20green) [![Latest Version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fhub.docker.com%2Fv2%2Frepositories%2Fdatakitchen%2Fdataops-testgen%2Ftags%2F&query=results%5B0%5D.name&label=latest%20version&color=06A04A)](https://hub.docker.com/r/datakitchen/dataops-testgen) [![Docker Pulls](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fhub.docker.com%2Fv2%2Frepositories%2Fdatakitchen%2Fdataops-testgen%2F&query=pull_count&style=flat&label=docker%20pulls&color=06A04A)](https://hub.docker.com/r/datakitchen/dataops-testgen) [![Documentation](https://img.shields.io/badge/docs-On%20datakitchen.io-06A04A?style=flat)](https://docs.datakitchen.io/articles/#!dataops-testgen-help/dataops-testgen-help) [![Static Badge](https://img.shields.io/badge/Slack-Join%20Discussion-blue?style=flat&logo=slack)](https://data-observability-slack.datakitchen.io/join)

*<p style="text-align: center;">DataOps Data Quality TestGen delivers simple, fast data quality test generation and execution by data profiling,  new dataset screening and hygiene review, algorithmic generation of data quality validation tests, ongoing production testing of new data refreshes, and continuous anomaly monitoring of datasets. DataOps TestGen is part of DataKitchen's Open Source Data Observability.</p>* 

## Features

What does DataKitchen's DataOps Data Quality TestGen do?  It helps you understand and <b>find data issues in new data</b>. 
<p align="center">
<img alt="DatKitchen Open Source Data Quality TestGen Features - New Data" src="https://datakitchen.io/wp-content/uploads/2024/07/Screenshot-2024-07-23-at-2.22.57 PM.png" width="70%" >
</p>
It constantly <b>watches your data for data quality anomalies</b> and lets you drill into problems.
<br></br>
<p align="center">
<img alt="DataKitchen Open Source Data Quality TestGen Features - Data Ingestion and Quality Testing" src="https://datakitchen.io/wp-content/uploads/2024/07/Screenshot-2024-07-23-at-2.23.07 PM.png"  width="70%" >
</p>
A <b>single place to manage Data Quality</b> across data sets, locations, and teams.
<br></br>
<p align="center">
<img alt="DataKitchen Open Source Data Quality TestGen Features - Singel Placeg" src="https://datakitchen.io/wp-content/uploads/2024/07/Screenshot-dataops-testgen-centralize.png"  width="70%" >
</p>

## Installation
The dk-installer program [installs DataOps Data Quality TestGen](https://github.com/DataKitchen/data-observability-installer/?tab=readme-ov-file#install-the-testgen-application).  Install the required software for TestGen and download the installer program to a new directory on your computer.

### Using dk-installer (recommended)
Install with a single command using [`dk-installer`](https://github.com/DataKitchen/data-observability-installer/?tab=readme-ov-file#install-the-testgen-application).

```
python3 dk-installer.py tg install
```

### Using docker compose
You can also install using the provided [`docker-compose.yml`](deploy/docker-compose.yml).

Make a local copy of the compose file.
```bash
curl -o docker-compose.yml 'https://raw.githubusercontent.com/DataKitchen/dataops-testgen/main/deploy/docker-compose.yml'
```

If you are interested in integrating TestGen with DataKitchen Observability platform, edit the compose file and set values for the environment variables `OBSERVABILITY_API_URL` and `OBSERVABILITY_API_KEY`.

Before running docker compose, create a `.env` to hold the secrets needed to run Testgen.
```bash
touch testgen.env
```

The following variables are required:
```
TESTGEN_USERNAME=
TESTGEN_PASSWORD=
TG_DECRYPT_SALT=
TG_DECRYPT_PASSWORD=
```

You can learn about how each variable is used in [Configuration](#configuration)

Then, run docker compose to start the services:
```bash
docker compose --env-file testgen.env up --detach
```

This will spin up a postgres service, a startup service which runs once to setup the database and, make the Testgen UI available at http://localhost:8501.

After verifying that Testgen is running, follow [the steps for the quick start](#quick-start) to start getting familiar with the tool.

## Quick start
Testgen includes a basic data set for you to play around.

### Using dk-installer (recommended)
Once Testgen is running, you can use [`dk-installer`](https://github.com/DataKitchen/data-observability-installer/?tab=readme-ov-file#run-the-testgen-demo-setup) to generate the demo data:
```bash
python3 dk-installer.py tg run-demo
```

And, if you are integrating Testgen with the DataKitchen Observability platform, you will need to pass the `--export`
flag:
```bash
python3 dk-installer.py tg run-demo --export
```

### Using docker compose
You can also generate the demo data if you installed using docker compose. Set it up by using the Testgen CLI to run the quick start command:
```bash
docker compose --env-file testgen.env exec engine testgen quick-start
```

It also supports setting up the integration with DataKitchen Observability:
```bash
docker compose --env-file testgen.env exec engine testgen quick-start --observability-api-url <url> --observability-api-key <key>
```
**NOTE:** You don't need to pass the Observability URL and key as arguments if you set them up as environment variables in your compose file.


After you have the demo data from the `quick-start` command, follow the following steps to complete the quick start:

1. Run profiling against the target demo database
```bash
docker compose --env-file testgen.env exec engine testgen run-profile --table-group-id 0ea85e17-acbe-47fe-8394-9970725ad37d
```

2. Generate tests cases for all columns in the target demo database 
```bash
docker compose --env-file testgen.env exec engine testgen run-test-generation --table-group-id 0ea85e17-acbe-47fe-8394-9970725ad37d
```

3. Run the generated tests
```bash
docker compose --env-file testgen.env exec engine testgen run-tests --project-key DEFAULT --test-suite-key default-suite-1
```

4. Export the test results to Observability
```bash
docker compose --env-file testgen.env exec engine testgen export-observability --project-key DEFAULT --test-suite-key default-suite-1
```

5. Simulate changes to the demo data
```bash
docker compose --env-file testgen.env exec engine testgen quick-start --simulate-fast-forward
```

6. And, export the test results over the simulated changes to Observability
```bash
docker compose --env-file testgen.env exec engine testgen export-observability --project-key DEFAULT --test-suite-key default-suite-1
```

## Configuration

#### `TESTGEN_DEBUG`

Invalidates the cache with the bootstrapped application causing the changes to the routing and plugins to take effect
on every render.

Also, changes the logging level for the `testgen.ui` logger from `INFO` to `DEBUG`.

default: `no`

### `TESTGEN_LOG_TO_FILE`
Set it to `yes` to enable rotating file logs to be written under `/var/log/testgen/`.

default: `no`

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

#### `PROJECT_QC_SCHEMA`

Name of the schema to be created in the project database.

default: `qc`

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

#### `TG_DOCKER_RELEASE_CHECK_ENABLED`

Enables calling Docker Hub API to fetch the latest released image tag. The fetched tag is displayed in the UI menu.

default: `yes`

## Community

### Getting Started Guide
We recommend you start by going through the [Data Observability Overview Demo](https://docs.datakitchen.io/articles/open-source-data-observability/data-observability-overview).

### Support
For support requests, [join the Data Observability Slack](https://data-observability-slack.datakitchen.io/join) and ask post on #support channel.

### Connect
Talk and Learn with other data practitioners who are building with DataKitchen. Share knowledge, get help, and contribute to our open-source project. 

Join our community here:

* 🌟 [Star us on GitHub](https://github.com/DataKitchen/data-observability-installer)

* 🐦 [Follow us on Twitter](https://twitter.com/i/flow/login?redirect_after_login=%2Fdatakitchen_io)

* 🕴️ [Follow us on LinkedIn](https://www.linkedin.com/company/datakitchen)

* 📺 [Get Free DataOps Fundamentals Certification](https://info.datakitchen.io/training-certification-dataops-fundamentals)

* 📚 [Read our blog posts](https://datakitchen.io/blog/)

* 👋 [Join us on Slack](https://data-observability-slack.datakitchen.io/join)

* 🗃 [Sign The DataOps Manifesto](https://DataOpsManifesto.org)

* 🗃 [Sign The Data Journey Manifesto](https://DataJourneyManifesto.org)


### Contributing
For details on contributing or running the project for development, check out our contributing guide.

### License
DataKitchen DataOps TestGen is Apache 2.0 licensed.
