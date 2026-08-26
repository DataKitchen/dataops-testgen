from typing import Annotated

from pydantic import Field

from testgen.common.generation_set_service import get_generation_set_members
from testgen.common.models import with_database_session
from testgen.common.models.hygiene_issue import HygieneIssueType
from testgen.common.models.test_definition import NON_PUBLIC_TEST_TYPES, TestType
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.tools.common import (
    FLAVOR_CONNECTION_SCHEMA,
    ConnField,
    DocGroup,
    FlavorMode,
    FlavorSchema,
    Req,
    resolve_test_type,
    schema_for,
)
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.DISCOVER


@with_database_session
def get_test_type(
    test_type: Annotated[str, Field(description="The test type (e.g., 'Alpha Truncation', 'Unique Percent').")],
) -> str:
    """Get detailed information about a specific test type."""
    try:
        tt = TestType.get(resolve_test_type(test_type))
    except MCPUserError:
        tt = None

    if not tt or tt.test_type in NON_PUBLIC_TEST_TYPES:
        return f"Test type `{test_type}` not found. Use `testgen://test-types` to see available types."

    doc = MdDoc()
    doc.heading(1, tt.test_name_short)
    if tt.test_name_long:
        doc.field("Full Name", tt.test_name_long)
    if tt.test_description:
        doc.field("Description", tt.test_description)
    if tt.measure_uom:
        doc.field("Unit of Measure", tt.measure_uom)
    if tt.measure_uom_description:
        doc.field("Measure Description", tt.measure_uom_description)
    if tt.threshold_description:
        doc.field("Threshold", tt.threshold_description)
    if tt.impact_dimension:
        doc.field("Impact Dimension", tt.impact_dimension)
    if tt.dq_dimension:
        doc.field("Quality Dimension", tt.dq_dimension)
    if tt.test_scope:
        doc.field("Scope", tt.test_scope)
    if tt.except_message:
        doc.field("Exception Message", tt.except_message)

    _append_type_parameters(doc, tt)

    if tt.usage_notes:
        doc.heading(2, "Usage Notes")
        doc.text(tt.usage_notes)

    return doc.render()


def _append_type_parameters(doc: MdDoc, tt: TestType) -> None:
    """Add parameter definitions section from test type metadata."""
    if not tt.param_fields:
        return

    doc.heading(2, "Parameters")
    doc.table(
        headers=["Parameter", "Field", "Description"],
        rows=[[prompt, column, help_text or None] for column, prompt, help_text in tt.param_fields],
        code=[1],
    )


@with_database_session
def test_types_resource() -> str:
    """Reference table of all test types.

    Covers the description and data quality dimensions of each type.
    """
    test_types = TestType.select_where(TestType.active == "Y", TestType.is_public())

    if not test_types:
        return "No test types found."

    doc = MdDoc()
    doc.heading(1, "TestGen Test Types Reference")
    doc.table(
        headers=["Test Type", "Impact Dimension", "Quality Dimension", "Scope", "Description"],
        rows=[
            [tt.test_name_short, tt.impact_dimension, tt.dq_dimension, tt.test_scope, tt.test_description]
            for tt in test_types
        ],
    )

    return doc.render()


@with_database_session
def generation_sets_resource() -> str:
    """Reference of generation sets and the test types each one generates."""
    members = get_generation_set_members()

    if not members:
        return "No generation sets found."

    # Only active types generate, so an inactive or uninstalled type is not part of the set.
    short_names = {
        tt.test_type: tt.test_name_short or tt.test_type for tt in TestType.select_where(TestType.active == "Y")
    }

    doc = MdDoc()
    doc.heading(1, "TestGen Generation Sets Reference")
    doc.text(
        "Generation sets scope which test types `generate_tests` creates for a test suite. "
        "A test suite can use more than one set, and test types can belong to more than one set."
    )
    for generation_set, test_types in members.items():
        names = sorted(short_names[test_type] for test_type in test_types if test_type in short_names)
        if not names:
            continue
        doc.heading(2, generation_set)
        doc.text(", ".join(names))

    return doc.render()


@with_database_session
def hygiene_issue_types_resource() -> str:
    """Reference table of all hygiene issue types.

    Covers the data quality dimension, description, and suggested action of each type.
    """
    issue_types = HygieneIssueType.select_where(order_by=(HygieneIssueType.name,))

    if not issue_types:
        return "No hygiene issue types found."

    doc = MdDoc()
    doc.heading(1, "TestGen Hygiene Issue Types Reference")
    doc.table(
        headers=["Issue Type", "Impact Dimension", "Quality Dimension", "Likelihood", "Description", "Suggested Action"],
        rows=[
            [it.name, it.impact_dimension, it.dq_dimension, it.likelihood, it.description, it.suggested_action]
            for it in issue_types
        ],
    )

    return doc.render()


def column_profile_fields_resource() -> str:
    """Reference for column-profile fields by general_type, with PII redaction notes."""
    return """\
# TestGen Column Profile Fields Reference

Column profiling stores ~70 statistics per column. The fields populated
depend on the column's `General Type` (Alpha / Numeric / Datetime / Boolean / Time / Other). The
`get_column_profile_detail` tool emits only the fields relevant to a column's type — use
this reference to interpret what each field measures.

## All Column Types

These fields are populated for every successfully-profiled column.

### Header
- **Profiling Run** — `job_execution_id` of the profiling run the rest of the fields come from.
- **Profiled at** — Timestamp when the profiling run started (`YYYY-MM-DD HH:MM UTC`).
- **General Type** — Broad category: `Alpha`, `Numeric`, `Datetime`, `Boolean`, `Time`, or `Other`.
- **Data Type** — Native DB type as reported by the source (e.g. `varchar(50)`, `numeric(18,4)`).
- **Semantic Data Type** — TestGen's functional classification (e.g. `Person Given Name`, `Currency`, `Datetime-Created`).
- **Suggested Data Type** — Suggested narrower DB type given observed values (e.g. `VARCHAR(20)`, `INTEGER`). Omitted when no suggestion applies.
- **PII** — `No` when the column has no PII flag; `Yes` when manually flagged; otherwise `Yes (<Risk> Risk[ - <Category>][ / <Detail>])` — Risk is `High`, `Moderate`, or `Low`; Category is `ID`, `Name`, `Demographic`, or `Contact`; Detail is a subtype (e.g. `Email`, `Passport`) when present.
- **Critical Data Element** — `Yes` if the column is flagged as critical (directly or via its parent table), `No` otherwise.
- **Profiling Score** — Aggregated profiling-derived quality score, 0-100.
- **Testing Score** — Aggregated testing-derived quality score, 0-100.
- **Hygiene Issues (confirmed)** — Confirmed hygiene issues against this column (count). Omitted when the column has a profiling error.

### Counts
- **Row Count** — Total rows in the table (count, integer).
- **Value Count** — Non-null values in this column (count, integer).
- **Distinct Values** — Distinct non-null values (count, integer).
- **Null** — Null values (count, integer).
- **Dummy Values** — Dummy / placeholder values like `'?'`, `'-'`, `'unknown'` (count, integer).
- **Zero Values** — Exact-zero or `'0'`-string values (count, integer). Populated for numeric and alpha columns.

## Alpha (text) Columns

Populated when `General Type == "Alpha"`.

### Length
- **Minimum Length** — Shortest string length (chars).
- **Maximum Length** — Longest string length (chars).
- **Average Length** — Average string length (chars, float).

### Text Range
- **Minimum Text** — Lexicographic minimum value (raw string; **PII-redactable**).
- **Maximum Text** — Lexicographic maximum value (raw string; **PII-redactable**).

### Patterns
- **Standard Pattern Match** — Recognized standard pattern when applicable (`Email`, `Phone (USA)`,
  `Street Address`, `State (USA)`, `Zip Code (USA)`, `Filename`, `Credit Card`, `Delimited Data`, `SSN (USA)`).
- **Distinct Patterns** — Distinct character-class patterns observed (count).
- **Frequent Patterns** — Top patterns and counts, pipe-separated.
- **Frequent Values** — Top frequent raw values and counts (raw strings; **PII-redactable**).
- **Distinct Standard Values** — Distinct values after standardization (count).

### Case & Composition
- **Upper Case / Lower Case / Mixed Case / Non-Alpha** — Case-distribution counts.
- **Includes Digits** — Values containing at least one digit (count).
- **Numeric Values** — Values parseable as numeric (count).
- **Date Values** — Values parseable as a date (count).
- **Quoted Values** — Values wrapped in quotes (count).
- **Leading Spaces** — Values with leading whitespace (count).
- **Embedded Spaces** — Values with internal whitespace (count).
- **Average Embedded Spaces** — Average embedded-space count per value (float).
- **Zero Length** — Empty strings (count).

## Numeric Columns

Populated when `General Type == "Numeric"`.

### Distribution
- **Minimum Value** — Minimum numeric value (raw value; **PII-redactable**).
- **Minimum Value > 0** — Minimum value strictly greater than zero (**PII-redactable**).
- **Maximum Value** — Maximum numeric value (**PII-redactable**).
- **Average Value** — Arithmetic mean.
- **Standard Deviation** — Standard deviation.

### Percentiles
- **25th Percentile** — 25th percentile (Q1).
- **Median Value** — Median (Q2 / 50th percentile).
- **75th Percentile** — 75th percentile (Q3).

## Datetime Columns

Populated when `General Type == "Datetime"`.

### Date Range
- **Minimum Date** — Minimum timestamp (**PII-redactable**).
- **Maximum Date** — Maximum timestamp (**PII-redactable**).

### Age Buckets
- **Before 1 Year** — Values older than 1 year from profiling date (count).
- **Before 5 Years** — Values older than 5 years (count).
- **Before 20 Years** — Values older than 20 years (count).
- **Within 1 Year** — Values within the past year (count).
- **Within 1 Month** — Values within the past month (count).
- **Future Dates** — Values dated after the profiling date (count).

## Boolean Columns

Populated when `General Type == "Boolean"`.

- **True Count** — Rows where the value is true (count).
- **False Count** — Rows where the value is false (count, derived as `Value Count - True Count`).

## PII Redaction

When a column is flagged as PII AND the caller's role lacks permission to view PII on the column's
project, the following raw-value fields render as `[PII Redacted]`:

- Frequent Values
- Minimum Text
- Maximum Text
- Minimum Value
- Minimum Value > 0
- Maximum Value
- Minimum Date
- Maximum Date

Aggregates, counts, `Frequent Patterns`, and `Standard Pattern Match` are never redacted — they're
distribution-level signals that don't expose individual rows.

## Semantic Data Type — values emitted by profiling, grouped by family.

**Identifiers**: `ID`, `ID-FK`, `ID-Group`, `ID-Secondary`, `ID-SK`,
`ID-Unique`, `ID-Unique-SK`

**Dates & schedules**: `Date Stamp`, `DateTime Stamp`, `Schedule Date`,
`Future Date`, `Historical Date`, `Transactional Date`,
`Transactional Date (Mo)`, `Transactional Date (Qtr)`,
`Transactional Date (Wk)`

**Periods**: `Period`, `Period DOW`, `Period Mon-NN`, `Period Month`,
`Period Quarter`, `Period Week`, `Period Year`, `Period Year-Mon`

**People**: `Person Full Name`, `Person Given Name`, `Person Last Name`

**Location & contact**: `Address`, `City`, `State`, `Zip`, `Email`, `Phone`

**Measurements**: `Measurement`, `Measurement Discrete`, `Measurement Pct`,
`Measurement Spike`, `Measurement Text`

**Codes, flags, attributes**: `Attribute`, `Boolean`, `Code`, `Constant`,
`Flag`, `Sequence`

**Entity & system**: `Entity Name`, `Process`, `Process User`, `System User`

The `semantic_data_type` filter on `list_column_profiles` matches via `ILIKE`,
so partial inputs catch related variants (e.g. `ID` matches `ID`, `ID-FK`,
`ID-Group`, …).
"""


def glossary_resource() -> str:
    """Glossary of TestGen concepts.

    Covers the entity hierarchy, result statuses, and quality dimensions.
    """
    return """\
# TestGen Glossary

## Entity Hierarchy

- **Project** — Top-level organizational unit.
- **Connection** — Database connection configuration (host, credentials).
- **Table Group** — A set of tables within a schema that are profiled and tested together.
- **Profiling Run** — A scan of a table group that produces column-level statistics and detects hygiene issues.
- **Hygiene Issue** — A potential data-quality concern detected by a profiling run (e.g. PII columns, non-standard blanks, mixed types).
- **Test Suite** — A collection of test definitions scoped to a table group.
- **Test Definition** — A configured test with parameters, thresholds, and target table/column.
- **Test Run** — An execution of a test suite producing test results.
- **Test Result** — The outcome of a single test definition within a test run.

## Test Result Statuses

- **Passed** — Data meets test criteria.
- **Warning** — Data does not meet test criteria. Severity configured as Warning.
- **Failed** — Data does not meet test criteria. Severity configured as Fail.
- **Error** — Test could not execute (e.g., missing table or permission issue).
- **Log** — Informational result recorded for reference.

## Hygiene Issue Likelihood

How likely the issue is to indicate a real data quality problem.
- **Definite** — Strong signal; almost always a real issue worth fixing.
- **Likely** — Probable issue; review recommended.
- **Possible** — Weaker signal; confirm against the data.

PII issues use their own classification: hygiene issues that flag potential personally identifiable information are categorized by **PII Risk** (**High** or **Moderate**) instead of the likelihoods above.

## Disposition

Disposition is a user-assigned review status for both test results and hygiene issues:
- **Confirmed** (default) — Valid finding; counts toward scoring.
- **Dismissed** — Reviewed and dismissed; excluded from scoring.
- **Muted** — Acknowledged but suppressed; excluded from scoring. (For test results, this means the test was deactivated after the result.)

## Quality Dimensions

What aspect of data quality the test or hygiene issue measures.
- **Accuracy** — Data values are correct and reflect real-world truth.
- **Completeness** — Required data is present (no unexpected NULLs or blanks).
- **Consistency** — Data agrees across columns, tables, or systems.
- **Recency** — Data values themselves reflect recent points in time (e.g. dates in the data fall within expected windows).
- **Timeliness** — Data is updated on the expected schedule (no stale tables, expected refresh cadence).
- **Uniqueness** — No unintended duplicates exist.
- **Validity** — Data conforms to expected formats, ranges, or patterns.

## Impact Dimensions

What's at stake when the data has issues — the primary breakdown used by scorecards.
- **Reliability** — Data is available and correct when needed.
- **Conformance** — Data meets contracts, formats, and reference standards.
- **Regularity** — Data behaves normally, without unexpected statistical shifts from its historical baseline.
- **Usability** — Data is shaped so consumers can work with it efficiently.

## Test Scopes

- **column** — Tests a single column (e.g., null rate, pattern match).
- **table** — Tests table-level properties (e.g., row count, freshness).
- **referential** — Tests relationships between tables (e.g., foreign key match).
- **custom** — User-defined SQL tests.
"""


# Doc-only hints for the connection-parameters resource: value type / format
# guidance that helps the model but isn't part of the validation/mapping schema.
_FIELD_NOTES: dict[str, str] = {
    "Port": "Integer.",
    "Service Account Key": "Service-account key JSON, passed as a parsed object.",
    "Private Key": "Private key as PEM text.",
    "Private Key Passphrase": "Passphrase for the encrypted private key. Omit if the key is unencrypted.",
    "Login URL": "My Domain URL of the Salesforce org.",
    "Consumer Key": "Consumer key from the Salesforce external client app.",
    "Consumer Secret": "Consumer secret from the Salesforce external client app.",
    "Access Token": "Databricks personal access token.",
    "Client ID": "Service-principal client ID.",
    "Client Secret": "Service-principal OAuth secret.",
    "Tenant ID": "Entra ID directory (tenant) ID hosting the service principal.",
    "HTTP Path": "Databricks SQL warehouse HTTP path.",
    "Catalog": "Databricks catalog (the database/namespace).",
    "Service Name": "Oracle service name.",
    "Warehouse": "Snowflake warehouse name.",
    "URL": "Full connection URL. Provide instead of the host fields.",
}

# Doc-only: the conventional default port per flavor, so the model can fill the
# Port when the user doesn't specify one.
_DEFAULT_PORTS: dict[str, str] = {
    "redshift": "5439",
    "redshift_spectrum": "5439",
    "azure_mssql": "1433",
    "synapse_mssql": "1433",
    "onelake_mssql": "1433",
    "mssql": "1433",
    "postgresql": "5432",
    "snowflake": "443",
    "databricks": "443",
    "oracle": "1521",
    "sap_hana": "39015",
}


def _requirement_label(field: ConnField) -> str:
    if field.requirement is Req.REQUIRED:
        return "Required"
    if field.requirement is Req.REQUIRED_UNLESS_URL:
        return "Required (host mode)"
    return "Optional"


def _field_note(field: ConnField, schema: FlavorSchema) -> str | None:
    parts = []
    if field.secret:
        parts.append("Secret — encrypted at rest, never echoed back.")
    if note := _FIELD_NOTES.get(field.label):
        parts.append(note)
    if field.column == "project_port" and (port := _DEFAULT_PORTS.get(schema.code)):
        parts.append(f"Default for {schema.label} is {port} — use it unless the user specifies otherwise.")
    return " ".join(parts) or None


def _append_mode(doc: MdDoc, mode: FlavorMode, schema: FlavorSchema, *, url_offered: bool) -> None:
    if mode.mode is not None:
        doc.heading(2, f"Mode: {mode.mode}")
        doc.text(f'Pass `connection_mode="{mode.mode}"`.')
    doc.table(
        headers=["Field", "Required", "Notes"],
        rows=[[field.label, _requirement_label(field), _field_note(field, schema)] for field in mode.fields],
        code=[0],
    )
    if mode.supports_url and url_offered:
        doc.text(
            "Alternatively, provide `URL` instead of the host fields "
            "(the fields marked _Required (host mode)_) to connect by URL."
        )


def connection_parameters_resource(flavor: str) -> str:
    """Per-flavor connection parameter shapes: the auth modes and the exact
    ``connection_params`` keys (with required/optional + secret notes) for the flavor.

    The URI template variable is documented here rather than with ``Field``: resource
    templates publish no input schema, so a ``Field`` description would go nowhere.

    Args:
        flavor: Flavor code, e.g. ``snowflake``, ``azure_mssql``, ``salesforce_data360``.
    """
    if flavor not in FLAVOR_CONNECTION_SCHEMA:
        valid = ", ".join(sorted(FLAVOR_CONNECTION_SCHEMA))
        raise MCPUserError(f"Unknown flavor `{flavor}`. Valid flavor codes: {valid}.")

    schema = schema_for(flavor)
    doc = MdDoc()
    doc.heading(1, f"{schema.label} Connection Parameters")
    doc.text(
        f'Create with `sql_flavor="{schema.label}"` and a `connection_params` dict keyed by the '
        "field labels below. Secrets are encrypted at rest and never returned."
    )

    multi_mode = len([m for m in schema.modes if m.mode is not None]) > 1
    if multi_mode:
        modes = ", ".join(f"`{m.mode}`" for m in schema.modes if m.mode is not None)
        doc.text(f"Set `connection_mode` to one of: {modes}.")

    for mode in schema.modes:
        _append_mode(doc, mode, schema, url_offered=schema.url_field is not None)

    return doc.render()


def connection_parameters_index_resource() -> str:
    """Supported database flavors for the connection tools.

    Covers the accepted ``sql_flavor`` values and, for each, the resource that
    documents its connection modes and fields.
    """
    doc = MdDoc()
    doc.heading(1, "Connection Flavors")
    doc.text(
        "Accepted `sql_flavor` values. Read the per-flavor resource for a flavor's "
        "connection modes and the fields each needs."
    )
    doc.table(
        headers=["sql_flavor", "Parameters resource"],
        rows=[
            [schema.label, f"testgen://connection-parameters/{code}"]
            for code, schema in FLAVOR_CONNECTION_SCHEMA.items()
        ],
        code=[1],
    )
    return doc.render()
