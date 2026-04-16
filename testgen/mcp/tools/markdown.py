"""Lightweight Markdown document builder for MCP tool responses.

All escaping and formatting happens inside the builder — callers never
touch raw markdown syntax.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

# ---------------------------------------------------------------------------
# Escape / format helpers
#
# Table cells auto-escape | and \ (structural) and replace newlines.
# field(), bullets(), text(), and headings don't escape — caller controls
# content. Use escape() for untrusted data, code() for code spans.
# ---------------------------------------------------------------------------

_INLINE_RE = re.compile(r"([\\*_\[\]`])")
_TABLE_CELL_RE = re.compile(r"([\\|])")
_ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


def _escape_inline(value: str) -> str:
    """Escape characters that trigger markdown inline formatting."""
    return _INLINE_RE.sub(r"\\\1", value)


def _escape_table_cell(value: str) -> str:
    """Escape all markdown-significant characters in a table cell."""
    return _TABLE_CELL_RE.sub(r"\\\1", value)


def _format_dt(value: object) -> str | None:
    """Return 'YYYY-MM-DD HH:MM UTC' for datetime objects and ISO strings, else None."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M") + " UTC"
    if isinstance(value, str) and _ISO_DT_RE.match(value):
        return value[:16].replace("T", " ") + " UTC"
    return None


def _format_part(value: object) -> str:
    """Format a single value for text() parts — datetime-aware, no escaping."""
    if value is None:
        return "\u2014"
    return dt_str if (dt_str := _format_dt(value)) else str(value)


# ---------------------------------------------------------------------------
# MdDoc
# ---------------------------------------------------------------------------


class MdDoc:
    """Markdown document builder for MCP tool responses."""

    def __init__(self) -> None:
        self._sections: list[str] = []

    # -- structural elements ------------------------------------------------

    def heading(self, level: int, text: str) -> MdDoc:
        """Add a heading (levels 1-3). Text is not escaped."""
        self._sections.append(f"{'#' * level} {text}")
        return self

    def field(self, label: str, value: object, *, code: bool = False) -> MdDoc:
        """Add a bullet field: ``- **Label:** value``.

        * ``None`` → em-dash
        * ``datetime`` / ISO string → ``YYYY-MM-DD HH:MM UTC``
        * ``code=True`` → wraps value in backticks
        * Otherwise → ``str()``

        No escaping — caller controls content. Use ``escape()`` for untrusted data.
        Consecutive ``field()`` calls merge into one tight block.
        """
        display = self._format_field_value(value, code=code)
        line = f"- **{label}:** {display}"
        if self._sections and self._sections[-1].startswith("- **"):
            self._sections[-1] += "\n" + line
        else:
            self._sections.append(line)
        return self

    def text(self, *parts: object) -> MdDoc:
        """Add a plain text paragraph from one or more parts joined by spaces.

        * Strings pass through as-is (no escaping — caller controls content)
        * ``datetime`` / ISO string → ``YYYY-MM-DD HH:MM UTC``
        * ``None`` → em-dash
        * Numbers → ``str()``
        """
        if parts:
            formatted = " ".join(_format_part(p) for p in parts)
            self._sections.append(formatted)
        return self

    def table(
        self,
        headers: list[str],
        rows: list[list[object]],
        *,
        code: list[int] | None = None,
        null_display: str = "\u2014",
    ) -> MdDoc:
        """Add a markdown table.

        Cells are escaped (pipes, backslashes, newlines) and datetime-formatted.
        *code* is a list of column indices whose non-null values are wrapped in backtick code spans.
        """
        if not rows:
            self._sections.append("_No rows._")
            return self
        code_cols = set(code) if code else set()
        header_line = "| " + " | ".join(_escape_table_cell(str(h)) for h in headers) + " |"
        separator = "| " + " | ".join("---" for _ in headers) + " |"
        body_lines = []
        for row in rows:
            cells = []
            for i, v in enumerate(row):
                if i in code_cols and v is not None:
                    # Code spans protect their content — skip table-cell escaping
                    s = str(v).replace("\n", " ")
                    cells.append(self.code(s))
                else:
                    cells.append(self._format_cell(v, null_display))

            body_lines.append("| " + " | ".join(cells) + " |")
        self._sections.append("\n".join([header_line, separator, *body_lines]))
        return self

    def table_from_dataframe(
        self,
        df: pd.DataFrame | None,
        *,
        null_display: str = "_NULL_",
    ) -> MdDoc:
        """Add a markdown table from a pandas DataFrame."""
        import pandas as _pd

        if df is None or df.empty:
            self._sections.append("_No rows._")
            return self
        headers = list(df.columns)
        rows: list[list[object]] = []
        for _, row in df.iterrows():
            rows.append([None if _pd.isna(v) else v for v in row])
        return self.table(headers, rows, null_display=null_display)

    def bullets(self, items: list[object]) -> MdDoc:
        """Add a bullet list. No escaping — caller controls content."""
        lines = [f"- {_format_part(item)}" for item in items]
        self._sections.append("\n".join(lines))
        return self

    def code_block(self, content: str, language: str = "") -> MdDoc:
        """Add a fenced code block. Uses longer fence if content contains triple backticks."""
        fence = "````" if "```" in content else "```"
        self._sections.append(f"{fence}{language}\n{content}\n{fence}")
        return self

    # -- escaping -----------------------------------------------------------

    @staticmethod
    def escape(value: str) -> str:
        """Escape markdown inline formatting characters in a string.

        Use this for untrusted or user-generated data passed to ``field()``,
        ``bullets()``, or ``text()``. Not needed for table cells (those are
        always escaped) or code blocks.
        """
        return _escape_inline(value)

    @staticmethod
    def code(value: str | None) -> str:
        """Wrap a string in a backtick code span.

        Handles embedded backticks (double-fence) and newlines (replaced
        with literal ``\\n``). Returns em-dash for empty/None values.
        """
        if not value:
            return "\u2014"
        s = value.replace("\n", "\\n")
        return f"`` {s} ``" if "`" in s else f"`{s}`"

    # -- output -------------------------------------------------------------

    def render(self) -> str:
        """Join all sections with blank-line separation."""
        return "\n\n".join(self._sections)

    # -- private helpers ----------------------------------------------------

    @staticmethod
    def _format_field_value(value: object, *, code: bool = False) -> str:
        if value is None:
            return "\u2014"
        if dt_str := _format_dt(value):
            return MdDoc.code(dt_str) if code else dt_str
        s = str(value)
        return MdDoc.code(s) if code else s

    @staticmethod
    def _format_cell(value: object, null_display: str) -> str:
        if value is None:
            return null_display
        if dt_str := _format_dt(value):
            return dt_str
        s = str(value).replace("\n", " ")
        return _escape_table_cell(s)
