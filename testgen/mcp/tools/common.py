from datetime import date
from uuid import UUID

from testgen.common.date_service import parse_since
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_result import TestResultStatus
from testgen.common.models.test_suite import TestSuite
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import get_project_permissions


def parse_uuid(value: str, label: str = "ID") -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as err:
        raise MCPUserError(f"Invalid {label}: `{value}` is not a valid UUID.") from err


def parse_result_status(value: str) -> TestResultStatus:
    try:
        return TestResultStatus(value)
    except ValueError as err:
        valid = ", ".join(s.value for s in TestResultStatus)
        raise MCPUserError(f"Invalid status `{value}`. Valid values: {valid}") from err


def validate_page(value: int) -> None:
    if value < 1:
        raise MCPUserError(f"Invalid page `{value}`: must be >= 1.")


def validate_limit(value: int, max_limit: int) -> None:
    if not 1 <= value <= max_limit:
        raise MCPUserError(f"Invalid limit `{value}`: must be between 1 and {max_limit}.")


def parse_since_arg(value: str, label: str = "since", *, today: date | None = None) -> date:
    try:
        return parse_since(value, today=today)
    except ValueError as err:
        raise MCPUserError(f"Invalid `{label}`: {err}") from err


def resolve_test_type(short_name: str) -> str:
    """Resolve a test type short name to its internal code."""
    matches = TestType.select_where(TestType.test_name_short == short_name)
    if not matches:
        raise MCPUserError(
            f"Unknown test type: `{short_name}`. Use the testgen://test-types resource to see available types."
        )
    return matches[0].test_type


def format_page_info(total: int, page: int, limit: int) -> str:
    """Shared pagination summary line for MCP tool output."""
    if total == 0:
        return ""
    start = (page - 1) * limit + 1
    end = min(start + limit - 1, total)
    return f"Showing {start}\u2013{end} of {total} (page {page})."


def format_page_footer(total: int, page: int, limit: int) -> str:
    """Pagination footer hint — returns empty string if on the last page."""
    total_pages = (total + limit - 1) // limit
    if page >= total_pages:
        return ""
    return f"_Page {page} of {total_pages}. Use `page={page + 1}` for more._"


# Entity resolution helpers — see mcp-roadmap.md "Entity Resolution Helpers" guideline.
# Extract a new resolve_<entity> here when a second caller needs the same parse-uuid +
# perm-scoped lookup + collapsed-error pattern.

def resolve_table_group(table_group_id: str) -> TableGroup:
    """Resolve a TG ID, collapsing missing-or-inaccessible into one error path."""
    tg_uuid = parse_uuid(table_group_id, "table_group_id")
    perms = get_project_permissions()
    tg = TableGroup.get(tg_uuid, TableGroup.project_code.in_(perms.allowed_codes))
    if tg is None:
        raise MCPResourceNotAccessible("Table group", table_group_id)
    return tg


def resolve_test_suite(test_suite_id: str) -> TestSuite:
    """Resolve a regular (non-monitor) test suite ID, collapsing missing-or-inaccessible into one error path."""
    suite_uuid = parse_uuid(test_suite_id, "test_suite_id")
    perms = get_project_permissions()
    suite = TestSuite.get(
        suite_uuid,
        TestSuite.is_monitor.isnot(True),
        TestSuite.project_code.in_(perms.allowed_codes),
    )
    if suite is None:
        raise MCPResourceNotAccessible("Test suite", test_suite_id)
    return suite
