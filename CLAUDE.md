# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

DataOps TestGen is a data quality testing and profiling tool that generates and executes data quality validation tests. It's built with:
- **Python 3.12** (required minimum version)
- **Streamlit** for the web UI
- **SQLAlchemy** for database abstraction
- **Click** for CLI commands
- **PostgreSQL** as the application database

The application supports multiple database flavors: PostgreSQL, Snowflake, BigQuery, Databricks, Redshift, Redshift Spectrum, MS SQL Server (with Azure Managed Identity support), and Trino.

**Current Version**: 5.0.2

## Development Setup

### Environment Setup

Use the existing `venv` environment (Python 3.12):

```bash
source venv/bin/activate
```

**Important**: Do NOT use `uv run` directly, as it conflicts with the VIRTUAL_ENV setting. Either:
- Use `uv run --active` to target the active venv
- Or just activate venv and run commands directly

### Configuration

Create a `local.env` file with required environment variables (see `docs/configuration.md`):

```bash
# Database connection
export TG_METADATA_DB_HOST=localhost
export TG_METADATA_DB_PORT=5432
export TG_METADATA_DB_USER=<username>
export TG_METADATA_DB_PASSWORD=<password>

# Encryption
export TG_DECRYPT_PASSWORD=<password>
export TG_DECRYPT_SALT=<salt>

# Application credentials
export TESTGEN_USERNAME=<username>
export TESTGEN_PASSWORD=<password>

# JWT
export TG_JWT_HASHING_KEY=<base64_key>

# Logging
export TESTGEN_LOG_FILE_PATH=<path>
export TESTGEN_LOG_TO_FILE=no  # Set to 'no' for development

source local.env
```

### Database Initialization

```bash
# Initialize the application database
testgen setup-system-db --yes

# Run database upgrade/migration
testgen upgrade-system-version
```

## Common Commands

### Running the Application

```bash
# Run all modules (UI + scheduler + MCP server)
testgen run-app

# Run specific module
testgen run-app ui         # Just the Streamlit UI (http://localhost:8501)
testgen run-app scheduler  # Just the scheduler
testgen run-app mcp        # Just the MCP server
```

### CLI Operations

```bash
# Run data profiling
testgen run-profile -tg <table-group-id>

# Generate tests
testgen run-test-generation -tg <table-group-id> -ts <test-suite-key>

# Execute tests
testgen run-tests -ts <test-suite-key>

# List entities
testgen list-projects
testgen list-connections
testgen list-table-groups -pk <project-key>
testgen list-test-suites -pk <project-key>

# Quick start demo (creates sample data)
testgen quick-start
```

### Development Tools

```bash
# Linting (uses ruff)
ruff check testgen/

# Type checking (uses mypy)
mypy testgen/

# Run tests
pytest tests/

# Run specific test markers
pytest -m unit
pytest -m integration
pytest -m functional
```

## Architecture

### Module Structure

```
testgen/
├── __main__.py           # CLI entry point (Click commands)
├── settings.py           # Configuration via environment variables
├── commands/             # CLI command implementations
│   ├── run_profiling.py            # Data profiling logic (refactored)
│   ├── run_generate_tests.py      # Test generation
│   ├── run_test_execution.py      # Test execution (refactored)
│   ├── run_test_validation.py     # Test validation (refactored)
│   ├── run_pairwise_contingency_check.py  # Pairwise data checks
│   └── queries/                    # SQL query templates
├── common/
│   ├── database/                   # Database abstraction layer
│   │   └── flavor/                 # Database-specific implementations
│   ├── models/                     # SQLAlchemy ORM models
│   ├── notifications/              # Email notification system (NEW)
│   │   ├── base.py                # Base notification classes
│   │   ├── notifications.py       # Notification service
│   │   ├── profiling_run.py       # Profiling run notifications
│   │   ├── test_run.py            # Test run notifications
│   │   └── score_drop.py          # Score drop notifications
│   └── [various services]          # Shared utilities
├── ui/                   # Streamlit web application
│   ├── app.py           # Main Streamlit entry point
│   ├── bootstrap.py     # Application initialization
│   ├── views/           # Page implementations
│   ├── components/      # Reusable UI components
│   └── services/        # UI business logic
├── scheduler/           # Cron-based job scheduling
├── mcp/                 # FastMCP server for Claude Desktop integration
└── template/            # SQL templates for test generation/validation
```

### Key Architectural Patterns

**Multi-Module Application**: TestGen runs three separate modules that can be launched independently or together:
1. **UI** (Streamlit) - Web interface on port 8501
2. **Scheduler** - Background job execution
3. **MCP** (Model Context Protocol) - API server for Claude Desktop integration on port 8004

**Database Abstraction**: The `testgen.common.database.flavor` module provides database-specific implementations. When adding support for new databases or modifying SQL generation:
- Each flavor inherits from `FlavorService` base class
- Implements database-specific SQL generation methods
- Test generation templates are in `testgen/template/`

**CLI Structure**: Commands are defined in `testgen/__main__.py` using Click decorators. Long-running operations use the `@register_scheduler_job` decorator to make them schedulable.

**UI Bootstrapping**: The Streamlit UI uses a cached bootstrap pattern (`testgen.ui.bootstrap.run()`) that initializes routing, authentication, and plugins. The cache is invalidated when `TESTGEN_DEBUG=yes`.

**Session Management**: Database sessions are managed via the `@with_database_session` decorator, which provides automatic session handling and cleanup.

**Email Notifications**: The `testgen.common.notifications` module provides email notification functionality:
- Configured via `notification_settings` table (SMTP server, recipients, etc.)
- Supports profiling run, test run, score drop, and monitor run notifications
- Uses Handlebars templates (pybars3) for HTML email rendering
- Notifications can be triggered automatically after job completion

**Monitor System**: The monitoring feature provides real-time anomaly detection across tables:
- **Location**: `testgen/ui/views/monitors_dashboard.py` (main dashboard)
- **Models**: `testgen/common/models/` - MonitorNotificationSettings, TestRunMonitorSummary
- **Notifications**: `testgen/common/notifications/monitor_run.py` - Email alerts for anomalies
- **Test Generation**: `testgen/commands/test_generation.py` - `run_monitor_generation()` creates monitor tests
- **Frontend**: `testgen/ui/components/frontend/js/pages/monitors_dashboard.js` - React dashboard with trends and visualizations
- **Monitor Types**:
  - `Freshness_Trend` - Detects stale data (tables not updating on schedule)
  - `Volume_Trend` - Detects unusual row count changes
  - `Schema_Drift` - Detects schema changes (column adds/drops/modifications)
  - `Metric_Trend` - Custom metric monitoring (numeric columns)
- **Features**: Training mode, prediction-based or static thresholds, lookback windows, scheduled execution, holiday/weekend exclusions
- **Access**: Via "Monitors" menu item in the UI (Data Quality Testing section)

### Database Schema Management

Schema migrations are in `testgen/template/dbupgrade/`:
- Numbered incrementally (e.g., `0103_incremental_upgrade.sql`)
- Applied automatically on application startup
- Schema revision tracked in database

## MCP Server (Claude Desktop Integration)

### Important: Pydantic Version Conflict

The MCP server requires **Pydantic v2**, but TestGen pins **Pydantic v1.10.13** due to dependency `streamlit-pydantic==0.6.0`. Therefore:

**The MCP server MUST run in an isolated environment** using the standalone script:

```bash
# Run MCP server (auto-creates isolated mcp-env/)
./run_mcp_server.sh
```

This script:
- Creates a separate Python 3.12 environment in `mcp-env/`
- Installs FastMCP with Pydantic v2
- Runs the MCP server with HTTPS on port 8004
- Uses SSL certificates from `certs/server.crt` and `certs/server.key`

**DO NOT** try to install FastMCP in the main venv - it will break streamlit-pydantic.

### MCP Server Features

- Exposes TestGen version via MCP tool: `get_testgen_version_tool`
- Runs with HTTPS by default (if certs exist)
- Can run standalone without TestGen dependencies
- Fallback to environment variables for configuration

### Claude Desktop Configuration

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "testgen": {
      "command": "/full/path/to/run_mcp_server.sh"
    }
  }
}
```

## Code Style & Testing

### Type Checking
- All functions must have type hints (`disallow_untyped_defs = true`)
- Return types must be explicit (`warn_return_any = true`)
- Run mypy before committing: `mypy testgen/`

### Linting
- Uses Ruff with strict checks (bandit, bugbear, etc.)
- Line length: 120 characters
- No print statements in production code (use logging)
- Run before committing: `ruff check testgen/`

### Testing
- Test files: `tests/test_*.py`
- Use pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.functional`
- Tests must not use print statements (S101 ignored in tests)

## Important Constraints

1. **Python Version**: Requires Python >= 3.12 (uses pattern matching syntax)
2. **SQLAlchemy Version**: Pinned to 1.4.46 (not 2.x) - use legacy patterns
3. **Pydantic Isolation**: Never install FastMCP in main venv - use `mcp-env/` only
4. **Database Session Management**: Always use `@with_database_session` decorator
5. **Streamlit Caching**: UI bootstrap is cached - set `TESTGEN_DEBUG=yes` during development
6. **Match Statement**: Requires Python 3.10+ (used in `__main__.py`)

## Recent Major Changes

### Version 5.0.2 (Current)
- **Database upgrade fixes**: Handle duplicates before applying unique index (commit 509541e)
- Latest stable release based on 4.39.2 with improvements

### Version 5.0.1
- Helm services version updates
- Production stability improvements

### Version 4.39.2 (Base Features)
- **Email Notifications System**: Complete SMTP-based notification infrastructure for profiling runs, test runs, score drops, and monitor runs
- **Monitor System**: Real-time anomaly detection for freshness, volume, schema drift, and custom metrics
- **BigQuery Support**: Full support for Google BigQuery as a data source
- **Redshift Spectrum**: New database flavor for AWS Redshift Spectrum
- **Azure Managed Identity**: Passwordless authentication for Azure SQL Server using managed identities
- **Schema Drift Tests**: New test type for detecting schema changes
- **Pairwise Contingency Check**: New CLI command for analyzing data relationships
- **Major Refactoring**: Profiling engine, test execution, test validation, and query modules
- **New Dependencies**: `pybars3==0.9.7`, `azure-identity==1.25.1`, updated cron packages

## Data Contract Feature

The Data Contract feature surfaces TestGen test suites as a formal data contract, mapped to ODCS v3.1.0 YAML.

### Files
- **`testgen/ui/views/data_contract.py`** — Main Streamlit view: health grid, terms detail panel, suite picker, term modals
- **`testgen/ui/components/frontend/js/pages/data_contract.js`** — VanJS frontend page
- **`testgen/commands/export_data_contract.py`** — Exports a data contract as ODCS v3.1.0 YAML
- **`testgen/commands/import_data_contract.py`** — Imports YAML changes back to the database
- **`testgen/template/dbupgrade/0183_incremental_upgrade.sql`** — Adds `include_in_contract` BOOLEAN column to `test_suites`

### Navigation
- Page key: `data-contract`, accessed via `?table_group_id=<uuid>` query param
- Registered in `testgen/ui/components/widgets/testgen_component.py` `AvailablePages`

### DB Schema
- `test_suites.include_in_contract` — `BOOLEAN NOT NULL DEFAULT TRUE` — controls which suites are in scope for the contract
- `test_suites.is_monitor` — `BOOLEAN` — marks a suite as a monitor suite (excluded from contract test counts and suite picker)

### Key Architectural Patterns
- **Modals via `emitEvent` + `@st.dialog`** — Custom component iframes clip `position: fixed/absolute` elements. ALL modals must go through: JS emits event → Python `event_handlers` → `@st.dialog`. Do NOT use VanJS popups or positioned overlays inside the component iframe.
- **`event_handlers` vs `on_change_handlers`** — Use `event_handlers` when the handler needs to call `st.rerun()` (required for dialogs). `on_change_handlers` does not support `st.rerun()`.
- **Fresh test statuses** — Test statuses are fetched fresh from DB on each render via `_fetch_test_statuses()`. Do NOT rely on `lastResult` in cached YAML — it may be stale.
- **YAML caching** — Contract YAML is cached in `st.session_state[yaml_key]`. Test run results are NOT cached.
- **Monitor suite filtering** — Monitor suites (`is_monitor=True`) are excluded from the suite picker and test count display, but kept for navigation fallback.

## SQL Template System

Test generation uses Jinja2 templates in `testgen/template/`:
- Templates are database-flavor-specific
- Parameters passed via `FlavorService` methods
- Templates organized by test category (e.g., `gen_funny_cat_tests/`)

When modifying SQL generation:
1. Update the template in `testgen/template/`
2. Ensure flavor-specific adaptations in `testgen/common/database/flavor/`
3. Test against all supported database types

## Configuration Files

- `pyproject.toml` - Package metadata, dependencies, tool config
- `local.env` - Environment variables (not committed)
- `docs/configuration.md` - Full list of environment variables
- `.ruff.toml` - Ruff linter configuration (inline in pyproject.toml)
- `pytest.ini` - Pytest configuration (inline in pyproject.toml)
