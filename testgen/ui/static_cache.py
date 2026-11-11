import hashlib
import pathlib
from urllib.parse import parse_qs

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

STATIC_FOLDER = pathlib.Path(__file__).parent / "static"
STATIC_PATH_PREFIX = "/app/static/"
HASH_PARAM = "h"
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


def hash_static_files(static_folder: pathlib.Path) -> dict[str, str]:
    """
    Hashes the content of every file in a static folder.

    :param static_folder: the folder served under ``STATIC_PATH_PREFIX``
    :return: each file's URL path mapped to the first 12 hex digits of its SHA-256
    """
    return {
        f"{STATIC_PATH_PREFIX}{path.relative_to(static_folder).as_posix()}": hashlib.sha256(
            path.read_bytes()
        ).hexdigest()[:12]
        for path in sorted(static_folder.rglob("*"))
        if path.is_file()
    }


class StaticCacheMiddleware:
    """
    Sets ``Cache-Control`` on successful responses for TestGen's static files.

    A file requested with its own content hash in the query string is cached as immutable, and one requested with any
    other hash is revalidated. One requested without a hash keeps the headers it was served with.

    :param app: the ASGI app to wrap
    :param static_folder: the folder served under ``STATIC_PATH_PREFIX``, hashed once when the middleware is created
    :param dev: revalidate every static file instead, hashed or not
    :param base_path: the path the UI is served under, if any
    """

    def __init__(self, app: ASGIApp, static_folder: pathlib.Path, dev: bool, base_path: str = "") -> None:
        self.app = app
        self.dev = dev
        self.base_path = f"/{base_path.strip('/')}" if base_path.strip("/") else ""
        self.hashes = {} if dev else hash_static_files(static_folder)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        cache_control = self._cache_control(scope)
        if not cache_control:
            await self.app(scope, receive, send)
            return

        async def send_with_cache_control(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 200:
                MutableHeaders(scope=message)["cache-control"] = cache_control
            await send(message)

        await self.app(scope, receive, send_with_cache_control)

    def _cache_control(self, scope: Scope) -> str | None:
        if scope["type"] != "http":
            return None
        path = scope["path"].removeprefix(self.base_path)
        if not path.startswith(STATIC_PATH_PREFIX):
            return None
        if self.dev:
            return REVALIDATE
        requested_hashes = parse_qs(scope["query_string"].decode("latin-1")).get(HASH_PARAM)
        if not requested_hashes:
            return None
        return IMMUTABLE if requested_hashes == [self.hashes.get(path)] else REVALIDATE
