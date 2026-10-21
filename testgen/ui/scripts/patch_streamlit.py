
import json
import pathlib
import shutil

import streamlit
import streamlit.components.v2.manifest_scanner as streamlit_manifest_scanner
from bs4 import BeautifulSoup, Tag

from testgen.common.holiday_service import list_holiday_calendars

INJECTED_CLASS = "testgen-mods"
STREAMLIT_ROOT = pathlib.Path(streamlit.__file__).parent
STREAMLIT_INDEX = STREAMLIT_ROOT / "static" / "index.html"
STREAMLIT_JS_FOLDER = STREAMLIT_ROOT / "static" / "static" / "js"
STREAMLIT_CSS_FOLDER = STREAMLIT_ROOT / "static" / "static" / "css"
TESTGEN_ROOT = pathlib.Path(__file__).parent.parent.parent
TESTGEN_STATIC_FOLDER = pathlib.Path(__file__).parent.parent.parent / "ui" / "static"
STATIC_FILES = [
    "css/style.css",
    "css/shared.css",
    "css/roboto-font-faces.css",
    "css/material-symbols-rounded.css",
    "css/highlight-default-theme.min.css",
    "css/highlight-dark-theme.min.css",
    "js/scripts.js",
    "js/sidebar.js",
    "js/van.min.js",
    "js/highlight.min.js",
]


GENERATED_HOLIDAY_MODULE = TESTGEN_STATIC_FOLDER / "js" / "holiday_calendars.js"


def patch(dev: bool = False) -> None:
    _patch_streamlit_index(*STATIC_FILES, dev=dev)
    _generate_holiday_calendars_module()
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


def _patch_streamlit_index(*static_files: str, dev: bool = False) -> None:
    """
    Patches the index.html inside streamlit package to inject Testgen's
    own styles and scripts before rendering time.

    The new tags are injected with a distinctive class so that on the
    next streamlit re-run it skips injecting (making it a tag faster
    than st.markdown method).

    NOTE: keeps a .bak of the original index.html file

    :param filename: list of path to valid .css and .js files
    :param dev: to use in development while actively changing the
    injected files to force re-injection
    """

    html = BeautifulSoup(STREAMLIT_INDEX.read_text(), features="html.parser")
    if dev or not html.find_all(attrs={"class": INJECTED_CLASS}):
        streamlit_index_backup = _backup_path(STREAMLIT_INDEX)

        if not streamlit_index_backup.exists():
            shutil.copy(STREAMLIT_INDEX, streamlit_index_backup)
        else:
            shutil.copy(streamlit_index_backup, STREAMLIT_INDEX)
            html = BeautifulSoup(STREAMLIT_INDEX.read_text(), features="html.parser")

        head = html.find(name="head")
        if head:
            for relative_path in static_files:
                if (TESTGEN_STATIC_FOLDER / relative_path).exists():
                    if tag := _create_tag(relative_path, html):
                        head.append(tag)
            STREAMLIT_INDEX.write_text(str(html))


def _create_tag(relative_filepath: str, html: BeautifulSoup) -> Tag | None:
    tag_for_ext = {
        ".css": lambda: html.new_tag(
            "link", **{"href": f"/app/static/{relative_filepath}", "rel": "stylesheet", "class": INJECTED_CLASS}
        ),
        ".js": lambda: html.new_tag(
            "script", **{"type": "module", "src": f"/app/static/{relative_filepath}", "class": INJECTED_CLASS}
        ),
    }

    extension = f".{relative_filepath.split('.')[-1]}"
    if extension in tag_for_ext:
        return tag_for_ext[extension]()
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
