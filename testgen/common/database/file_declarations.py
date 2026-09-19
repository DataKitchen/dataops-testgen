"""File declarations — the table list a table group carries when its connection reads files.

A declaration names one table: a name, a URI relative to the connection's base path, a format,
and optional format-specific settings. It becomes one view in the target database, and therefore
one table for every purpose in the product.

The URI names a single file or a glob pattern. A pattern is one table whose rows span every
matching file. A folder is not accepted on its own: a pattern says which files in it to read and
whether to descend into its subfolders, where a bare folder leaves both to be guessed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from testgen.common.enums import FileFormat

LOG = logging.getLogger("testgen")

BASE_PATH_PARAMETER = "base_path"

NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

NAME_REQUIRED = "Name is required."
NAME_INVALID = "Name must start with a letter or underscore and contain only letters, numbers and underscores."
NAME_DUPLICATE = "Name is already used by another table in this table group."
URI_REQUIRED = "File or Pattern is required."
URI_HAS_CREDENTIALS = "File or Pattern cannot contain credentials. Credentials are configured on the connection."
URI_OUTSIDE_BASE_PATH = "File or Pattern must be inside the connection base path."
URI_IS_FOLDER = "File or Pattern names a folder. Use a pattern to read the files in it, such as sales/*.csv."
NO_DECLARATIONS = "Declare at least one table."
NO_FILES_MATCHED = "No files matched this path."

# Query-string keys that carry a signed URL. Credentials belong on the connection, where they are
# stored encrypted, rather than in the SQL text of a view.
_CREDENTIAL_KEYS = ("sig", "x-amz-signature", "x-amz-credential", "x-goog-signature", "signature")

_GLOB_CHARACTERS = "*?["

_READERS: dict[FileFormat, str] = {
    FileFormat.CSV: "read_csv",
    FileFormat.PARQUET: "read_parquet",
    FileFormat.JSON: "read_json",
}

# CSV settings a declaration may override, mapped to the reader argument each one becomes.
# Anything that makes a read tolerant of malformed data is absent. A tolerant read drops rows
# without saying so, and which rows it drops depends on the columns a query happens to project, so
# a column-scoped test and a table-scoped count end up disagreeing about how many rows exist.
_CSV_OPTIONS: dict[str, tuple[str, type]] = {
    "delimiter": ("delim", str),
    "header": ("header", bool),
    "quote": ("quote", str),
    "escape": ("escape", str),
}

_OPTIONS_BY_FORMAT: dict[FileFormat, dict[str, tuple[str, type]]] = {
    FileFormat.CSV: _CSV_OPTIONS,
    FileFormat.PARQUET: {},
    FileFormat.JSON: {},
}

# Reader arguments every declaration of a format gets, whatever its settings say.
#
# A quoted empty field is an empty string in every CSV convention, and an unquoted one is the
# ambiguous case. DuckDB reads both as NULL by default, which would leave TestGen unable to tell a
# blank apart from a missing value -- and unable to report a non-standard blank at all, since by
# the time the data arrives there are none left.
_FORMAT_ARGUMENTS: dict[FileFormat, tuple[str, ...]] = {
    FileFormat.CSV: ("allow_quoted_nulls = false",),
    FileFormat.PARQUET: (),
    FileFormat.JSON: (),
}


@dataclass(frozen=True, slots=True)
class FileDeclaration:
    name: str
    uri: str
    format: FileFormat
    options: dict[str, Any] = field(default_factory=dict)


def parse_file_declarations(raw: list[dict[str, Any]] | None) -> list[FileDeclaration]:
    """Read the stored JSON list, skipping any entry whose format is not one TestGen reads."""
    readable = {str(member) for member in FileFormat}
    declarations = []
    for entry in raw or []:
        declared_format = str(entry.get("format") or "").strip().lower()
        if declared_format not in readable:
            LOG.error(f"Table {entry.get('name')!r} declares format {declared_format!r}, which TestGen cannot read")
            continue
        file_format = FileFormat(declared_format)
        declarations.append(
            FileDeclaration(
                name=str(entry.get("name") or "").strip(),
                uri=str(entry.get("uri") or "").strip(),
                format=file_format,
                options=entry.get("options") or {},
            )
        )
    return declarations


def validate_file_declarations(raw: list[dict[str, Any]] | None, base_path: str) -> list[str]:
    """Return every rule a declaration list breaks, each prefixed with the table it belongs to."""
    entries = raw or []
    if not entries:
        return [NO_DECLARATIONS]

    errors: list[str] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        name = str(entry.get("name") or "").strip()
        uri = str(entry.get("uri") or "").strip()
        label = name or f"Table {position}"

        if not name:
            errors.append(f"{label}: {NAME_REQUIRED}")
        elif not NAME_PATTERN.match(name):
            errors.append(f"{label}: {NAME_INVALID}")
        # DuckDB folds identifiers even when quoted, so names that differ only in case collide.
        elif name.casefold() in seen:
            errors.append(f"{label}: {NAME_DUPLICATE}")
        seen.add(name.casefold())

        if not uri:
            errors.append(f"{label}: {URI_REQUIRED}")
            continue
        if has_embedded_credentials(uri):
            errors.append(f"{label}: {URI_HAS_CREDENTIALS}")
            continue
        if not is_inside_base_path(base_path, uri):
            errors.append(f"{label}: {URI_OUTSIDE_BASE_PATH}")
        elif names_folder(base_path, uri):
            errors.append(f"{label}: {URI_IS_FOLDER}")

    return errors


def has_embedded_credentials(uri: str) -> bool:
    """Whether a URI carries a signed-URL credential in its query string."""
    _, separator, query = uri.partition("?")
    if not separator:
        return False
    keys = {pair.partition("=")[0].strip().lower() for pair in query.split("&")}
    return any(key in keys for key in _CREDENTIAL_KEYS)


def resolve_uri(base_path: str, uri: str) -> Path:
    """The absolute path a declaration URI names, with the base path applied.

    An absolute URI keeps its own value rather than being joined, so that a user who pastes the
    full container path of a file already under the base path gets the file they named. Whether
    that lands inside the base path is the containment check's business.
    """
    candidate = Path(uri)
    if not candidate.is_absolute():
        candidate = Path(base_path) / uri
    return _lexical_resolve(candidate)


def is_inside_base_path(base_path: str, uri: str) -> bool:
    if not base_path:
        return False
    return resolve_uri(base_path, uri).is_relative_to(_lexical_resolve(Path(base_path)))


def _lexical_resolve(path: Path) -> Path:
    """Absolute form of ``path`` with ``.`` and ``..`` collapsed and symlinks followed.

    ``Path.resolve`` follows symlinks for the parts that exist, which is what makes a link
    inside the base path pointing outside it fail the containment check. It leaves the rest
    alone, so a glob pattern resolves as written.
    """
    return path.expanduser().resolve()


def is_multi_file(declaration: FileDeclaration) -> bool:
    """Whether a declaration can match more than one file, and so needs its columns unioned."""
    return any(character in declaration.uri for character in _GLOB_CHARACTERS)


def names_folder(base_path: str, uri: str) -> bool:
    """Whether a URI with no glob characters names a directory rather than a file."""
    if any(character in uri for character in _GLOB_CHARACTERS):
        return False
    return resolve_uri(base_path, uri).is_dir()


def read_pattern(base_path: str, declaration: FileDeclaration) -> str:
    """The path the reader is pointed at."""
    return str(resolve_uri(base_path, declaration.uri))


def create_view_statement(base_path: str, declaration: FileDeclaration, schema: str) -> str:
    """The ``CREATE VIEW`` that makes one declaration queryable.

    Raises ``ValueError`` when the declaration name is not a bare SQL identifier.
    """
    # The name becomes an identifier in DDL, and a declaration list can arrive from anywhere a
    # table group is saved. A driver that accepts several statements in one call would turn a
    # quote here into arbitrary SQL, so an unusable name stops before it reaches the text.
    if not NAME_PATTERN.match(declaration.name):
        raise ValueError(NAME_INVALID)

    arguments = [_sql_literal(read_pattern(base_path, declaration))]
    arguments.extend(_FORMAT_ARGUMENTS[declaration.format])

    declared = _OPTIONS_BY_FORMAT[declaration.format]
    for key, (argument, kind) in declared.items():
        if (value := declaration.options.get(key)) is None or value == "":
            continue
        arguments.append(f"{argument} = {_sql_value(value, kind)}")

    if is_multi_file(declaration) and declaration.format is not FileFormat.JSON:
        # Without this the first matching file defines the column list, so a column present only
        # in later files is dropped with no error. read_json unions across files on its own.
        arguments.append("union_by_name = true")

    reader = _READERS[declaration.format]
    view = f"{_sql_identifier(schema)}.{_sql_identifier(declaration.name)}"
    # Not OR REPLACE: a name that folds onto an existing view must fail rather than replace it.
    return f'CREATE VIEW {view} AS SELECT * FROM {reader}({", ".join(arguments)})'


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_value(value: Any, kind: type) -> str:
    if kind is bool:
        return "true" if value in (True, "true", "True", 1) else "false"
    return _sql_literal(str(value))
