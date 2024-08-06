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

From the root of your local repository, create a Python virtual environment.
```shell
python3.10 -m venv venv
```

Activate the environment.
```shell
source venv/bin/activate
```

### Install dependencies

Install the Python dependencies in editable mode.
```shell
# On Linux
pip install -e .[dev]

# On Mac
pip install -e .'[dev]'
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
export TESTGEN_USERNAME=<username>
export TESTGEN_PASSWORD=<password>
export TG_DECRYPT_SALT=<decrypt_salt>
export TG_DECRYPT_PASSWORD=<decrypt_password>
```

Source the file to apply the environment variables.
```shell
source local.env
```

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
testgen quick-start --delete-target-db
testgen run-profile --table-group-id 0ea85e17-acbe-47fe-8394-9970725ad37d
testgen run-test-generation --table-group-id 0ea85e17-acbe-47fe-8394-9970725ad37d
testgen run-tests --project-key DEFAULT --test-suite-key default-suite-1
testgen quick-start --simulate-fast-forward
```

### Patch and run Streamlit
Patch the Streamlit package with our custom files.
```shell
testgen ui patch-streamlit -f
```

Run the local Streamlit-based TestGen application. It will open the browser at [http://localhost:8501](http://localhost:8501).
```shell
testgen ui run
```
