"""MCP tool implementations.

Each tool module declares ``_DOC_GROUP = DocGroup.<member>`` to control where
the tool appears on the supported-tools doc page. The ``deploy/build_mcp_docs.py``
script reads these values to organize the page.
"""

from enum import StrEnum


class DocGroup(StrEnum):
    """User-facing groupings for tools on the supported-tools doc page."""

    DISCOVER = "Discover what TestGen knows about"
    INVESTIGATE = "Investigate quality issues"
    BROWSE_PROFILING = "Browse profiling results"
    TRIGGER = "Trigger profiling, tests, and test generation"
