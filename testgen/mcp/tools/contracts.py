"""MCP read tools for data contracts — exporting a contract version as an ODCS document."""

import hashlib
from typing import Annotated

from pydantic import Field

from testgen import settings
from testgen.common import contract_service
from testgen.common.models import with_database_session
from testgen.common.models.suite_version import SuiteVersion
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import mcp_permission
from testgen.mcp.services.source_data_protection import mcp_source_data_only
from testgen.mcp.tools.common import DocGroup, resolve_contract
from testgen.mcp.tools.markdown import MdDoc

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

    if target.frozen_at is None:
        state = "draft"
    elif SuiteVersion.is_active(target.id, suite.id):
        state = "active"
    else:
        state = "superseded"

    pieces = split_document(exported.text, settings.MCP_CONTRACT_EXPORT_CHUNK_BYTES)
    if not 1 <= chunk <= len(pieces):
        raise MCPUserError(f"This document has {len(pieces)} chunks, so there is no chunk {chunk}.")

    doc = MdDoc()
    doc.heading(1, f"Contract `{suite.test_suite}`")
    doc.field("Version", f"v{target.version} {state}")
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
