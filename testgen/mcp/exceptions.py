"""MCP exception hierarchy and error boundary.

``MCPUserError`` (and its subclasses) carry safe, user-facing messages.
``mcp_error_boundary`` is a decorator that catches them and converts to
text, while neutralising unexpected exceptions.
"""

import functools
import logging

LOG = logging.getLogger("testgen")


class MCPUserError(Exception):
    """Safe, user-facing error for MCP tools, prompts, and resources.

    The error boundary converts ``str(e)`` into the response text.
    All other exceptions are treated as unexpected: their traceback is
    logged and a neutral message is returned to the client.
    """


class MCPPermissionDenied(MCPUserError):
    """Raised when access is denied due to insufficient project permissions."""


def mcp_error_handler(fn):
    """Wrap an MCP handler (tool, resource, or prompt) with safe error handling.

    - ``MCPUserError`` (including ``MCPPermissionDenied``) → ``str(e)`` as the response.
    - Any other exception → traceback logged, neutral message returned.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except MCPUserError as e:
            return str(e)
        except Exception:
            LOG.exception("Unhandled error in MCP handler '%s'", fn.__name__)
            return "An unexpected error occurred."

    return wrapper
