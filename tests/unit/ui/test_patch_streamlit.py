import hashlib
import json
import pathlib
import re

import pytest
from bs4 import BeautifulSoup

from testgen.ui.scripts import patch_streamlit

pytestmark = pytest.mark.unit

BASE_INDEX = (
    '<!doctype html><html><head><meta charset="utf-8"/>'
    '<script type="module" src="./static/js/index.js"></script></head><body></body></html>'
)
FONT_CSS = (
    '@font-face { src: url("/app/static/fonts/quoted.woff2") format("woff2"); }\n'
    "@font-face { src: url(/app/static/fonts/bare.woff2) format('woff2'); }\n"
)


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:12]


@pytest.fixture
def static(tmp_path, monkeypatch) -> pathlib.Path:
    folder = tmp_path / "static"
    files = {
        "js/scripts.js": "import van from './van.min.js';",
        "js/van.min.js": "export default {};",
        "js/components/button.js": "export const Button = 1;",
        "css/shared.css": ".a { color: red; }",
        "css/fonts.css": FONT_CSS,
        "fonts/quoted.woff2": "quoted-font",
        "fonts/bare.woff2": "bare-font",
    }
    for name, content in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(content)

    index = tmp_path / "streamlit" / "index.html"
    index.parent.mkdir()
    index.write_text(BASE_INDEX)

    monkeypatch.setattr(patch_streamlit, "TESTGEN_STATIC_FOLDER", folder)
    monkeypatch.setattr(patch_streamlit, "STREAMLIT_INDEX", index)
    monkeypatch.setattr(patch_streamlit, "GENERATED_HOLIDAY_MODULE", folder / "js" / "holiday_calendars.js")
    monkeypatch.setattr(patch_streamlit, "STATIC_FILES", ["css/shared.css", "css/fonts.css", "js/scripts.js"])
    return folder


def _index() -> BeautifulSoup:
    return BeautifulSoup(patch_streamlit.STREAMLIT_INDEX.read_text(), features="html.parser")


def _import_map() -> dict[str, str]:
    return json.loads(_index().find("script", type="importmap").string)["imports"]


def test_import_map_comes_before_every_module_script(static):
    patch_streamlit.patch_index()

    scripts = _index().head.find_all("script")
    assert scripts[0]["type"] == "importmap"
    assert all(script.get("type") != "importmap" for script in scripts[1:])


def test_import_map_follows_the_charset_declaration(static):
    patch_streamlit.patch_index()

    head_tags = [tag.name for tag in _index().head.find_all(["meta", "script"])]
    assert head_tags[:2] == ["meta", "script"]
    assert _index().head.find("meta").find_next_sibling()["type"] == "importmap"


def test_failed_write_leaves_the_previous_index_intact(static, monkeypatch):
    patch_streamlit.patch_index()
    previous = patch_streamlit.STREAMLIT_INDEX.read_text()
    (static / "js" / "van.min.js").write_text("export default { changed: true };")

    original_write_text = pathlib.Path.write_text

    def write_half_then_fail(self, data, *args, **kwargs):
        original_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("disk full")

    with monkeypatch.context() as failing_writes, pytest.raises(OSError):
        failing_writes.setattr(pathlib.Path, "write_text", write_half_then_fail)
        patch_streamlit.patch_index()

    assert patch_streamlit.STREAMLIT_INDEX.read_text() == previous


def test_unchanged_index_is_not_rewritten(static):
    patch_streamlit.patch_index()
    index_folder = patch_streamlit.STREAMLIT_INDEX.parent
    index_folder.chmod(0o555)
    patch_streamlit.STREAMLIT_INDEX.chmod(0o444)
    try:
        patch_streamlit.patch_index()
    finally:
        index_folder.chmod(0o755)
        patch_streamlit.STREAMLIT_INDEX.chmod(0o644)


def test_import_map_points_every_script_at_its_content_hash(static):
    patch_streamlit.patch_index()

    hashed = {
        name: f"./app/static/{name}?h={_hash((static / name).read_bytes())}"
        for name in ["js/components/button.js", "js/scripts.js", "js/van.min.js"]
    }
    assert _import_map() == {
        **{f"/app/static/{name}": url for name, url in hashed.items()},
        **{f"./app/static/{name}": url for name, url in hashed.items()},
    }


def test_changed_script_gets_a_new_hash_and_the_others_keep_theirs(static):
    patch_streamlit.patch_index()
    before = _import_map()

    (static / "js" / "van.min.js").write_text("export default { changed: true };")
    patch_streamlit.patch_index()
    after = _import_map()

    assert after["/app/static/js/van.min.js"] != before["/app/static/js/van.min.js"]
    assert {k: v for k, v in after.items() if "van.min" not in k} == {
        k: v for k, v in before.items() if "van.min" not in k
    }


def test_injected_tags_carry_the_content_hash(static):
    patch_streamlit.patch_index()

    index = _index()
    stylesheet = index.find("link", rel="stylesheet")
    script = index.find("script", src=re.compile(r"^\./app/static/"))
    assert stylesheet["href"] == f"./app/static/css/shared.css?h={_hash((static / 'css/shared.css').read_bytes())}"
    assert script["src"] == f"./app/static/js/scripts.js?h={_hash((static / 'js/scripts.js').read_bytes())}"
    assert script["src"] == _import_map()["/app/static/js/scripts.js"]


def test_stylesheet_with_font_urls_is_inlined_with_hashed_urls(static):
    patch_streamlit.patch_index()

    index = _index()
    assert not index.find("link", href=re.compile("fonts.css"))
    style = index.find("style").string
    assert f'url("./app/static/fonts/quoted.woff2?h={_hash(b"quoted-font")}")' in style
    assert f"url(./app/static/fonts/bare.woff2?h={_hash(b'bare-font')})" in style


def test_repatching_replaces_the_previous_injection(static):
    patch_streamlit.patch_index()
    patch_streamlit.patch_index()

    index = _index()
    assert len(index.find_all("script", type="importmap")) == 1
    assert len(index.find_all("link", rel="stylesheet")) == 1
    assert len(index.find_all("style")) == 1
    assert len(index.find_all("script", src=re.compile(r"^\./app/static/"))) == 1


def test_patch_hashes_the_holiday_module_it_generates(static, monkeypatch):
    monkeypatch.setattr(patch_streamlit, "list_holiday_calendars", lambda: [{"code": "US"}])

    patch_streamlit.patch()

    holiday_module = static / "js" / "holiday_calendars.js"
    assert _import_map()["/app/static/js/holiday_calendars.js"].endswith(f"?h={_hash(holiday_module.read_bytes())}")
