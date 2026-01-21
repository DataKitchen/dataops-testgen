# ruff: noqa: TRY002

import pathlib
import re
import shutil

import streamlit
import streamlit.web.server.app_static_file_handler as streamlit_app_static_file_handler
from bs4 import BeautifulSoup, Tag

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
    "js/scripts.js",
    "js/sidebar.js",
    "js/van.min.js",
]


def patch(force: bool = False) -> None:
    _allow_static_files([".js", ".css"])
    _patch_streamlit_index(*STATIC_FILES, force=force)


def _patch_streamlit_index(*static_files: str, force: bool = False) -> None:
    """
    Patches the index.html inside streamlit package to inject Testgen's
    own styles and scripts before rendering time.

    The new tags are injected with a distinctive class so that on the
    next streamlit re-run it skips injecting (making it a tag faster
    than st.markdown method).

    NOTE: keeps a .bak of the original index.html file

    :param filename: list of path to valid .css and .js files
    :param force: to use in development while actively changing the
    injected files to force re-injection
    """

    html = BeautifulSoup(STREAMLIT_INDEX.read_text(), features="html.parser")
    if force or not html.find_all(attrs={"class": INJECTED_CLASS}):
        streamlit_index_backup = STREAMLIT_INDEX.with_suffix(".bak")

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

    extension = f".{relative_filepath.split(".")[-1]}"
    if extension in tag_for_ext:
        return tag_for_ext[extension]()
    return None


def _allow_static_files(extensions: list[str]):
    file_path = pathlib.Path(streamlit_app_static_file_handler.__file__)
    backup_file_path = file_path.with_suffix(".py.bak")

    if not backup_file_path.exists():
        shutil.copy(file_path, backup_file_path)
    shutil.copy(backup_file_path, file_path)

    content = file_path.read_text()

    match = re.search(r"(SAFE_APP_STATIC_FILE_EXTENSIONS\s*=\s*\()([^)]*)(\))", content, re.DOTALL)

    if match:
        prefix = match.group(1)
        existing_extensions_str = match.group(2)
        suffix = match.group(3)

        existing_extensions: list[str] = []
        for line in existing_extensions_str.splitlines():
            stripped_line = line.strip()
            if stripped_line and not stripped_line.startswith("#"):
                found_exts = re.findall(r'\"(\.[a-zA-Z0-9]+)\"', stripped_line)
                existing_extensions.extend(found_exts)

        all_extensions = []
        for ext in existing_extensions + extensions:
            if not ext.startswith("."):
                ext = "." + ext
            all_extensions.append(ext)
        all_extensions = sorted(set(all_extensions))

        new_extensions_formatted_lines = []
        for ext in all_extensions:
            new_extensions_formatted_lines.append(f'    "{ext}",')

        new_tuple_content = "\n".join(new_extensions_formatted_lines)
        new_tuple_str = f"{prefix}\n{new_tuple_content}\n{suffix}"
        
        new_content = content.replace(match.group(0), new_tuple_str)
        file_path.write_text(new_content)
    else:
        raise RuntimeError("Could not find SAFE_APP_STATIC_FILE_EXTENSIONS in the file.")

