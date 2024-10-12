# ruff: noqa: TRY002

import functools
import pathlib
import shutil

import streamlit
from bs4 import BeautifulSoup, Tag

INJECTED_CLASS = "testgen-mods"
STREAMLIT_ROOT = pathlib.Path(streamlit.__file__).parent
STREAMLIT_INDEX = STREAMLIT_ROOT / "static" / "index.html"
STREAMLIT_JS_FOLDER = STREAMLIT_ROOT / "static" / "static" / "js"
STREAMLIT_CSS_FOLDER = STREAMLIT_ROOT / "static" / "static" / "css"
TESTGEN_ROOT = pathlib.Path(__file__).parent.parent.parent


def patch(force: bool = False) -> list[str]:
    operations = [
        "ui/assets/style.css:insert",
        "ui/assets/scripts.js:insert",
        "ui/components/frontend/css/KFOmCnqEu92Fr1Mu7GxKOzY.woff2:copy",
        "ui/components/frontend/css/KFOmCnqEu92Fr1Mu4mxK.woff2:copy",
        "ui/components/frontend/css/KFOlCnqEu92Fr1MmEU9fChc4EsA.woff2:copy",
        "ui/components/frontend/css/KFOlCnqEu92Fr1MmEU9fBBc4.woff2:copy",
        "ui/components/frontend/css/material-symbols-rounded.woff2:copy",
        "ui/components/frontend/css/roboto-font-faces.css:inject",
        "ui/components/frontend/css/material-symbols-rounded.css:inject",
        "ui/components/frontend/js/van.min.js:copy",
        "ui/components/frontend/js/components/sidebar.js:inject",
    ]

    _patch_streamlit_index(*operations, force=force)

    return [op.split(":")[0] for op in operations]


def _patch_streamlit_index(*operations: str, force: bool = False) -> None:
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
            actions = {
                "insert": _inline_tag,
                "copy": _sourced_tag,
                "inject": functools.partial(_sourced_tag, inject=True),
            }
            for operation in operations:
                filename, action = operation.split(":")
                if (filepath := (TESTGEN_ROOT / filename)).exists():
                    if tag := actions[action](filepath, html):
                        head.append(tag)

            STREAMLIT_INDEX.write_text(str(html))


def _inline_tag(filepath: pathlib.Path, html: BeautifulSoup, **_) -> Tag:
    tag_for_ext = {
        ".css": lambda: html.new_tag("style", **{"class": INJECTED_CLASS}),
        ".js": lambda: html.new_tag("script", **{"type": "module", "class": INJECTED_CLASS}),
    }

    try:
        tag = tag_for_ext[filepath.suffix]()
    except:
        raise Exception(f"Unsupported insert operation for file with extension {filepath.suffix}") from None

    tag.string = filepath.read_text()
    return tag


def _sourced_tag(filepath: pathlib.Path, html: BeautifulSoup, inject: bool = False) -> Tag | None:
    tag_for_ext = {
        ".css": lambda: html.new_tag(
            "link", **{"href": f"./static/css/{filepath.name}", "rel": "stylesheet", "class": INJECTED_CLASS}
        ),
        ".js": lambda: html.new_tag(
            "script", **{"type": "module", "src": f"./static/js/{filepath.name}", "class": INJECTED_CLASS}
        ),
    }
    copy_to = ({".js": STREAMLIT_JS_FOLDER}).get(filepath.suffix, STREAMLIT_CSS_FOLDER)

    shutil.copy(filepath, copy_to)

    if not inject or filepath.suffix not in tag_for_ext:
        return None

    return tag_for_ext[filepath.suffix]()
