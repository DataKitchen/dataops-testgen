"""The file declaration as a request or response field, and its translation to and from storage.

A file declaration is stored in ``table_groups.file_declarations`` with its CSV settings gathered
under ``options``. Callers see those settings as separate fields, each described as applying to
CSV only.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, Field, model_validator

from testgen.common.database.file_declarations import parse_file_declarations
from testgen.common.enums import FileFormat

CSV_SETTINGS = ("delimiter", "header", "quote", "escape")

HEADER_DESCRIPTION = "CSV only. Whether the first row holds column names. Autodetected when omitted."

_Quote = Annotated[
    str | None,
    Field(
        description="CSV only. Character wrapping a field that contains the delimiter or a line break, e.g. "
        '``"``. Autodetected when omitted.',
    ),
]
_Escape = Annotated[
    str | None,
    Field(
        description="CSV only. Character that escapes a quote inside a quoted field, e.g. ``\\`` or a second "
        '``"``. Autodetected when omitted.',
    ),
]


class FileDeclarationShape(BaseModel):
    """One table on a file connection, named by the path its rows come from.

    The fields alone, with no rule on their values, so a stored declaration is shown as it is.
    """

    name: Annotated[
        str,
        Field(
            description="Name for this table in TestGen. Must start with a letter or underscore and contain only "
            "letters, numbers and underscores. Unique within the table group.",
        ),
    ]
    uri: Annotated[
        str,
        Field(
            description="Path to the data, relative to the connection's base path, base URI or container. Name one "
            "file (``sales/orders.csv``) or a glob pattern (``sales/*.csv``, or ``sales/**/*.csv`` to include "
            "subfolders). A pattern is one table whose rows span every file it matches. A bare folder is rejected.",
        ),
    ]
    format: Annotated[FileFormat, Field(description="Format TestGen reads the files as.")]
    delimiter: Annotated[
        str | None,
        Field(description="CSV only. Character between fields, e.g. ``,`` or ``|``. Autodetected when omitted."),
    ] = None
    header: Annotated[bool | None, Field(description=HEADER_DESCRIPTION)] = None
    quote: _Quote = None
    escape: _Escape = None


class FileDeclarationSpec(FileDeclarationShape):
    """One table to declare on a file connection, named by the path its rows come from."""

    quote: Annotated[_Quote, Field(max_length=1)] = None
    escape: Annotated[_Escape, Field(max_length=1)] = None

    @model_validator(mode="after")
    def _reject_settings_for_another_format(self) -> FileDeclarationSpec:
        if self.format is FileFormat.CSV:
            return self
        supplied = [name for name in CSV_SETTINGS if getattr(self, name) is not None]
        if supplied:
            raise ValueError(
                f"{', '.join(supplied)} applies to a CSV file. "
                f"Table {self.name!r} is declared as {self.format}."
            )
        return self

    def to_payload(self) -> dict[str, Any]:
        """The stored JSONB entry, with the CSV settings that are set gathered into ``options``."""
        options = {name: value for name in CSV_SETTINGS if (value := getattr(self, name)) is not None}
        return {
            "name": self.name,
            "uri": self.uri,
            "format": str(self.format),
            "options": options if self.format is FileFormat.CSV else {},
        }


_Shape = TypeVar("_Shape", bound=FileDeclarationShape)


def declarations_from_payload(
    raw: list[dict[str, Any]] | None,
    model: type[_Shape] = FileDeclarationShape,  # type: ignore[assignment]
) -> list[_Shape]:
    """The stored declarations as ``model`` instances, skipping any whose format TestGen cannot read.

    Built without validation, so a stored value is shown as it is, even one a write path would
    refuse.
    """
    declarations = []
    for declaration in parse_file_declarations(raw):
        settings = declaration.options if declaration.format is FileFormat.CSV else {}
        declarations.append(
            model.model_construct(
                name=declaration.name,
                uri=declaration.uri,
                format=declaration.format,
                **{name: settings.get(name) for name in CSV_SETTINGS},
            )
        )
    return declarations
