from uuid import UUID

from testgen.common.models.test_definition import TestType
from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPUserError


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
