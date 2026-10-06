"""Validates a contract document against the bundled, pinned ODCS JSON schema."""

import functools
import json
from importlib import resources

from jsonschema import Draft201909Validator

from testgen.common.odcs.servers import ODCS_API_VERSION

_SCHEMA_FILES: dict[str, str] = {
    ODCS_API_VERSION: "odcs-json-schema-v3.2.0.json",
}


class UnknownApiVersionError(ValueError):
    """Raised when no bundled schema exists for a requested ODCS API version."""


@functools.lru_cache
def _validator_for(api_version: str) -> Draft201909Validator:
    try:
        filename = _SCHEMA_FILES[api_version]
    except KeyError:
        raise UnknownApiVersionError(f"No bundled schema for ODCS API version {api_version!r}.") from None
    schema = json.loads(resources.files("testgen.common.odcs.schemas").joinpath(filename).read_text())
    return Draft201909Validator(schema, format_checker=Draft201909Validator.FORMAT_CHECKER)


def validate_document(document: dict, api_version: str | None = None) -> list[str]:
    """Validate a document against the pinned ODCS schema for ``api_version``.

    ``api_version`` defaults to the pinned ``ODCS_API_VERSION`` when ``None``. Returns every
    violation the schema validator reports, as ``f"{json_path}: {message}"`` in the
    validator's own wording, sorted by JSON path. An empty list means the document is valid.
    Raises ``UnknownApiVersionError`` when no bundled schema matches ``api_version``.
    """
    validator = _validator_for(api_version or ODCS_API_VERSION)
    errors = sorted(validator.iter_errors(document), key=lambda error: error.json_path)
    return [f"{error.json_path}: {error.message}" for error in errors]
