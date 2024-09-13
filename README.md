# DataOps Data Quality TestGen
![apache 2.0 license Badge](https://img.shields.io/badge/License%20-%20Apache%202.0%20-%20blue) ![PRs Badge](https://img.shields.io/badge/PRs%20-%20Welcome%20-%20green) [![Latest Version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fhub.docker.com%2Fv2%2Frepositories%2Fdatakitchen%2Fdataops-testgen%2Ftags%2F&query=results%5B0%5D.name&label=latest%20version&color=06A04A)](https://hub.docker.com/r/datakitchen/dataops-testgen) [![Docker Pulls](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fhub.docker.com%2Fv2%2Frepositories%2Fdatakitchen%2Fdataops-testgen%2F&query=pull_count&style=flat&label=docker%20pulls&color=06A04A)](https://hub.docker.com/r/datakitchen/dataops-testgen) [![Documentation](https://img.shields.io/badge/docs-On%20datakitchen.io-06A04A?style=flat)](https://docs.datakitchen.io/articles/#!dataops-testgen-help/dataops-testgen-help) [![Static Badge](https://img.shields.io/badge/Slack-Join%20Discussion-blue?style=flat&logo=slack)](https://data-observability-slack.datakitchen.io/join)

*<p style="text-align: center;">DataOps Data Quality TestGen, or "TestGen" for short, can help you find data issues so you can alert your users and notify your suppliers. It does this by delivering simple, fast data quality test generation and execution by data profiling, new dataset screening and hygiene review, algorithmic generation of data quality validation tests, ongoing production testing of new data refreshes, and continuous anomaly monitoring of datasets. TestGen is part of DataKitchen's Open Source Data Observability.</p>*

## Features

What does DataKitchen's DataOps Data Quality TestGen do? It helps you understand and <b>find data issues in new data</b>.
<p align="center">
<img alt="DatKitchen Open Source Data Quality TestGen Features - New Data" src="https://datakitchen.io/wp-content/uploads/2024/07/Screenshot-2024-07-23-at-2.22.57 PM.png" width="70%">
</p>
It constantly <b>watches your data for data quality anomalies</b> and lets you drill into problems.
<br></br>
<p align="center">
<img alt="DataKitchen Open Source Data Quality TestGen Features - Data Ingestion and Quality Testing" src="https://datakitchen.io/wp-content/uploads/2024/07/Screenshot-2024-07-23-at-2.23.07 PM.png" width="70%">
</p>
A <b>single place to manage Data Quality</b> across data sets, locations, and teams.
<br></br>
<p align="center">
<img alt="DataKitchen Open Source Data Quality TestGen Features - Single Place" src="https://datakitchen.io/wp-content/uploads/2024/07/Screenshot-dataops-testgen-centralize.png" width="70%">
</p>

## Installation with dk-installer (recommended)

The [dk-installer](https://github.com/DataKitchen/data-observability-installer/?tab=readme-ov-file#install-the-testgen-application) program installs DataOps Data Quality TestGen as a [Docker Compose](https://docs.docker.com/compose/) application. This is the recommended mode of installation as Docker encapsulates and isolates the application from other software on your machine and does not require you to manage Python dependencies.

### Install the prerequisite software

| Software                | Tested Versions               | Command to check version                |
|-------------------------|-------------------------|-------------------------------|
| [Python](https://www.python.org/downloads/) <br/>- Most Linux and macOS systems have Python pre-installed. <br/>- On Windows machines, you will need to download and install it.        | 3.9, 3.10, 3.11, 3.12                | `python3 --version`                |
| [Docker](https://docs.docker.com/get-docker/) <br/>[Docker Compose](https://docs.docker.com/compose/install/)         | 25.0.3, 26.1.1, <br/> 2.24.6, 2.27.0, 2.28.1        | `docker -v` <br/> `docker compose version`         |

### Download the installer

On Unix-based operating systems, use the following command to download it to the current directory. We recommend creating a new, empty directory.

```shell
curl -o dk-installer.py 'https://raw.githubusercontent.com/DataKitchen/data-observability-installer/main/dk-installer.py'
```

* Alternatively, you can manually download the [`dk-installer.py`](https://github.com/DataKitchen/data-observability-installer/blob/main/dk-installer.py) file from the [data-observability-installer](https://github.com/DataKitchen/data-observability-installer) repository.
* All commands listed below should be run from the folder containing this file.
* For usage help and command options, run `python3 dk-installer.py --help` or `python3 dk-installer.py <command> --help`.

### Install the TestGen application

The installation downloads the latest Docker images for TestGen and deploys a new Docker Compose application. The process may take 5~10 minutes depending on your machine and network connection.

```shell
python3 dk-installer.py tg install
```

The `--port` option may be used to set a custom localhost port for the application (default: 8501).

To enable SSL for HTTPS support, use the `--ssl-cert-file` and `--ssl-key-file` options to specify local file paths to your SSL certificate and key files.

Once the installation completes, verify that you can login to the UI with the URL and credentials provided in the output.

### Optional: Run the TestGen demo setup

The [Data Observability quickstart](https://docs.datakitchen.io/articles/open-source-data-observability/data-observability-overview) walks you through DataOps Data Quality TestGen capabilities to demonstrate how it covers critical use cases for data and analytic teams.

```shell
python3 dk-installer.py tg run-demo
```

In the TestGen UI, you will see that new data profiling and test results have been generated.

## Installation with pip

As an alternative to the Docker Compose [installation with dk-installer (recommended)](#installation-with-dk-installer-recommended), DataOps Data Quality TestGen can also be installed as a Python package via [pip](https://pip.pypa.io/en/stable/). This mode of installation uses the [dataops-testgen](https://pypi.org/project/dataops-testgen/) package published to PyPI, and it requires a PostgreSQL instance to be provisioned for the application database.

### Install the prerequisite software

| Software                                                                                                                                                                         | Tested Versions  | Command to check version               |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------|------------------------------|
| [Python](https://www.python.org/downloads/) <br/>- Most Linux and macOS systems have Python pre-installed. <br/>- On Windows machines, you will need to download and install it. | 3.10, 3.11, 3.12 | `python3 --version`               |
| [PostgreSQL](https://www.postgresql.org/download/)                                                                                                                                                                     | 14.1, 15.8, 16.4       | `psql --version`|

### Install the TestGen package

We recommend using a Python virtual environment to avoid any dependency conflicts with other applications installed on your machine. The [venv](https://docs.python.org/3/library/venv.html#creating-virtual-environments) module, which is part of the Python standard library, or other third-party tools, like [virtualenv](https://virtualenv.pypa.io/en/latest/) or [conda](https://docs.conda.io/en/latest/), can be used.

Create and activate a virtual environment with a TestGen-compatible version of Python (`>=3.10`). The steps may vary based on your operating system and Python installation - the [Python packaging user guide](https://packaging.python.org/en/latest/tutorials/installing-packages/) is a useful reference.

_On Linux/Mac_
```shell
python3 -m venv venv
source venv/bin/activate
```

_On Windows_
```powershell
py -3.10 -m venv venv
venv\Scripts\activate
```

Within the virtual environment, install the TestGen package with pip.
```shell
pip install dataops-testgen
```

Verify that the [_testgen_ command line](https://docs.datakitchen.io/articles/#!dataops-testgen-help/testgen-commands-and-details) works.
```shell
testgen --help
```

### Set up the application database in PostgresSQL

Create a `local.env` file with the following environment variables, replacing the `<value>` placeholders with appropriate values. Refer to the [TestGen Configuration](docs/configuration.md) document for more details, defaults, and other supported configuration.
```shell
# Connection parameters for the PostgreSQL server
export TG_METADATA_DB_HOST=<postgres_hostname>
export TG_METADATA_DB_PORT=<postgres_port>

# Connection credentials for the PostgreSQL server
# This role must have privileges to create roles, users, database and schema so that the application database can be initialized
export TG_METADATA_DB_USER=<postgres_username>
export TG_METADATA_DB_PASSWORD=<postgres_password>

# Set a password and arbitrary string (the "salt") to be used for encrypting secrets in the application database
export TG_DECRYPT_PASSWORD=<encryption_password>
export TG_DECRYPT_SALT=<encryption_salt>

# Set credentials for the default admin user to be created for TestGen
export TESTGEN_USERNAME=<username>
export TESTGEN_PASSWORD=<password>

# Set an accessible path for storing application logs
export TESTGEN_LOG_FILE_PATH=<path_for_logs>
```

Source the file to apply the environment variables. For the Windows equivalent, refer to [this guide](https://bennett4.medium.com/windows-alternative-to-source-env-for-setting-environment-variables-606be2a6d3e1).
```shell
source local.env
```

Make sure the PostgreSQL database server is up and running. Initialize the application database for TestGen. 
```shell
testgen setup-system-db --yes
```

### Run the TestGen UI

Run the following command to start the TestGen UI. It will open the browser at [http://localhost:8501](http://localhost:8501).

```shell
testgen ui run
```

Verify that you can login to the UI with the `TESTGEN_USERNAME` and `TESTGEN_PASSWORD` values that you configured in the environment variables.

### Optional: Run the TestGen demo setup

The [Data Observability quickstart](https://docs.datakitchen.io/articles/open-source-data-observability/data-observability-overview) walks you through DataOps Data Quality TestGen capabilities to demonstrate how it covers critical use cases for data and analytic teams.

```shell
testgen quick-start --delete-target-db
testgen run-profile --table-group-id 0ea85e17-acbe-47fe-8394-9970725ad37d
testgen run-test-generation --table-group-id 0ea85e17-acbe-47fe-8394-9970725ad37d
testgen run-tests --project-key DEFAULT --test-suite-key default-suite-1
testgen quick-start --simulate-fast-forward
```

In the TestGen UI, you will see that new data profiling and test results have been generated.


## Product Documentation

[DataOps Data Quality TestGen](https://docs.datakitchen.io/articles/dataops-testgen-help/dataops-testgen-help)

## Useful Commands

The [dk-installer](https://github.com/DataKitchen/data-observability-installer/?tab=readme-ov-file#install-the-testgen-application) and [docker compose CLI](https://docs.docker.com/compose/reference/) can be used to operate the TestGen application installed using dk-installer. All commands must be run in the same folder that contains the `dk-installer.py` and `docker-compose.yml` files used by the installation.

### Remove demo data

After completing the quickstart, you can remove the demo data from the application with the following command.

```shell
python3 dk-installer.py tg delete-demo
```

### Upgrade to latest version

New releases of TestGen are announced on the `#releases` channel on [Data Observability Slack](https://data-observability-slack.datakitchen.io/join), and release notes can be found on the [DataKitchen documentation portal](https://docs.datakitchen.io/articles/#!dataops-testgen-help/testgen-release-notes/a/h1_1691719522). Use the following command to upgrade to the latest released version.

 ```shell
 python3 dk-installer.py tg upgrade
 ```

### Uninstall the application

The following command uninstalls the Docker Compose application and removes all data, containers, and images related to TestGen from your machine.

```shell
python3 dk-installer.py tg delete
```

### Access the _testgen_ CLI

The [_testgen_ command line](https://docs.datakitchen.io/articles/#!dataops-testgen-help/testgen-commands-and-details) can be accessed within the running container.

```shell
docker compose exec engine bash
```

Use `exit` to return to the regular terminal.

### Stop the application

```shell
docker compose down
```

### Restart the application

```shell
docker compose up -d
```

## What Next?

### Getting started guide
We recommend you start by going through the [Data Observability Overview Demo](https://docs.datakitchen.io/articles/open-source-data-observability/data-observability-overview).

### Support
For support requests, [join the Data Observability Slack](https://data-observability-slack.datakitchen.io/join) 👋 and post on the `#support` channel.

### Connect to your database
Follow [these instructions](https://docs.datakitchen.io/articles/#!dataops-testgen-help/connect-your-database) to improve the quality of data in your database.

### Community
Talk and learn with other data practitioners who are building with DataKitchen. Share knowledge, get help, and contribute to our open-source project.

Join our community here:

* 👋 [Join us on Slack](https://data-observability-slack.datakitchen.io/join), this is also how you get support (see above)

* 🌟 [Star us on GitHub](https://github.com/DataKitchen/data-observability-installer)

* 🐦 [Follow us on Twitter](https://twitter.com/i/flow/login?redirect_after_login=%2Fdatakitchen_io)

* 🕴️ [Follow us on LinkedIn](https://www.linkedin.com/company/datakitchen)

* 📺 [Get Free DataOps Fundamentals Certification](https://info.datakitchen.io/training-certification-dataops-fundamentals)

* 📚 [Read our blog posts](https://datakitchen.io/blog/)

* 🗃 [Sign The DataOps Manifesto](https://DataOpsManifesto.org)

* 🗃 [Sign The Data Journey Manifesto](https://DataJourneyManifesto.org)


### Contributing
For details on contributing or running the project for development, check out our [contributing guide](CONTRIBUTING.md).

### License
DataKitchen's DataOps Data Quality TestGen is Apache 2.0 licensed.
