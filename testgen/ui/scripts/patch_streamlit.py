
import json
import os
import pathlib
import re
import shutil

import streamlit
import streamlit.components.v2.manifest_scanner as streamlit_manifest_scanner
from bs4 import BeautifulSoup, Tag

from testgen.common.holiday_service import list_holiday_calendars
from testgen.ui.static_cache import HASH_PARAM, STATIC_FOLDER, STATIC_PATH_PREFIX, hash_static_files

INJECTED_CLASS = "testgen-mods"
STREAMLIT_ROOT = pathlib.Path(streamlit.__file__).parent
STREAMLIT_INDEX = STREAMLIT_ROOT / "static" / "index.html"
STREAMLIT_JS_FOLDER = STREAMLIT_ROOT / "static" / "static" / "js"
STREAMLIT_CSS_FOLDER = STREAMLIT_ROOT / "static" / "static" / "css"
TESTGEN_ROOT = pathlib.Path(__file__).parent.parent.parent
TESTGEN_STATIC_FOLDER = STATIC_FOLDER
STATIC_FILES = [
    "css/style.css",
    "css/shared.css",
    "css/roboto-font-faces.css",
    "css/material-symbols-rounded.css",
    "css/code-highlight.css",
    "js/scripts.js",
    "js/sidebar.js",
    "js/van.min.js",
    "js/highlight.min.js",
]


GENERATED_HOLIDAY_MODULE = TESTGEN_STATIC_FOLDER / "js" / "holiday_calendars.js"
STATIC_URL_REFERENCE = re.compile(rf"""url\((["']?)({STATIC_PATH_PREFIX}[^)"']+)\1\)""")


def patch(dev: bool = False) -> None:
    _generate_holiday_calendars_module()
    patch_index()
    if dev:
        _allow_pyproject_from_editable_installs()


def _generate_holiday_calendars_module() -> None:
    calendars = json.dumps(list_holiday_calendars(), indent=4)
    GENERATED_HOLIDAY_MODULE.write_text(
        "// Generated at startup from the backend `holidays` package. Do not edit.\n"
        f"const holidayCodes = {calendars};\n\n"
        "export { holidayCodes };\n",
        encoding="utf-8",
    )


def _backup_path(file_path: pathlib.Path) -> pathlib.Path:
    # Keyed by version so a backup left behind by an upgraded Streamlit is never restored over the new files
    return file_path.with_name(f"{file_path.name}.{streamlit.__version__}.bak")


def patch_index() -> None:
    """
    Rebuilds the index.html inside the streamlit package from its original, injecting TestGen's styles and scripts.

    Every injected URL carries a hash of its file's content, and an import map gives every script import one, so a
    browser keeps a cached file only until its content changes. Stylesheets that reference other static files are
    inlined with those references hashed.

    The file is written only when its content changes.

    NOTE: keeps a .bak of the original index.html file
    """
    streamlit_index_backup = _backup_path(STREAMLIT_INDEX)
    if not streamlit_index_backup.exists():
        shutil.copy(STREAMLIT_INDEX, streamlit_index_backup)

    html = BeautifulSoup(streamlit_index_backup.read_text(), features="html.parser")
    head = html.find(name="head")
    if not head:
        return

    hashed_urls = {
        url: f"{url}?{HASH_PARAM}={file_hash}" for url, file_hash in hash_static_files(TESTGEN_STATIC_FOLDER).items()
    }

    # Browsers ignore an import map that follows the first module script, and Streamlit's own bundle is one
    import_map = html.new_tag("script", attrs={"type": "importmap", "class": INJECTED_CLASS})
    import_map.string = json.dumps(
        {"imports": {url: hashed for url, hashed in hashed_urls.items() if url.endswith(".js")}}
    )
    if charset := head.find("meta", charset=True):
        charset.insert_after(import_map)
    else:
        head.insert(0, import_map)

    for relative_path in STATIC_FILES:
        if (TESTGEN_STATIC_FOLDER / relative_path).exists():
            if tag := _create_tag(relative_path, html, hashed_urls):
                head.append(tag)

    patched_index = str(html)
    if STREAMLIT_INDEX.read_text() == patched_index:
        return
    staged_index = STREAMLIT_INDEX.with_name(f"{STREAMLIT_INDEX.name}.{os.getpid()}.tmp")
    try:
        staged_index.write_text(patched_index)
        os.replace(staged_index, STREAMLIT_INDEX)
    finally:
        staged_index.unlink(missing_ok=True)


def _create_tag(relative_filepath: str, html: BeautifulSoup, hashed_urls: dict[str, str]) -> Tag | None:
    hashed_url = hashed_urls[f"{STATIC_PATH_PREFIX}{relative_filepath}"]
    if relative_filepath.endswith(".js"):
        return html.new_tag("script", attrs={"type": "module", "src": hashed_url, "class": INJECTED_CLASS})
    if relative_filepath.endswith(".css"):
        stylesheet = (TESTGEN_STATIC_FOLDER / relative_filepath).read_text()
        if not STATIC_URL_REFERENCE.search(stylesheet):
            return html.new_tag("link", attrs={"href": hashed_url, "rel": "stylesheet", "class": INJECTED_CLASS})
        # A relative url() would drop the stylesheet's own hash, so the references are hashed in place
        style = html.new_tag("style", attrs={"class": INJECTED_CLASS})
        style.string = STATIC_URL_REFERENCE.sub(
            lambda match: f"url({match[1]}{hashed_urls.get(match[2], match[2])}{match[1]})", stylesheet
        )
        return style
    return None


def _allow_pyproject_from_editable_installs() -> None:
    injected_functions = """
import json


def _pyproject_via_editable_package(dist: importlib.metadata.Distribution) -> Path | None:
    from urllib.parse import urlparse, unquote

    if _is_editable_package(dist):
        try:
            content = dist.read_text("direct_url.json")
            data = json.loads(content)
            if not data.get("dir_info", {}).get("editable", False):
                return None
            file_url = data.get("url")
            if not file_url or not file_url.startswith("file://"):
                return None
            path_str = unquote(urlparse(file_url).path)
            project_root = Path(path_str)
            pyproject_path = project_root / "pyproject.toml"
            if pyproject_path.exists():
                return pyproject_path
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _is_editable_package(dist: importlib.metadata.Distribution) -> bool:
    content = dist.read_text("direct_url.json")
    if not content:
        return False
    try:
        data = json.loads(content)
        return data.get("dir_info", {}).get("editable", False)
    except (json.JSONDecodeError, ValueError):
        pass
    return False


IGNORED_DIR_NAMES = ["__pycache__", "invocations", "tests"]
def _find_first_package_dir(project_path: Path) -> Path | None:
    for item in sorted(project_path.iterdir()):
        if item.is_dir():
            if item.name.startswith(".") or item.name in IGNORED_DIR_NAMES:
                continue
            if (item / "__init__.py").exists():
                return item
    return None
"""

    file_path = pathlib.Path(streamlit_manifest_scanner.__file__)
    backup_file_path = _backup_path(file_path)

    if not backup_file_path.exists():
        shutil.copy(file_path, backup_file_path)
    shutil.copy(backup_file_path, file_path)

    content = file_path.read_text()
    to_replace = """    for finder in (
        _pyproject_via_read_text,
        _pyproject_via_dist_files,
        lambda d: _pyproject_via_import_spec(d, package_name),
    ):"""
    new_value = """    for finder in (
        _pyproject_via_read_text,
        _pyproject_via_dist_files,
        lambda d: _pyproject_via_import_spec(d, package_name),
        _pyproject_via_editable_package,
    ):"""

    new_content = content + "\n" + injected_functions
    new_content = new_content.replace(to_replace, new_value)

    to_replace = """    if not package_root:
        package_root = pyproject_path.parent"""
    new_value = """    if not package_root:
        if not (pyproject_path.parent / "__init__.py").exists():
            package_root = _find_first_package_dir(pyproject_path.parent)

    if not package_root:
        package_root = pyproject_path.parent"""

    new_content = new_content.replace(to_replace, new_value)

    file_path.write_text(new_content)


if __name__ == "__main__":
    patch(dev=True)
    print("patched internal streamlit files")  # noqa: T201
