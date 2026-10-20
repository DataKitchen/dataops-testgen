"""Validates a contract document against the bundled, pinned ODCS JSON schema."""

import functools
import json
from dataclasses import dataclass
from importlib import resources

from jsonschema import Draft201909Validator, ValidationError

from testgen.common.odcs.servers import ODCS_API_VERSION

# Every ODCS release from v3.1.0 on. Each file is the schema as published at its release tag.
_SCHEMA_FILES: dict[str, str] = {
    "v3.1.0": "odcs-json-schema-v3.1.0.json",
    ODCS_API_VERSION: "odcs-json-schema-v3.2.0.json",
}


class UnknownApiVersionError(ValueError):
    """Raised when no bundled schema exists for a requested ODCS API version."""


@dataclass(frozen=True)
class SchemaViolation:
    """One violation the schema validator reports.

    ``path`` is the JSON path of the offending value, ``schema_path`` the schema keyword it
    failed, and ``message`` the validator's own wording, which may quote the offending value.
    ``unexpected_keys`` names the keys an object may not have, for a violation of
    ``additionalProperties`` or ``unevaluatedProperties``.
    """

    path: str
    schema_path: str
    message: str
    unexpected_keys: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@functools.lru_cache
def _validator_for(api_version: str) -> Draft201909Validator:
    try:
        filename = _SCHEMA_FILES[api_version]
    except KeyError:
        raise UnknownApiVersionError(f"No bundled schema for ODCS API version {api_version!r}.") from None
    schema = json.loads(resources.files("testgen.common.odcs.schemas").joinpath(filename).read_text())
    return Draft201909Validator(schema, format_checker=Draft201909Validator.FORMAT_CHECKER)


def validate_document(document: dict) -> list[str]:
    """The violations ``schema_violations`` finds in ``document``, each as ``f"{json_path}: {message}"``.
    An empty list means the document is valid."""
    return [str(violation) for violation in schema_violations(document)]


def schema_violations(document: dict) -> list[SchemaViolation]:
    """Validate a document against the bundled schema for the version it declares.

    The version comes from the document's own ``apiVersion``, falling back to the pinned
    ``ODCS_API_VERSION`` when it declares none -- never from a value supplied alongside it,
    which is how a document comes to be checked against a version it does not claim.

    Returns every violation the schema validator reports, in the validator's own wording,
    sorted by JSON path. A version with no bundled schema is itself reported as a violation at
    ``$.apiVersion``: the standard allows versions older than the ones bundled here, and a
    document declaring one is legal ODCS that cannot be checked, which a caller handles the same
    way as any other violation.
    """
    api_version = document.get("apiVersion") or ODCS_API_VERSION
    try:
        validator = _validator_for(api_version)
    except UnknownApiVersionError as exc:
        return [SchemaViolation("$.apiVersion", "", str(exc))]
    errors = sorted(validator.iter_errors(document), key=lambda error: error.json_path)
    return [
        SchemaViolation(
            error.json_path, "/".join(str(step) for step in error.schema_path), error.message, _unexpected_keys(error)
        )
        for error in errors
    ]


_UNEXPECTED_KEY_VALIDATORS = frozenset({"additionalProperties", "unevaluatedProperties"})


def _unexpected_keys(error: ValidationError) -> tuple[str, ...]:
    if error.validator not in _UNEXPECTED_KEY_VALIDATORS or not isinstance(error.instance, dict):
        return ()
    # The message lists each unexpected key as its repr; the error carries no other record of them.
    return tuple(sorted(key for key in error.instance if repr(key) in error.message))
