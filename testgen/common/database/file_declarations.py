"""File declarations — the table list a table group carries when its connection reads files.

A declaration names one table: a name, a URI relative to the connection's base location, a format,
and optional format-specific settings. It becomes one view in the target database, and therefore
one table for every purpose in the product.

The URI names a single file or a glob pattern. A pattern is one table whose rows span every
matching file. A folder is not accepted on its own: a pattern says which files in it to read and
whether to descend into its subfolders, where a bare folder leaves both to be guessed.

The base location is a directory for a connection that reads a mounted path, and a URI such as
``s3://bucket/prefix`` or ``az://container`` for one that reads object storage. Every helper here
takes either.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from testgen.common.database.sql_quoting import sql_identifier, sql_literal
from testgen.common.enums import FileFormat

LOG = logging.getLogger("testgen")

BASE_PATH_PARAMETER = "base_path"

NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

NAME_REQUIRED = "Name is required."
NAME_INVALID = "Name must start with a letter or underscore and contain only letters, numbers and underscores."
NAME_DUPLICATE = "Name is already used by another table in this table group."
URI_REQUIRED = "File or Pattern is required."
URI_HAS_CREDENTIALS = "File or Pattern cannot contain credentials. Credentials are configured on the connection."
URI_OUTSIDE_BASE_PATH = "File or Pattern must be inside the location the connection reads from."
URI_IS_FOLDER = "File or Pattern names a folder. Use a pattern to read the files in it, such as sales/*.csv."
URI_HAS_QUERY = (
    "File or Pattern cannot contain ? on object storage. To match any one character, list the "
    "characters in brackets, such as claims_202[45].csv."
)
NO_DECLARATIONS = "Declare at least one table."
NO_FILES_MATCHED = "No files matched this path."
PATH_OUTSIDE_BASE_PATH = "This path is outside the location the connection reads from."

# Query-string keys that carry a signed URL. Credentials belong on the connection, where they are
# stored encrypted, rather than in the SQL text of a view.
_CREDENTIAL_KEYS = ("sig", "x-amz-signature", "x-amz-credential", "x-goog-signature", "signature")

_GLOB_CHARACTERS = "*?["

# ``<scheme>://<bucket or container><key>``. The key keeps its leading slash, or is empty for the
# root of the bucket. ``#`` is an ordinary key character on object storage.
_REMOTE_URI = re.compile(r"^(?P<root>[A-Za-z][A-Za-z0-9+.-]*://[^/?#]+)(?P<key>/[^?]*)?$")

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
        if has_url_query(base_path, uri):
            errors.append(f"{label}: {URI_HAS_QUERY}")
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


def is_remote(location: str) -> bool:
    """Whether a base location or URI names object storage rather than a filesystem path."""
    return _split_remote(location) is not None


def _split_remote(uri: str) -> tuple[str, str] | None:
    match = _REMOTE_URI.match(uri)
    if not match:
        return None
    return match["root"], match["key"] or ""


def _normalize_key(key: str) -> str | None:
    """The key with ``.`` and ``..`` collapsed, or ``None`` when ``..`` climbs above the root.

    Object stores treat neither as special, and DuckDB's allow-list does not either -- a key of
    ``prefix/../other`` passes an allow-list of ``prefix/`` -- so they are collapsed here, where
    the containment check can see where the URI really lands. A trailing slash marks a folder, so
    it is kept, and a last segment of ``.`` or ``..`` names a folder too.
    """
    parts: list[str] = []
    for segment in key.split("/"):
        if segment == "..":
            if not parts:
                return None
            parts.pop()
        elif segment not in ("", "."):
            parts.append(segment)
    normalized = "/" + "/".join(parts)
    if parts and (key.endswith("/") or key.rsplit("/", 1)[-1] in (".", "..")):
        normalized += "/"
    return normalized


def _locate(base_path: str, uri: str) -> str | None:
    """The path or URL a declaration URI names, or ``None`` when that is outside the base location.

    A URI that is itself a full object-storage URI keeps its own root, so one naming another bucket
    is refused; anything else is joined onto the base location.
    """
    if not base_path:
        return None
    if (base := _split_remote(base_path)) is None:
        resolved = resolve_uri(base_path, uri)
        return str(resolved) if resolved.is_relative_to(_lexical_resolve(Path(base_path))) else None
    base_root, base_key = base
    root, key = _split_remote(uri) or (base_root, f"{base_key}/{uri}")
    normalized = _normalize_key(key)
    if root != base_root or normalized is None or not (normalized + "/").startswith(base_key.rstrip("/") + "/"):
        return None
    return root + normalized


def has_url_query(base_path: str, uri: str) -> bool:
    """Whether an object-storage declaration carries a query string.

    DuckDB reads ``s3_*`` query parameters off an S3 URL as connection settings, so one can send
    the signed request to another endpoint over plain HTTP, and the allow-list does not see it:
    it matches the URL's prefix only. On object storage ``?`` only ever starts a query string; on
    a local path it is a glob character.
    """
    return is_remote(base_path) and "?" in uri


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
    return _locate(base_path, uri) is not None


def _lexical_resolve(path: Path) -> Path:
    """Absolute form of ``path`` with ``.`` and ``..`` collapsed and symlinks followed.

    ``Path.resolve`` follows symlinks for the parts that exist, which is what makes a link
    inside the base path pointing outside it fail the containment check. It leaves the rest
    alone, so a glob pattern resolves as written.
    """
    return path.expanduser().resolve()


def skip_reason(base_path: str, declaration: FileDeclaration) -> str | None:
    """Why a declaration cannot be read at all, or ``None`` when it can be."""
    # A path outside the base path is refused by the allow-list as well; checking it here keeps it
    # out of the SQL text, and is the only guard where there is no allow-list.
    if not NAME_PATTERN.match(declaration.name):
        return NAME_INVALID
    if has_url_query(base_path, declaration.uri):
        return URI_HAS_QUERY
    if not is_inside_base_path(base_path, declaration.uri):
        return PATH_OUTSIDE_BASE_PATH
    # Only a declaration saved some other way gets this far naming a folder. DuckDB would refuse
    # it with a permission error that says nothing about what to write instead.
    if names_folder(base_path, declaration.uri):
        return URI_IS_FOLDER
    return None


def is_multi_file(declaration: FileDeclaration) -> bool:
    """Whether a declaration can match more than one file, and so needs its columns unioned."""
    return any(character in declaration.uri for character in _GLOB_CHARACTERS)


def names_folder(base_path: str, uri: str) -> bool:
    """Whether a URI with no glob characters, inside the base location, names a folder rather than a file.

    Object storage has no directories to ask about, so there only a trailing slash says so. A key
    without one is read as an object.
    """
    if any(character in uri for character in _GLOB_CHARACTERS):
        return False
    if (location := _locate(base_path, uri)) is None:
        return False
    return location.endswith("/") if is_remote(base_path) else Path(location).is_dir()


def read_pattern(base_path: str, declaration: FileDeclaration) -> str:
    """The path the reader is pointed at.

    Raises ``ValueError`` when the URI carries a query string on object storage or lands outside the
    base location, since the result goes into SQL text.
    """
    if has_url_query(base_path, declaration.uri):
        raise ValueError(URI_HAS_QUERY)
    if (location := _locate(base_path, declaration.uri)) is None:
        raise ValueError(PATH_OUTSIDE_BASE_PATH)
    return location


def file_count_query(base_path: str, declaration: FileDeclaration) -> str:
    """A query returning the declaration's ``table_name`` and ``file_ct``.

    Counts the files matched by ``read_pattern``, the same glob the view reads.
    """
    return (
        f"SELECT {sql_literal(declaration.name)} AS table_name, COUNT(*) AS file_ct"
        f" FROM glob({sql_literal(read_pattern(base_path, declaration))})"
    )


def create_view_statement(base_path: str, declaration: FileDeclaration, schema: str) -> str:
    """The ``CREATE VIEW`` that makes one declaration queryable.

    Raises ``ValueError`` when the declaration name is not a bare SQL identifier.
    """
    # The name becomes an identifier in DDL, and a declaration list can arrive from anywhere a
    # table group is saved. A driver that accepts several statements in one call would turn a
    # quote here into arbitrary SQL, so an unusable name stops before it reaches the text.
    if not NAME_PATTERN.match(declaration.name):
        raise ValueError(NAME_INVALID)

    arguments = [sql_literal(read_pattern(base_path, declaration))]
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
    view = f"{sql_identifier(schema)}.{sql_identifier(declaration.name)}"
    # Not OR REPLACE: a name that folds onto an existing view must fail rather than replace it.
    return f'CREATE VIEW {view} AS SELECT * FROM {reader}({", ".join(arguments)})'


def _sql_value(value: Any, kind: type) -> str:
    if kind is bool:
        return "true" if value in (True, "true", "True", 1) else "false"
    return sql_literal(str(value))
