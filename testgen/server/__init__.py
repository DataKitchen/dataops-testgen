"""TestGen server — combined FastAPI + MCP application."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from testgen import settings

# authlib rejects http:// URIs by default; allow in debug mode for local dev
if settings.IS_DEBUG:
    os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")

from testgen.api.app import router as api_router
from testgen.api.oauth.metadata import router as metadata_router
from testgen.api.oauth.routes import init_routes
from testgen.api.oauth.routes import router as oauth_router
from testgen.api.oauth.server import create_authorization_server
from testgen.common import version_service
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")


def create_app() -> FastAPI:
    version_data = with_database_session(version_service.get_version)()

    mcp_session_manager = None

    if settings.MCP_ENABLED:
        from testgen.mcp.server import build_mcp_app

        mcp_app, mcp_session_manager = build_mcp_app(settings.BASE_URL)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if mcp_session_manager is not None:
            async with mcp_session_manager.run():
                yield
        else:
            yield

    app = FastAPI(
        title="TestGen API",
        version=version_data.current or "dev",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    server = create_authorization_server()
    init_routes(server)

    app.include_router(metadata_router)
    app.include_router(oauth_router)
    app.include_router(api_router)

    if settings.MCP_ENABLED:
        app.mount("", mcp_app)

    if settings.IS_DEBUG:
        from starlette.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Mcp-Session-Id"],
        )

    return app


def run_server() -> None:
    """Start the combined API + MCP server with uvicorn."""
    import uvicorn

    from testgen.utils.plugins import discover

    for plugin in discover():
        try:
            plugin.load()
        except Exception:
            LOG.warning("Plugin %s failed to load (Streamlit-only?), skipping", plugin.package)

    app = create_app()

    ssl_kwargs = {}
    if settings.API_TLS_ENABLED:
        ssl_kwargs["ssl_certfile"] = settings.SSL_CERT_FILE
        ssl_kwargs["ssl_keyfile"] = settings.SSL_KEY_FILE

    LOG.info(
        "Starting server on %s:%s (TLS: %s, MCP: %s)",
        settings.API_HOST,
        settings.API_PORT,
        "enabled" if settings.API_TLS_ENABLED else "disabled",
        "enabled" if settings.MCP_ENABLED else "disabled",
    )
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, log_level="info", **ssl_kwargs)
