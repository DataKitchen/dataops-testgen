"""TestGen server — combined FastAPI + MCP application."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from testgen import settings

_FAVICON_PATH = Path(__file__).resolve().parent.parent / "ui" / "assets" / "favicon.ico"

# authlib rejects http:// URIs by default; allow in debug mode for local dev
if settings.IS_DEBUG:
    os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")

from testgen.api.app import router as api_router
from testgen.api.jobs import router as jobs_router
from testgen.api.oauth.metadata import router as metadata_router
from testgen.api.oauth.routes import init_routes
from testgen.api.oauth.routes import router as oauth_router
from testgen.api.oauth.server import create_authorization_server
from testgen.api.runs import router as runs_router
from testgen.api.test_definitions import router as test_definitions_router
from testgen.common import version_service
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")


def _patch_openapi_schema(app: FastAPI) -> None:
    """Strip Pydantic-generated ``title`` fields from the OpenAPI schema.

    Pydantic v2 auto-generates a ``title`` for every model field by converting
    the Python name to title case (e.g. ``completed_at`` → ``"Completed At"``).
    Redoc displays these next to the field name, producing redundant labels like
    ``completed_at  string <date-time> (Completed At)``.  For nullable unions
    (``anyOf``) the effect is worse: each branch gets its own title, leading to
    ``"Completed At (string) or Completed At (null) (Completed At)"``.

    This post-processor wraps ``app.openapi()`` and strips ``title`` from:
    - Component schema properties and their ``anyOf`` branches
    - Top-level component schema titles (shown in Redoc sidebar)
    - Path/query parameter schemas

    FastAPI caches the schema after the first call, so the patching runs once.
    """
    _original = app.openapi

    def patched_openapi() -> dict:
        schema = _original()
        for model_schema in schema.get("components", {}).get("schemas", {}).values():
            for prop in model_schema.get("properties", {}).values():
                prop.pop("title", None)
                for branch in prop.get("anyOf", []):
                    branch.pop("title", None)
            model_schema.pop("title", None)
        for methods in schema.get("paths", {}).values():
            for details in methods.values():
                if isinstance(details, dict):
                    for param in details.get("parameters", []):
                        param.get("schema", {}).pop("title", None)
        return schema

    app.openapi = patched_openapi  # type: ignore[method-assign]


def create_app(version: str | None = None) -> FastAPI:
    version_data = None if version else with_database_session(version_service.get_version)()

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

    tags_metadata = [
        {"name": "Jobs", "description": "Submit, poll, cancel, and list job executions (profiling, tests, generation)."},
        {"name": "Test Definitions", "description": "Export and import test definitions across environments."},
        {"name": "OAuth", "description": "OAuth 2.1 authorization code flow and token management."},
        {"name": "API", "description": "Health and version information."},
    ]

    app = FastAPI(
        title=f"{version_data.edition} API" if version_data else "TestGen API",
        summary="REST API for DataOps Data Quality TestGen.",
        description=(
            "Automate profiling, test execution, and test generation jobs. "
            "Export and import test definitions for promotion across environments.\n\n"
            "**Authentication**: OAuth 2.1 authorization code flow. "
            "See `GET /.well-known/oauth-authorization-server` for discovery."
        ),
        version=version or version_data.current or "dev",
        contact={"name": "DataKitchen Support", "email": "support@datakitchen.io", "url": "https://datakitchen.io"},
        terms_of_service="https://datakitchen.io/terms-of-service/",
        docs_url=None,
        redoc_url="/api/docs",
        openapi_url="/api/openapi.json",
        openapi_tags=tags_metadata,
        lifespan=lifespan,
    )

    server = create_authorization_server()
    init_routes(server)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(_FAVICON_PATH)

    _patch_openapi_schema(app)

    app.include_router(metadata_router)
    app.include_router(oauth_router)
    app.include_router(api_router)
    app.include_router(jobs_router)
    app.include_router(runs_router)
    app.include_router(test_definitions_router)

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
