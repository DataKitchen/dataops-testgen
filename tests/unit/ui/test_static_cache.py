import hashlib
import pathlib

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from testgen.ui.static_cache import IMMUTABLE, REVALIDATE, StaticCacheMiddleware, hash_static_files

pytestmark = pytest.mark.unit

VAN_CONTENT = b"export default {};"
VAN_HASH = hashlib.sha256(VAN_CONTENT).hexdigest()[:12]
OTHER_HASH = "000000000000"


@pytest.fixture
def static(tmp_path) -> pathlib.Path:
    folder = tmp_path / "static"
    (folder / "js" / "components").mkdir(parents=True)
    (folder / "js" / "van.min.js").write_bytes(VAN_CONTENT)
    (folder / "js" / "components" / "button.js").write_bytes(b"export const Button = 1;")
    return folder


def _serve(request: Request) -> PlainTextResponse:
    if request.path_params["path"] == "missing.js":
        return PlainTextResponse("not found", status_code=404)
    return PlainTextResponse("content")


def _client(static: pathlib.Path, dev: bool) -> TestClient:
    app = Starlette(
        routes=[Route("/app/static/{path:path}", _serve), Route("/{path:path}", _serve)],
        middleware=[Middleware(StaticCacheMiddleware, static_folder=static, dev=dev)],
    )
    return TestClient(app)


def test_hash_static_files_maps_every_url_to_its_content_hash(static):
    assert hash_static_files(static) == {
        "/app/static/js/van.min.js": VAN_HASH,
        "/app/static/js/components/button.js": hashlib.sha256(b"export const Button = 1;").hexdigest()[:12],
    }


def test_static_file_with_its_own_hash_is_immutable(static):
    response = _client(static, dev=False).get(f"/app/static/js/van.min.js?h={VAN_HASH}")

    assert response.headers["cache-control"] == IMMUTABLE


def test_static_file_with_another_files_hash_is_revalidated(static):
    response = _client(static, dev=False).get(f"/app/static/js/van.min.js?h={OTHER_HASH}")

    assert response.headers["cache-control"] == REVALIDATE


def test_unhashed_static_file_keeps_its_headers(static):
    response = _client(static, dev=False).get("/app/static/js/van.min.js")

    assert "cache-control" not in response.headers


def test_missing_hashed_static_file_is_not_immutable(static):
    response = _client(static, dev=False).get(f"/app/static/missing.js?h={VAN_HASH}")

    assert response.status_code == 404
    assert "cache-control" not in response.headers


def test_hash_outside_static_is_ignored(static):
    response = _client(static, dev=False).get(f"/connections?h={VAN_HASH}")

    assert "cache-control" not in response.headers


@pytest.mark.parametrize("query", [f"?h={VAN_HASH}", ""])
def test_dev_mode_revalidates_static_files(static, query):
    response = _client(static, dev=True).get(f"/app/static/js/van.min.js{query}")

    assert response.headers["cache-control"] == REVALIDATE
