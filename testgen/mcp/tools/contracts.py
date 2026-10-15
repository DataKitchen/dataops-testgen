"""MCP read tools for data contracts — exporting a contract version as an ODCS document."""

import hashlib
from typing import Annotated

from pydantic import Field

from testgen import settings
from testgen.common import contract_service
from testgen.common.contract_service import InvalidContractDocumentError
from testgen.common.enums import JOB_STATUS_LABEL
from testgen.common.models import with_database_session
from testgen.common.models.suite_version import SuiteVersion, VersionState, version_state
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import mcp_permission
from testgen.mcp.services.source_data_protection import mcp_source_data_only
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

    pieces = split_document(exported.text, settings.MCP_CONTRACT_EXPORT_CHUNK_BYTES)
    if not 1 <= chunk <= len(pieces):
        raise MCPUserError(f"This document has {len(pieces)} chunks, so there is no chunk {chunk}.")

    doc = MdDoc()
    doc.heading(1, f"Contract `{suite.test_suite}`")
    doc.field("Version", format_version(target.version, state))
    if len(pieces) > 1:
        size = len(exported.text.encode()) // 1024
        doc.field("Document", f"{size} KB in {len(pieces)} chunks, of which this is chunk {chunk} of {len(pieces)}")
        doc.field("SHA-256", hashlib.sha256(exported.text.encode()).hexdigest())
    if chunk == 1 and exported.problems:
        doc.text("This document does not validate against the ODCS schema:")
        doc.bullets(exported.problems)
    if chunk < len(pieces):
        doc.text(f"Call `export_contract` again with `chunk={chunk + 1}`, appending each piece in order.")
    doc.code_block(pieces[chunk - 1], language="yaml")

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
