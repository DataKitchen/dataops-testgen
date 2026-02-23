from testgen.common.models import with_database_session
from testgen.common.models.test_definition import TestType


@with_database_session
def get_test_type(test_type: str) -> str:
    """Get detailed information about a specific test type.

    Args:
        test_type: The test type code (e.g., 'Alpha_Trunc', 'Unique_Pct').
    """
    tt = TestType.get(test_type)

    if not tt:
        return f"Test type `{test_type}` not found."

    lines = [
        f"# Test Type: {tt.test_type}\n",
        f"- **Name:** {tt.test_name_short}",
    ]
    if tt.test_name_long:
        lines.append(f"- **Full Name:** {tt.test_name_long}")
    if tt.test_description:
        lines.append(f"- **Description:** {tt.test_description}")
    if tt.measure_uom:
        lines.append(f"- **Measure UOM:** {tt.measure_uom}")
    if tt.measure_uom_description:
        lines.append(f"- **Measure Description:** {tt.measure_uom_description}")
    if tt.threshold_description:
        lines.append(f"- **Threshold:** {tt.threshold_description}")
    if tt.dq_dimension:
        lines.append(f"- **DQ Dimension:** {tt.dq_dimension}")
    if tt.test_scope:
        lines.append(f"- **Scope:** {tt.test_scope}")
    if tt.except_message:
        lines.append(f"- **Exception Message:** {tt.except_message}")
    if tt.usage_notes:
        lines.append(f"- **Usage Notes:** {tt.usage_notes}")

    return "\n".join(lines)


@with_database_session
def test_types_resource() -> str:
    """Reference table of all active test types with their descriptions and DQ dimensions."""
    test_types = TestType.select_where(TestType.active == "Y")

    if not test_types:
        return "No active test types found."

    lines = [
        "# TestGen Test Types Reference\n",
        "| Test Type | Name | DQ Dimension | Scope | Description |",
        "|---|---|---|---|---|",
    ]

    for tt in test_types:
        desc = (tt.test_description or "")[:80]
        lines.append(
            f"| {tt.test_type} | {tt.test_name_short or ''} | "
            f"{tt.dq_dimension or ''} | {tt.test_scope or ''} | {desc} |"
        )

    return "\n".join(lines)


def glossary_resource() -> str:
    """Glossary of TestGen concepts, entity hierarchy, result statuses, and DQ dimensions."""
    return """\
# TestGen Glossary

## Entity Hierarchy

- **Project** — Top-level organizational unit. Contains connections and test suites.
- **Connection** — Database connection configuration (host, credentials, flavor).
- **Table Group** — A set of tables within a schema that are profiled and tested together.
- **Test Suite** — A collection of test definitions scoped to a table group.
- **Test Definition** — A configured test with parameters, thresholds, and target table/column.
- **Test Run** — An execution of a test suite producing test results.
- **Test Result** — The outcome of a single test definition within a test run.

## Result Statuses

- **Passed** — Test passed within acceptable thresholds.
- **Warning** — Test exceeded the failure threshold.
- **Failed** — Test exceeded the failure threshold. Higher severity.
- **Error** — Test could not execute (e.g., SQL error, missing table).
- **Log** — Informational result, not scored.

## Disposition

Disposition is a user-assigned review status for test results:
- **Confirmed** (default) — Result is valid and counts toward scoring.
- **Dismissed** — Result reviewed and dismissed (excluded from scoring).
- **Inactive** — Test was deactivated after this result (excluded from scoring).

## DQ Dimensions

- **Accuracy** — Data values are correct and reflect real-world truth.
- **Completeness** — Required data is present (no unexpected NULLs or blanks).
- **Consistency** — Data agrees across columns, tables, or systems.
- **Timeliness** — Data is current and updated within expected windows.
- **Uniqueness** — No unintended duplicates exist.
- **Validity** — Data conforms to expected formats, ranges, or patterns.

## Test Scopes

- **column** — Tests a single column (e.g., null rate, pattern match).
- **table** — Tests table-level properties (e.g., row count, freshness).
- **referential** — Tests relationships between tables (e.g., foreign key match).
- **custom** — User-defined SQL tests.

## Monitor Types

- **Volume_Trend** — Tracks row count changes over time using statistical prediction.
- **Freshness_Trend** — Detects when a table has not been updated as expected.
- **Schema_Drift** — Detects column additions, deletions, or type changes.
- **Metric_Trend** — Tracks changes in user-defined metrics over time.
"""
