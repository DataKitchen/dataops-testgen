# Local Environment Setup

This document describes how to set up your local environment for TestGen development.

### Prerequisites

- [Git](https://github.com/git-guides/install-git)
- [Python 3](https://www.python.org/downloads/)
- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

### Clone repository

Login to your GitHub account.

Fork the [dataops-testgen](https://github.com/DataKitchen/dataops-testgen) repository, following [GitHub's guide](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/fork-a-repo).

Clone your forked repository locally.
```shell
git clone https://github.com/YOUR-USERNAME/dataops-testgen
```

### Set up virtual environment

We recommend using a Python virtual environment to avoid any dependency conflicts with other applications installed on your machine. The [venv](https://docs.python.org/3/library/venv.html#creating-virtual-environments) module, which is part of the Python standard library, or other third-party tools, like [virtualenv](https://virtualenv.pypa.io/en/latest/) or [conda](https://docs.conda.io/en/latest/), can be used.

From the root of your local repository, create and activate a virtual environment with a TestGen-compatible version of Python (`>=3.12`). The steps may vary based on your operating system and Python installation - the [Python packaging user guide](https://packaging.python.org/en/latest/tutorials/installing-packages/) is a useful reference.

_On Linux/Mac_
```shell
python3.12 -m venv venv
source venv/bin/activate
```

_On Windows_
```powershell
py -3.12 -m venv venv
venv\Scripts\activate
```

### Install dependencies

Install the Python dependencies in editable mode.

_On Linux_
```shell
pip install -e .[dev]
```

_On Mac/Windows_
```shell
pip install -e ".[dev]"
```

On Mac, you can optionally install [watchdog](https://github.com/gorakhargosh/watchdog) for better performance of the [file watcher](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) used for local development.
```shell
xcode-select --install
pip install watchdog
```

### Set environment variables

Create a `local.env` file with the following environment variables, replacing the `<value>` placeholders with appropriate values. Refer to the [TestGen Configuration](configuration.md) document for other supported values.
```shell
export TESTGEN_DEBUG=yes
export TESTGEN_LOG_TO_FILE=no
export TG_ANALYTICS=no
export TG_JWT_HASHING_KEY=<base64_key>
export TESTGEN_USERNAME=<username>
export TESTGEN_PASSWORD=<password>
export TG_DECRYPT_SALT=<decrypt_salt>
export TG_DECRYPT_PASSWORD=<decrypt_password>
```

Source the file to apply the environment variables.
```shell
source local.env
```

For the Windows equivalent, refer to [this guide](https://bennett4.medium.com/windows-alternative-to-source-env-for-setting-environment-variables-606be2a6d3e1).

### Set up Postgres instance

Run a PostgreSQL instance as a Docker container.

```shell
docker compose -f docker-compose.local.yml up -d
```

Initialize the application database for TestGen.
```shell
testgen setup-system-db --yes
```

Seed the demo data.
```shell
testgen quick-start
```

### Run the Application

TestGen has two modules that have to be running: The web user interface (UI) and the Scheduler.
The scheduler starts jobs (profiling, test execution, ...) at their scheduled times.

The following command starts both modules, each in their own process:

```shell
testgen run-app
```

Alternatively, you can run each individually:


```shell
testgen run-app ui
```

```shell
testgen run-app scheduler
```
