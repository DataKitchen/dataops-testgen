from testgen.common.models import with_database_session
from testgen.common.models.hygiene_issue import HygieneIssueType
from testgen.common.models.test_definition import TestType
from testgen.mcp.tools.common import DocGroup
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.DISCOVER


@with_database_session
def get_test_type(test_type: str) -> str:
    """Get detailed information about a specific test type.

    Args:
        test_type: The test type (e.g., 'Alpha Truncation', 'Unique Percent').
    """
    matches = TestType.select_where(TestType.test_name_short == test_type)
    tt = matches[0] if matches else None

    if not tt:
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
    """Reference table of all test types with their descriptions and data quality dimensions."""
    test_types = TestType.select_where(TestType.active == "Y")

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
def hygiene_issue_types_resource() -> str:
    """Reference table of all hygiene issue types with their data quality dimensions, descriptions, and suggested actions."""
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
depend on the column's `General Type` (Alpha / Numeric / Date / Boolean / Other). The
`get_column_profile_detail` tool emits only the fields relevant to a column's type — use
this reference to interpret what each field measures.

## All Column Types

These fields are populated for every successfully-profiled column.

### Header
- **Profiling Run** — `job_execution_id` of the profiling run the rest of the fields come from.
- **Profiled at** — Timestamp when the profiling run started (`YYYY-MM-DD HH:MM UTC`).
- **General Type** — Broad category: `Alpha`, `Numeric`, `Date`, `Boolean`, `Time`, or `Other`.
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

## Date Columns

Populated when `General Type == "Date"`.

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
    """Glossary of TestGen concepts, entity hierarchy, result statuses, and quality dimensions."""
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
- **Regularity** — Data arrives on schedule and stays structurally consistent.
- **Usability** — Data is shaped so consumers can work with it efficiently.

## Test Scopes

- **column** — Tests a single column (e.g., null rate, pattern match).
- **table** — Tests table-level properties (e.g., row count, freshness).
- **referential** — Tests relationships between tables (e.g., foreign key match).
- **custom** — User-defined SQL tests.
"""
