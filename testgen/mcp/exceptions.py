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


class MCPResourceNotAccessible(MCPPermissionDenied):
    """Resource is unknown OR inaccessible — message must not distinguish.

    Use whenever a tool looks up a specific resource by identifier and either
    the resource doesn't exist or the caller can't access it. A unified message
    prevents existence-leak via error wording.
    """

    def __init__(self, resource: str, identifier: str | None = None):
        self.resource = resource
        self.identifier = identifier
        message = (
            f"{resource} `{identifier}` not found or not accessible."
            if identifier is not None
            else f"{resource} not found or not accessible."
        )
        super().__init__(message)


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
