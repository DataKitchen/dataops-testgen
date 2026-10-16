"""MCP tools for data contracts — exporting a version, reading its metadata document, and listing, freezing and
discarding versions."""

import hashlib
from dataclasses import dataclass
from typing import Annotated

import yaml
from pydantic import Field

from testgen import settings
from testgen.common import contract_service
from testgen.common.contract_document import PROFILED_VALUES
from testgen.common.contract_service import InvalidContractDocumentError
from testgen.common.enums import JOB_STATUS_LABEL
from testgen.common.models import with_database_session
from testgen.common.models.suite_version import SuiteVersion, VersionState, version_state
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import mcp_permission
from testgen.mcp.services.source_data_protection import mcp_source_data_only, mcp_source_data_protected
from testgen.mcp.tools.common import (
    DocGroup,
    format_page_footer,
    format_page_info,
    format_version,
    resolve_contract,
    validate_limit,
    validate_page,
)
from testgen.mcp.tools.markdown import MdDoc, format_datetime

_DOC_GROUP = DocGroup.CONTRACTS


def split_document(text: str, limit: int) -> list[str]:
    """``text`` in pieces of at most ``limit`` bytes, split only between lines.

    Concatenating the pieces reproduces ``text`` exactly. A single line longer than ``limit``
    is returned whole as its own piece rather than cut, since a cut inside a line can land
    inside a multi-byte character and no reassembly on the caller's side repairs that.
    """
    if len(text.encode()) <= limit:
        return [text]

    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        line_size = len(line.encode())
        if current and size + line_size > limit:
            pieces.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += line_size
    if current:
        pieces.append("".join(current))
    return pieces


@dataclass
class _DocumentChunk:
    """A YAML document split into chunks of bounded size, and the chunk one response returns."""

    text: str
    pieces: list[str]
    number: int

    @classmethod
    def select(cls, text: str, number: int) -> "_DocumentChunk":
        """Split ``text`` into chunks and select chunk ``number``, counted from 1.

        Raises ``MCPUserError`` when the document has no such chunk.
        """
        pieces = split_document(text, settings.MCP_CONTRACT_EXPORT_CHUNK_BYTES)
        if not 1 <= number <= len(pieces):
            raise MCPUserError(f"This document has {len(pieces)} chunks, so there is no chunk {number}.")
        return cls(text, pieces, number)

    def add_fields(self, doc: MdDoc) -> None:
        """Add the document's size, chunk count and SHA-256 to ``doc`` when it has more than one chunk."""
        if len(self.pieces) > 1:
            size = len(self.text.encode()) // 1024
            doc.field(
                "Document",
                f"{size} KB in {len(self.pieces)} chunks, of which this is chunk {self.number} of {len(self.pieces)}",
            )
            doc.field("SHA-256", hashlib.sha256(self.text.encode()).hexdigest())

    def add_body(self, doc: MdDoc, tool_name: str) -> None:
        """Add the chunk to ``doc`` as a YAML block, preceded by how to fetch the next one when there is one."""
        if self.number < len(self.pieces):
            doc.text(f"Call `{tool_name}` again with `chunk={self.number + 1}`, appending each piece in order.")
        doc.code_block(self.pieces[self.number - 1], language="yaml")


# Document fields that can carry values from the source data: a column's value bounds, profiled
# value bounds, examples and allowed values, and a quality rule's thresholds, arguments, query and
# implementation. A value a person typed cannot be told apart from one taken from the data, so
# under source-data protection they are dropped uniformly.
_SOURCE_VALUE_TYPE_OPTIONS = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"})
_SOURCE_VALUE_RULE_FIELDS = frozenset({
    "mustBe",
    "mustNotBe",
    "mustBeGreaterThan",
    "mustBeGreaterOrEqualTo",
    "mustBeLessThan",
    "mustBeLessOrEqualTo",
    "mustBeBetween",
    "mustNotBeBetween",
    "arguments",
    "query",
    "implementation",
})
_SOURCE_VALUE_PROPERTY_FIELDS = frozenset({"examples", "enum"})
_OMITTED_FIELDS = (
    "`logicalTypeOptions` " + ", ".join(f"`{key}`" for key in sorted(_SOURCE_VALUE_TYPE_OPTIONS)),
    f"`{PROFILED_VALUES}` `maximum`, `minimum`",
    ", ".join(f"`{key}`" for key in sorted(_SOURCE_VALUE_PROPERTY_FIELDS)),
    "quality rule " + ", ".join(f"`{key}`" for key in sorted(_SOURCE_VALUE_RULE_FIELDS)),
)


def _without_bounds(options: dict) -> dict:
    return {option: value for option, value in options.items() if option not in _SOURCE_VALUE_TYPE_OPTIONS}


def _without_profiled_bounds(entries: list) -> list:
    """``entries`` with the value bounds dropped from a ``profiledValues`` entry, and the entry
    dropped when nothing else is left in it."""
    kept = []
    for entry in entries:
        if (
            isinstance(entry, dict) and entry.get("property") == PROFILED_VALUES
            and isinstance(entry.get("value"), dict)
        ):
            if not (values := _without_bounds(entry["value"])):
                continue
            entry = {**entry, "value": values}
        kept.append(entry)
    return kept


def _without_source_values(node: object) -> object:
    """A copy of a metadata document node without the fields that can carry source-data values:
    ``examples``, ``enum``, the value bounds of ``logicalTypeOptions`` and ``profiledValues``, and
    quality-rule thresholds, arguments, queries and implementations."""
    if isinstance(node, list):
        return [_without_source_values(item) for item in node]
    if not isinstance(node, dict):
        return node
    kept = {}
    for key, value in node.items():
        if key in _SOURCE_VALUE_PROPERTY_FIELDS:
            continue
        if key == "logicalTypeOptions" and isinstance(value, dict):
            value = _without_bounds(value)
            if not value:
                continue
        elif key == "customProperties" and isinstance(value, list):
            value = _without_profiled_bounds(value)
            if not value:
                continue
        elif key == "quality" and isinstance(value, list):
            value = [
                {field: v for field, v in rule.items() if field not in _SOURCE_VALUE_RULE_FIELDS}
                if isinstance(rule, dict) else rule
                for rule in value
            ]
        kept[key] = _without_source_values(value)
    return kept


@mcp_source_data_only
@with_database_session
@mcp_permission("view")
def export_contract(
    test_suite_id: Annotated[
        str, Field(description="UUID of the contract to export.")
    ],
    version: Annotated[
        int | None,
        Field(
            description="Version number to export. Defaults to the draft where one exists, otherwise the "
            "version in force.",
        ),
    ] = None,
    chunk: Annotated[
        int,
        Field(
            description="Which piece of a document too large for one response to return. The first "
            "response reports how many there are.",
        ),
    ] = 1,
) -> str:
    """Export one version of a contract as a complete ODCS document.

    The document comes back whole, never narrowed to a section, table or column. Past a size
    threshold it arrives in chunks: the first names how many there are, and appending them in
    order reproduces the document exactly, ready to write to a YAML file. Every chunk carries the
    whole document's SHA-256; a chunk whose digest differs from the first means the draft changed
    in between, so start again from chunk 1. Size follows the contract -- around 110 KB for one
    declaring 5 tables of 20 columns, 1.3 MB for 40 tables.

    A frozen version returns the bytes stored when it was frozen. A draft is rendered fresh,
    and any way in which it would fail the check that freezing applies is reported above it.
    """
    suite = resolve_contract(test_suite_id)
    try:
        target = contract_service.version_for_export(suite, version)
        exported = contract_service.export_version(target)
    except ValueError as e:
        # Covers the renderer's own refusals too -- an orphaned term, an unmapped flavor, a
        # test type excluded from contracts -- each of which names what to fix.
        raise MCPUserError(str(e)) from e

    state = version_state(target.frozen_at, SuiteVersion.is_active(target.id, suite.id))

    selected = _DocumentChunk.select(exported.text, chunk)

    doc = MdDoc()
    doc.heading(1, f"Contract `{suite.test_suite}`")
    doc.field("Version", format_version(target.version, state))
    selected.add_fields(doc)
    if chunk == 1 and exported.problems:
        doc.text("This document does not validate against the ODCS schema:")
        doc.bullets(exported.problems)
    selected.add_body(doc, "export_contract")

    return doc.render()


@with_database_session
@mcp_permission("view")
def get_contract_metadata(
    test_suite_id: Annotated[
        str, Field(description="UUID of the contract to read.")
    ],
    version: Annotated[
        int | None,
        Field(
            description="Version number to read. Defaults to the draft where one exists, otherwise the "
            "version in force.",
        ),
    ] = None,
    chunk: Annotated[
        int,
        Field(
            description="Which piece of a document too large for one response to return. The first "
            "response reports how many there are.",
        ),
    ] = 1,
) -> str:
    """Read one version of a contract's metadata document.

    Returns the contract's descriptive half as ODCS YAML: its tables and columns with their types
    and descriptions, governance attributes and servers. The contract's terms -- its tests -- are
    not included; ``list_tests`` returns them, and, where source data is not protected,
    ``export_contract`` returns the full document with them. A large document arrives in chunks: the first response says how many there are, and
    appending them in order reproduces the document. Every chunk carries the whole document's
    SHA-256; a chunk whose digest differs from the first means the document changed in between, so
    start again from chunk 1.

    Under source-data protection, fields that can hold values from the data, such as observed
    minimums and maximums, are left out, and the response lists them.
    """
    suite = resolve_contract(test_suite_id)
    try:
        target = contract_service.version_for_export(suite, version)
    except ValueError as e:
        raise MCPUserError(str(e)) from e

    hide_source_data = mcp_source_data_protected()
    document = target.metadata_document or {}
    if hide_source_data:
        document = _without_source_values(document)
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    selected = _DocumentChunk.select(text, chunk)

    doc = MdDoc()
    doc.heading(1, f"Contract `{suite.test_suite}` metadata")
    doc.field(
        "Version",
        format_version(target.version, version_state(target.frozen_at, SuiteVersion.is_active(target.id, suite.id))),
    )
    selected.add_fields(doc)
    if hide_source_data:
        doc.field("Omitted Fields", "; ".join(_OMITTED_FIELDS))
    if chunk == 1:
        doc.text(
            "The contract's terms are not included; `list_tests` returns them."
            if hide_source_data
            else "The contract's terms are not included; `list_tests` returns them, and `export_contract` "
            "returns the full document with them."
        )
    selected.add_body(doc, "get_contract_metadata")

    return doc.render()


@with_database_session
@mcp_permission("view")
def list_contract_versions(
    test_suite_id: Annotated[str, Field(description="UUID of the contract, e.g. from `list_test_suites`.")],
    limit: Annotated[int, Field(description="Maximum number of versions per page (default 20, max 100).")] = 20,
    page: Annotated[int, Field(description="Page number, starting from 1 (default 1).")] = 1,
) -> str:
    """List a contract's versions, newest first.

    Each version shows its state, label, author, freeze time, how many tests it holds, how many
    times it has run and its latest run. Use `list_test_runs` with `version` for a version's
    full run history.
    """
    validate_page(page)
    validate_limit(limit, 100)
    suite = resolve_contract(test_suite_id)
    items, total = SuiteVersion.list_for_suite(suite.id, page=page, limit=limit)
    in_force = SuiteVersion.in_force_for(suite.id)
    active_number = in_force.version if in_force else None

    doc = MdDoc()
    doc.heading(1, f"Versions of contract `{suite.test_suite}`")
    doc.text(format_page_info(total, page, limit))
    rows = []
    for item in items:
        state = version_state(item.frozen_at, item.version == active_number)
        latest = None
        if item.latest_run_id:
            status = JOB_STATUS_LABEL.get(item.latest_run_status, item.latest_run_status)
            started = format_datetime(item.latest_run_started_at)
            latest = f"`{item.latest_run_id}` {status} {started}" if started else f"`{item.latest_run_id}` {status}"
        rows.append([
            format_version(item.version, state), item.label, item.created_by, item.frozen_at,
            item.term_count, item.run_count, latest,
        ])
    doc.table(["Version", "Label", "Author", "Frozen", "Tests", "Runs", "Latest Run"], rows)
    if footer := format_page_footer(total, page, limit):
        doc.text(footer)
    return doc.render()


@with_database_session
@mcp_permission("edit")
def freeze_contract_version(
    test_suite_id: Annotated[str, Field(description="UUID of the contract, e.g. from `list_test_suites`.")],
    label: Annotated[str | None, Field(description="Optional name for the version being frozen.")] = None,
) -> str:
    """Freeze a contract's draft, making it the version in force.

    A frozen version cannot be changed or unfrozen. Later edits open a new draft.
    """
    suite = resolve_contract(test_suite_id)
    previous = SuiteVersion.in_force_for(suite.id)
    if SuiteVersion.draft_for(suite.id) is None:
        detail = (
            f" {format_version(previous.version, VersionState.ACTIVE)} is already frozen; "
            "edit a test to open a new draft."
            if previous else ""
        )
        raise MCPUserError(f"Contract `{suite.test_suite}` has no draft to freeze.{detail}")
    try:
        frozen = contract_service.freeze_version(suite, label=label)
    except InvalidContractDocumentError as e:
        raise MCPUserError(
            "The draft cannot be frozen because its document does not validate:\n"
            + "\n".join(f"- {problem}" for problem in e.problems)
        ) from e
    except ValueError as e:
        raise MCPUserError(str(e)) from e

    doc = MdDoc()
    doc.heading(1, f"Froze v{frozen.version} of contract `{suite.test_suite}`")
    doc.field("Version", format_version(frozen.version, VersionState.ACTIVE))
    if frozen.label:
        doc.field("Label", frozen.label)
    if previous:
        doc.field("Previous version", format_version(previous.version, VersionState.SUPERSEDED))
    doc.text(
        f"Runs of this contract now run v{frozen.version} by default. A frozen version cannot be "
        "changed or unfrozen; edits open a new draft."
    )
    return doc.render()


@with_database_session
@mcp_permission("edit")
def discard_contract_draft(
    test_suite_id: Annotated[str, Field(description="UUID of the contract, e.g. from `list_test_suites`.")],
) -> str:
    """Discard a contract's draft and the tests on it.

    The contract returns to its version in force.
    """
    suite = resolve_contract(test_suite_id)
    draft = SuiteVersion.draft_for(suite.id)
    try:
        removed = contract_service.discard_draft(suite)
    except ValueError as e:
        raise MCPUserError(str(e)) from e
    now_at = SuiteVersion.in_force_for(suite.id)

    doc = MdDoc()
    doc.heading(1, f"Discarded {format_version(draft.version, VersionState.DRAFT)} of contract `{suite.test_suite}`")
    doc.field("Tests removed", removed)
    doc.field("Contract is now at", format_version(now_at.version, VersionState.ACTIVE))
    return doc.render()
