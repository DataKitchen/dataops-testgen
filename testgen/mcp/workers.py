"""Run synchronous MCP handler code on worker threads, within the shared database session limit."""

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import anyio

from testgen.common.models import POOL_MAX_OVERFLOW, POOL_SIZE, session_limiter

T = TypeVar("T")


@functools.cache
def mcp_limiter() -> anyio.CapacityLimiter:
    """Limit on concurrent MCP handlers: two fewer than the shared session limit, which REST requests also use."""
    return anyio.CapacityLimiter(POOL_SIZE + POOL_MAX_OVERFLOW - 2)


async def run_on_worker_thread(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Call ``fn`` on a worker thread once a database session is free for it, and return its result.

    The caller's context, which carries the authenticated user, is copied to the thread.
    """
    async with mcp_limiter(), session_limiter():
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
