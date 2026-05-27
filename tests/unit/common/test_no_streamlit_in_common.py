"""Boundary guard — `testgen/common/` must not import Streamlit or use its cache.

Streamlit caches in-process even outside its runtime; a `@st.cache_data` decorator
on a shared model method leaks stale results into MCP, API, scheduler, and CLI
processes. Cache decorators belong in the UI layer (`testgen/ui/services/query_cache.py`
or view-local helpers), not in `common/`.

Exception: ``streamlit_authenticator`` is a separately-packaged dependency unrelated
to this boundary; it's allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import testgen.common as common_pkg

COMMON_ROOT = Path(common_pkg.__file__).resolve().parent

_BANNED_PATTERNS = [
    re.compile(r"^\s*import\s+streamlit\s*(?:as\s+\w+)?\s*(?:#.*)?$"),
    re.compile(r"^\s*from\s+streamlit(?:\.|\s)"),
    re.compile(r"@st\.cache_(data|resource)\b"),
]


def _python_files() -> list[Path]:
    return sorted(p for p in COMMON_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(COMMON_ROOT)))
def test_no_streamlit_or_cache_decorator(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    offending: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in _BANNED_PATTERNS:
            if pattern.search(line):
                offending.append((lineno, line.rstrip()))
                break
    assert not offending, (
        f"{path.relative_to(COMMON_ROOT)} imports Streamlit or applies an "
        f"@st.cache_* decorator. Caching belongs in the UI layer "
        f"(testgen/ui/services/query_cache.py). Offending lines: {offending}"
    )
