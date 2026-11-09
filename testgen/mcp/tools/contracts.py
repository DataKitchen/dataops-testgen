"""MCP tools for data contracts — exporting a version, reading its metadata document, listing, freezing and
discarding versions, and importing an ODCS document."""

import copy
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

import yaml
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from testgen import settings
from testgen.common import contract_comparison, contract_creation, contract_import, contract_service
from testgen.common.audit.test_suites import record_contract_created
from testgen.common.auth import get_jwt_signing_key
from testgen.common.contract_comparison import TermChangeKind
from testgen.common.contract_document import PROFILED_VALUES
from testgen.common.contract_import import (
    ContractIdentityError,
    ContractImportMode,
    ContractImportPlan,
    ContractTermReason,
)
from testgen.common.contract_service import CheckableRuleError, InvalidContractDocumentError, OwnedFieldError
from testgen.common.database.test_suite_service import (
    duplicate_name_message,
    is_duplicate_name_error,
    validate_test_suite_fields,
)
from testgen.common.enums import JOB_STATUS_LABEL, SuiteType
from testgen.common.flavors import SqlFlavorCode
from testgen.common.merge_patch import apply_merge_patch
from testgen.common.models import get_current_session, with_database_session
from testgen.common.models.connection import Connection
from testgen.common.models.suite_version import SuiteVersion, VersionState, format_version, version_state
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.quality_rules import CONVERSION_PROPERTIES
from testgen.common.source_value_fields import (
    CALIBRATION_SHAPED_PARAM_COLUMNS,
    SOURCE_VALUE_PROPERTY_FIELDS,
    SOURCE_VALUE_RULE_FIELDS,
    SOURCE_VALUE_TYPE_OPTIONS,
    hidden_slots,
    value_digest,
)
from testgen.common.test_definition_export_import_service import ImportAction
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import get_mcp_username, get_project_permissions, mcp_permission
from testgen.mcp.services.source_data_protection import mcp_source_data_only, mcp_source_data_protected
from testgen.mcp.tools.common import (
    DocGroup,
    format_page_footer,
    format_page_info,
    parse_enum,
    raise_validation_error,
    render_diff_table,
    resolve_contract,
    resolve_contract_version,
    resolve_table_group,
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


_HIDDEN_FIELDS = (
    "`logicalTypeOptions` " + ", ".join(f"`{key}`" for key in sorted(SOURCE_VALUE_TYPE_OPTIONS)),
    f"`{PROFILED_VALUES}` " + ", ".join(f"`{key}`" for key in sorted(SOURCE_VALUE_TYPE_OPTIONS)),
    ", ".join(f"`{key}`" for key in sorted(SOURCE_VALUE_PROPERTY_FIELDS)),
    "quality rule " + ", ".join(f"`{key}`" for key in sorted(SOURCE_VALUE_RULE_FIELDS)),
    "quality rule `testgen` " + ", ".join(f"`{key}`" for key in sorted(CONVERSION_PROPERTIES)),
)
_PLACEHOLDER = re.compile(r"<hidden:([0-9a-f]{16})\.([0-9a-f]{16})>")
_NOT_FOUND = object()


def _placeholder_key() -> bytes:
    return hmac.new(get_jwt_signing_key(), b"contract-hidden-values", hashlib.sha256).digest()


def _placeholder(key: bytes, value: Any) -> str:
    """A placeholder that stands for ``value`` in reads under source-data protection.

    A random salt and a keyed digest of the salt with the value. Placeholders for equal values
    differ, and without the server's key a placeholder can neither be traced back to its value
    nor compared with another one.
    """
    salt = secrets.token_hex(8)
    return f"<hidden:{salt}.{value_digest(key, salt, value)}>"


def _with_placeholders(node: Any) -> Any:
    """A copy of a metadata document node with each value that can carry source data replaced by a placeholder."""
    key = _placeholder_key()
    masked = copy.deepcopy(node)
    for slot in list(hidden_slots(masked)):
        slot.container[slot.key] = _placeholder(key, slot.container[slot.key])
    return masked


def _resolve_placeholders(document: Any, stored: Any) -> Any:
    """A copy of ``document`` with each placeholder replaced by the stored value it stands for.

    A placeholder resolves only as the whole value of a field that can carry source data, so a
    hidden value can never be moved where reads would show it.

    Raises ``MCPUserError`` for a placeholder anywhere else, or one that stands for no value
    ``stored`` holds.
    """
    key: bytes | None = None
    stored_values = [slot.container[slot.key] for slot in hidden_slots(stored)]
    resolved = copy.deepcopy(document)
    stale = []
    for slot in list(hidden_slots(resolved)):
        value = slot.container[slot.key]
        if isinstance(value, str) and (match := _PLACEHOLDER.fullmatch(value)):
            salt, digest = match.groups()
            key = key or _placeholder_key()
            found = next(
                (stored for stored in stored_values if hmac.compare_digest(value_digest(key, salt, stored), digest)),
                _NOT_FOUND,
            )
            if found is _NOT_FOUND:
                stale.append(slot.path)
                slot.container[slot.key] = None
            else:
                slot.container[slot.key] = copy.deepcopy(found)
    if misplaced := _placeholder_paths(_blank_placeholder_slots(document), "$"):
        raise MCPUserError(
            "No changes saved. A `<hidden:…>` placeholder can only be the whole value of a field that reads "
            f"hide. Found at: {', '.join(f'`{path}`' for path in misplaced)}."
        )
    if stale:
        raise MCPUserError(
            "No changes saved. These placeholders stand for values the contract no longer holds, so the document "
            f"changed after it was read: {', '.join(f'`{path}`' for path in stale)}. Read it again with "
            "`get_contract_metadata`."
        )
    return resolved


def _blank_placeholder_slots(document: Any) -> Any:
    blanked = copy.deepcopy(document)
    for slot in list(hidden_slots(blanked)):
        if isinstance(slot.container[slot.key], str) and _PLACEHOLDER.fullmatch(slot.container[slot.key]):
            slot.container[slot.key] = None
    return blanked


def _placeholder_paths(node: Any, path: str) -> list[str]:
    if isinstance(node, str):
        return [path] if _PLACEHOLDER.search(node) else []
    if isinstance(node, list):
        return [found for index, item in enumerate(node) for found in _placeholder_paths(item, f"{path}[{index}]")]
    if isinstance(node, dict):
        return [
            found
            for key, value in node.items()
            for found in (
                ([f"{path}.{key}"] if _PLACEHOLDER.search(str(key)) else [])
                + _placeholder_paths(value, f"{path}.{key}")
            )
        ]
    return []


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
        exported = contract_service.export_file(target, contract_name=suite.test_suite)
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


def _narrow(
    document: dict[str, Any], section: str | None, table_name: str | None, column_name: str | None
) -> dict[str, Any]:
    """The part of ``document`` a read asked for.

    A table or column keeps the ``schema`` entries around it, so the result reads as a document
    fragment rather than a bare value.
    """
    if column_name and not table_name:
        raise MCPUserError("`column_name` requires `table_name`.")
    if table_name:
        if section not in (None, "schema"):
            raise MCPUserError(f"Tables are in the `schema` section, not `{section}`. Omit `section` or pass `schema`.")
        section = "schema"
    if section is None:
        return document
    if section not in document:
        present = ", ".join(f"`{key}`" for key in document) or "none"
        raise MCPUserError(f"This document has no `{section}` section. Its sections are {present}.")
    if not table_name:
        return {section: document[section]}

    tables = [table for table in document.get("schema") or [] if isinstance(table, dict)]
    table = next((table for table in tables if table_name in (table.get("name"), table.get("physicalName"))), None)
    if table is None:
        names = ", ".join(_declared_name(table) for table in tables) or "none"
        raise MCPUserError(f"The document declares no table `{table_name}`. Its tables are {names}.")
    if not column_name:
        return {"schema": [table]}

    properties = [prop for prop in table.get("properties") or [] if isinstance(prop, dict)]
    prop = next((prop for prop in properties if column_name in (prop.get("name"), prop.get("physicalName"))), None)
    if prop is None:
        names = ", ".join(_declared_name(prop) for prop in properties) or "none"
        raise MCPUserError(f"Table `{table_name}` declares no column `{column_name}`. Its columns are {names}.")
    return {"schema": [{**{key: table[key] for key in ("name", "physicalName") if key in table}, "properties": [prop]}]}


def _declared_name(entry: dict[str, Any]) -> str:
    name, physical = entry.get("name"), entry.get("physicalName")
    return f"`{name}` (`{physical}`)" if physical and physical != name else f"`{name}`"


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
    section: Annotated[
        str | None,
        Field(description="Top-level key of the document to return, e.g. `schema`, `team`, or `support`."),
    ] = None,
    table_name: Annotated[
        str | None,
        Field(
            description="Table to return from the `schema` section, by its `name` or its `physicalName`. Implies "
            "`section='schema'`.",
        ),
    ] = None,
    column_name: Annotated[
        str | None,
        Field(description="Column of `table_name` to return, by its `name` or its `physicalName`. Requires `table_name`."),
    ] = None,
    chunk: Annotated[
        int,
        Field(
            description="Which piece of a document too large for one response to return. The first "
            "response reports how many there are.",
        ),
    ] = 1,
) -> str:
    """Read a contract's metadata document, whole or one section, table, or column.

    Returns the document as ODCS YAML: tables and columns with their types and descriptions,
    catalog metadata such as tags and classification, team, support, and servers. The contract's tests are not in it:
    ``list_tests`` returns them, and, where source data is not protected, ``export_contract``
    returns the full document with them. Change this document with ``update_contract_metadata``.

    A large document arrives in chunks; append them in order. Every chunk carries the whole
    document's SHA-256, and a different digest means the document changed: start again from chunk 1.

    Under source-data protection, each value that can come from the data shows as a placeholder.
    """
    suite = resolve_contract(test_suite_id)
    try:
        target = contract_service.version_for_export(suite, version)
    except ValueError as e:
        raise MCPUserError(str(e)) from e

    hide_source_data = mcp_source_data_protected()
    document = _narrow(
        contract_service.document_with_contract_name(target, suite), section, table_name, column_name
    )
    if hide_source_data:
        document = _with_placeholders(document)
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    selected = _DocumentChunk.select(text, chunk)

    doc = MdDoc()
    doc.heading(1, f"Contract `{suite.test_suite}` metadata")
    doc.field(
        "Version",
        format_version(target.version, version_state(target.frozen_at, SuiteVersion.is_active(target.id, suite.id))),
    )
    filters = [
        f"{label} `{value}`"
        for label, value in (("section", section), ("table", table_name), ("column", column_name))
        if value
    ]
    if filters:
        doc.field("Filters", ", ".join(filters))
    selected.add_fields(doc)
    if hide_source_data:
        doc.field("Hidden Fields", "; ".join(_HIDDEN_FIELDS))
        doc.text(
            "Each hidden value shows as a `<hidden:…>` placeholder. To keep a value when changing the document "
            "with `update_contract_metadata`, send its placeholder back as the whole value of a hidden field; "
            "leave it out to remove the value."
        )
    if chunk == 1:
        doc.text(
            "The contract's terms are not included; `list_tests` returns them."
            if hide_source_data
            else "The contract's terms are not included; `list_tests` returns them, and `export_contract` "
            "returns the full document with them."
        )
    selected.add_body(doc, "get_contract_metadata")

    return doc.render()


class MetadataUpdateMode(StrEnum):
    MERGE = "merge"
    REPLACE = "replace"


@with_database_session
@mcp_permission("edit")
def update_contract_metadata(
    test_suite_id: Annotated[str, Field(description="UUID of the contract, e.g. from `list_test_suites`.")],
    patch: Annotated[
        dict[str, Any],
        Field(description="A JSON merge patch against the document, or with `mode='replace'` the whole document."),
    ],
    mode: Annotated[
        str,
        Field(description="`merge` (default) applies `patch` as a JSON merge patch; `replace` stores it as the document."),
    ] = "merge",
) -> str:
    """Change a contract's metadata document, in its draft.

    The change is saved to the contract's draft, opening one when there is none. `merge` follows
    RFC 7386: an object merges into the document, `null` removes a field, and any other value
    replaces what is there. An array is replaced whole, so to change one table in `schema` or one
    column in its `properties`, send the whole list.

    A quality rule that a test type checks is refused: add it as a test with `create_test`. A rule
    no test type checks is saved marked unverifiable, and is exported with the contract but not
    run. `apiVersion`, `kind`, `id`, `version`, and `status` cannot be changed, and `name` is the
    contract's name: rename the contract with `update_test_suite`. `status` follows the version: `draft`,
    `active`, or `deprecated` once a later version is frozen. A change that would make the document
    invalid is refused with the path of each problem, and nothing is saved.

    Under source-data protection, send each `<hidden:…>` placeholder back to keep its value.
    """
    parsed_mode = parse_enum(mode, MetadataUpdateMode, "mode")
    suite = resolve_contract(test_suite_id)
    current = SuiteVersion.draft_for(suite.id) or SuiteVersion.in_force_for(suite.id)
    if current is None:
        raise MCPUserError(f"Contract `{suite.test_suite}` has no version to change.")
    before = copy.deepcopy(current.metadata_document or {})
    if "name" in before:
        before["name"] = suite.test_suite
    patch = _resolve_placeholders(patch, before)
    document = patch if parsed_mode is MetadataUpdateMode.REPLACE else apply_merge_patch(before, patch)
    hide_source_data = mcp_source_data_protected()

    try:
        saved = contract_service.save_metadata_document(suite, document)
    except CheckableRuleError as e:
        raise_validation_error(
            e.problems,
            "No changes saved. Test types check these rules, so add each one as a test with `create_test`:",
        )
    except OwnedFieldError as e:
        raise_validation_error(e.problems, "No changes saved.")
    except InvalidContractDocumentError as e:
        raise_validation_error(
            _problem_lines(e.problems, hide_source_data), "No changes saved. The document would not be valid ODCS:"
        )
    except ValueError as e:
        raise MCPUserError(str(e)) from e

    version = SuiteVersion.get(saved.version_id)
    doc = MdDoc()
    doc.heading(1, f"Contract `{suite.test_suite}` metadata updated")
    doc.field("Version", format_version(version.version, VersionState.DRAFT))
    doc.field("Mode", parsed_mode.value)
    _render_document_changes(
        doc,
        contract_comparison.document_changes(before, version.metadata_document or {}, hide_source_data),
        heading="Changes",
    )
    if saved.unverifiable_rules:
        doc.heading(2, f"Stored as unverifiable ({len(saved.unverifiable_rules)})")
        doc.text(
            "No test type checks these rules. They are exported with the contract and are not run. "
            "`testgen://contract-rule-mappings` lists the rule shapes that become tests."
        )
        doc.bullets([_inline_text(label) for label in saved.unverifiable_rules])
    if saved.untested_declarations:
        doc.heading(2, f"Declarations with no test ({len(saved.untested_declarations)})")
        doc.text("A test type checks these declarations, but the contract holds no such test on the column yet.")
        doc.bullets([_inline_text(label) for label in saved.untested_declarations])
    if saved.overridden_declarations:
        doc.heading(2, f"Declarations set by a test ({len(saved.overridden_declarations)})")
        doc.text(
            "A test on the column declares these with a different value, and the exported contract shows the "
            "test's value. To change it, change the test with `update_test`."
        )
        doc.bullets([_inline_text(label) for label in saved.overridden_declarations])
    if saved.unresolved_declarations:
        doc.heading(2, f"Declarations no test checks ({len(saved.unresolved_declarations)})")
        doc.text("No test type checks exactly these declarations. They stay in the contract's document.")
        doc.bullets([_inline_text(label) for label in saved.unresolved_declarations])
    if saved.problems:
        doc.heading(2, f"Problems the document already had ({len(saved.problems)})")
        doc.text("Freezing this draft is refused until these are fixed.")
        doc.bullets([_inline_text(problem) for problem in _problem_lines(saved.problems, hide_source_data)])
    return doc.render()


def _problem_lines(problems: list[str], hide_source_data: bool) -> list[str]:
    """``problems``, each reduced to its path under source-data protection, since a validation
    message quotes the value it rejects."""
    if not hide_source_data:
        return problems
    return [
        f"{problem.partition(': ')[0]}: does not match the ODCS schema." if problem.startswith("$") else problem
        for problem in problems
    ]


@with_database_session
@mcp_permission("view")
def diff_contract_versions(
    test_suite_id: Annotated[str, Field(description="UUID of the contract, e.g. from `list_test_suites`.")],
    from_version: Annotated[int, Field(description="Version number to compare from, e.g. from `list_contract_versions`.")],
    to_version: Annotated[
        int | None,
        Field(description="Version number to compare to. Defaults to the draft where one exists, otherwise the version in force."),
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of changed tests per page (default 20, max 100).")] = 20,
    page: Annotated[int, Field(description="Page number, starting from 1 (default 1).")] = 1,
) -> str:
    """Compare two versions of a contract, test by test and in its metadata.

    Lists the tests added, removed, or changed between the two versions. Each changed test shows the
    fields that differ, and whether test generation rewrote it, someone edited it, or both. The
    first page also lists what changed in the metadata document, by path.

    Without permission to view PII, a test on a PII column names the changed fields that can carry
    values from the data, without their values.
    """
    validate_page(page)
    validate_limit(limit, 100)
    suite = resolve_contract(test_suite_id)
    source = resolve_contract_version(suite, from_version)
    target = (
        resolve_contract_version(suite, to_version)
        if to_version is not None
        else SuiteVersion.draft_for(suite.id) or SuiteVersion.in_force_for(suite.id)
    )
    if target.id == source.id:
        raise MCPUserError(f"`from_version` and `to_version` are both v{source.version}. Pick two different versions.")

    changes = contract_comparison.term_changes(source.id, target.id)
    counts = {kind: sum(1 for change in changes if change.kind is kind) for kind in TermChangeKind}
    page_changes = changes[(page - 1) * limit : page * limit]
    labels = _test_type_labels({change.term.test_type for change in page_changes})
    hide_source_data = mcp_source_data_protected()
    pii_columns = (
        frozenset()
        if get_project_permissions().has_permission("view_pii", suite.project_code)
        else contract_comparison.pii_columns(suite, source, target)
    )

    doc = MdDoc()
    doc.heading(1, f"Contract `{suite.test_suite}`: {_version_label(source, suite)} to {_version_label(target, suite)}")
    for kind, count in counts.items():
        if count:
            doc.field(kind.value, count)
    if not changes:
        doc.text("No test changed.")
    if page == 1:
        _render_document_changes(
            doc, contract_comparison.version_document_changes(source, target, suite, hide_source_data)
        )

    if changes and not page_changes:
        doc.text(f"No tests on page {page} (total: {len(changes)}).")
    elif changes:
        doc.heading(2, "Tests")
        doc.text(format_page_info(len(changes), page, limit))
        doc.table(
            ["Change", "Rule ID", "Test Type", "Table", "Column", "Fields"],
            [
                [
                    change.kind.value,
                    change.term.contract_term_id,
                    labels.get(change.term.test_type, change.term.test_type),
                    change.term.table_name,
                    change.term.column_name,
                    ", ".join(change.fields) or None,
                ]
                for change in page_changes
            ],
        )
        for change in page_changes:
            if change.before is None or change.after is None:
                continue
            doc.heading(3, f"{change.kind.value}: {MdDoc.code(change.term.contract_term_id or str(change.term.id))}")
            hidden = [field for field in change.fields if hide_source_data and field in CALIBRATION_SHAPED_PARAM_COLUMNS]
            redacted = [
                field for field in contract_comparison.pii_redacted_fields(change, pii_columns) if field not in hidden
            ]
            shown = [field for field in change.fields if field not in hidden and field not in redacted]
            render_diff_table(
                doc,
                {field: getattr(change.before, field) for field in shown},
                {field: getattr(change.after, field) for field in shown},
                attrs=shown,
                labels={},
            )
            if hidden:
                doc.field("Omitted Fields", ", ".join(hidden))
            if redacted:
                doc.field("PII Redacted Fields", ", ".join(redacted))
        if footer := format_page_footer(len(changes), page, limit):
            doc.text(footer)
    return doc.render()


def _version_label(version: SuiteVersion, suite: TestSuite) -> str:
    is_active = version.frozen_at is not None and SuiteVersion.is_active(version.id, suite.id)
    return format_version(version.version, version_state(version.frozen_at, is_active))


def _render_document_changes(
    doc: MdDoc, changes: list[contract_comparison.DocumentChange], heading: str = "Metadata document"
) -> None:
    doc.heading(2, heading)
    if not changes:
        doc.text("No change.")
        return
    doc.table(["Path", "Change"], [[change.path, change.kind.value] for change in changes], code=[0])


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


_TERM_REASON_LABELS: dict[ContractTermReason, str] = {
    ContractTermReason.MATCHED_BY_ID: "Matched by rule ID",
    ContractTermReason.MATCHED_BY_KEY: "Matched by test type, table and column",
    ContractTermReason.UNCHANGED: "Unchanged",
    ContractTermReason.NEW: "Not in the contract",
    ContractTermReason.ABSENT: "Not in the document",
}

_ACTION_HEADINGS: dict[ImportAction, str] = {
    ImportAction.create: "To create",
    ImportAction.update: "To update",
    ImportAction.delete: "To delete",
    ImportAction.skip: "Unchanged",
}


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
        frozen = contract_service.freeze_version(suite, label=label, username=get_mcp_username())
    except InvalidContractDocumentError as e:
        raise MCPUserError(
            "The draft cannot be frozen because its document does not validate:\n"
            + "\n".join(f"- {problem}" for problem in _problem_lines(e.problems, mcp_source_data_protected()))
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
    doc.field("Tests removed besides schema conformance", removed)
    doc.field("Contract is now at", format_version(now_at.version, VersionState.ACTIVE))
    return doc.render()


@with_database_session
@mcp_permission("edit")
def import_contract(
    payload: Annotated[str, Field(description="The ODCS document, as YAML or JSON text.")],
    test_suite_id: Annotated[
        str | None,
        Field(
            description="UUID of the contract to import into. The document replaces the contract's draft, and opens "
            "one when the contract has none. Omit to create a contract instead.",
        ),
    ] = None,
    table_group_id: Annotated[
        str | None,
        Field(description="UUID of the table group to create a contract in. Omit to import into `test_suite_id`."),
    ] = None,
    test_suite_name: Annotated[
        str | None,
        Field(
            description="Name for the contract being created, which becomes the document's `name`. Defaults to "
            "the name the document declares, and is required when it declares none.",
        ),
    ] = None,
    mode: Annotated[
        str,
        Field(description="`preview` (default) reports every change without saving anything; `apply` saves them."),
    ] = "preview",
) -> str:
    """Import an ODCS document as a new contract, or into an existing contract's draft.

    The document is the whole agreement. Its quality rules, and column constraints such as a
    maximum or a required column, become the contract's tests; the rest becomes its metadata.
    Active tests the contract holds that the document does not state are deleted, and muted tests are
    kept. Every test the document states is locked against test generation. Preview first, and check the deletions.

    Supply exactly one of `test_suite_id` and `table_group_id`. An import never changes a frozen
    version. A document whose contract `id` differs from the contract's is refused, as is a new
    contract whose `id` another contract in the table group already has.

    A rule TestGen cannot check stays in the document, marked unverifiable. SQL in the document is
    not translated between database dialects; the response warns when the document declares a
    server of a different type than the connection.
    """
    parsed_mode = parse_enum(mode, ContractImportMode, "mode")
    if test_suite_id and table_group_id:
        raise MCPUserError(
            "Supply `test_suite_id` or `table_group_id`, not both. `test_suite_id` imports into that contract's "
            "draft; `table_group_id` creates a contract."
        )
    if not test_suite_id and not table_group_id:
        raise MCPUserError(
            "Supply either `test_suite_id` (to import into that contract's draft) or `table_group_id` (to create a "
            "contract in that table group)."
        )

    if test_suite_id:
        suite: TestSuite | None = resolve_contract(test_suite_id)
        table_group = TableGroup.get(suite.table_groups_id)
    else:
        suite = None
        table_group = resolve_table_group(table_group_id)

    connection = Connection.get(table_group.connection_id)

    try:
        plan = contract_import.prepare_import(payload, table_group, connection, suite)
    except InvalidContractDocumentError as e:
        raise_validation_error(e.problems, "The document was not imported. No changes saved.")
    except ContractIdentityError as e:
        incoming, target = _inline_code(e.incoming_id), _inline_code(e.target_id)
        raise MCPUserError(
            f"The document's contract `id` is {incoming}, but this contract's is {target}, so the document is a "
            f"different agreement. To import it into this contract, change the document's `id` to {target}. If it "
            "is a separate agreement, call `import_contract` with `table_group_id` instead of `test_suite_id` to "
            "create a new contract. No changes saved."
        ) from e

    if suite is None:
        name = (test_suite_name or plan.document_name or "").strip()
        if not name:
            raise MCPUserError("The document declares no `name`, so `test_suite_name` is required. No changes saved.")
        suite = TestSuite(
            project_code=table_group.project_code,
            connection_id=table_group.connection_id,
            table_groups_id=table_group.id,
            test_suite=name,
            suite_type=SuiteType.CONTRACT.value,
        )
        if errors := validate_test_suite_fields(suite):
            raise_validation_error(errors, "The contract was not created. No changes saved.")
        creating = True
    else:
        creating = False

    version_label = None
    conformance_failed = False
    if parsed_mode is ContractImportMode.APPLY:
        if creating:
            try:
                created = contract_creation.create_contract_from_import(suite, table_group, connection, plan)
            except IntegrityError as err:
                if is_duplicate_name_error(err):
                    raise MCPUserError(f"{duplicate_name_message(suite.test_suite)} No changes saved.") from err
                raise
            record_contract_created(created.suite)
            version_id, conformance_failed = created.version_id, created.conformance_failed
        else:
            applied = contract_import.apply_import(plan, suite, table_group, SqlFlavorCode(connection.sql_flavor_code))
            version_id, conformance_failed = applied.version_id, applied.conformance_failed
        version = SuiteVersion.get(version_id)
        is_active = version.frozen_at is not None and SuiteVersion.is_active(version.id, suite.id)
        version_label = format_version(version.version, version_state(version.frozen_at, is_active))

    return _render_import(
        plan, suite, parsed_mode, creating=creating, version_label=version_label, conformance_failed=conformance_failed
    )


def _render_import(
    plan: ContractImportPlan,
    suite: TestSuite,
    mode: ContractImportMode,
    *,
    creating: bool,
    version_label: str | None,
    conformance_failed: bool = False,
) -> str:
    preview = mode is ContractImportMode.PREVIEW
    name = _inline_code(suite.test_suite)
    doc = MdDoc()
    if preview:
        doc.heading(1, f"Contract Import Preview for {name}")
        doc.text("Preview only — no changes were persisted. Re-run with `mode='apply'` to persist.")
    else:
        doc.heading(1, f"Contract {name} {'created' if creating else 'imported'}")
        doc.field("ID", str(suite.id), code=True)
        doc.field("Version", version_label)
    if conformance_failed:
        doc.text(
            "The import was saved, but updating its schema conformance tests failed. Re-run this import with "
            "`mode='apply'` to update them."
        )
    if plan.document_id:
        doc.field("ODCS contract ID", _inline_code(plan.document_id))

    suffix = " (projected)" if preview else ""
    doc.field(f"Created{suffix}", plan.count(ImportAction.create))
    doc.field(f"Updated{suffix}", plan.count(ImportAction.update))
    doc.field(f"Deleted{suffix}", plan.count(ImportAction.delete))
    doc.field("Unchanged", plan.count(ImportAction.skip))
    doc.field("Rules and constraints that became tests", plan.resolved_count)
    doc.field("Rules kept as unverifiable", len(plan.unverifiable_rules))
    doc.field("Constraints no test checks", len(plan.unresolved_declarations))
    doc.text(
        f"Every test the document states {'is' if preview else 'was'} locked, unchanged ones included, "
        "so test generation does not change or delete it. The counts above leave out schema conformance: "
        "each table the document declares gets a Schema Conformance test, checking its columns and types."
    )

    if plan.server_type_warning:
        doc.text(f"Warning: {plan.server_type_warning}")
    if plan.tables_not_in_catalog:
        doc.text(
            "The data catalog holds no columns for "
            f"{', '.join(_inline_code(table) for table in plan.tables_not_in_catalog)}, so those tables get no schema "
            "conformance test until they appear in the catalog."
        )

    labels = _test_type_labels({change.test_type for change in plan.changes})
    for action in (ImportAction.delete, ImportAction.create, ImportAction.update, ImportAction.skip):
        changes = [change for change in plan.changes if change.action is action]
        if not changes:
            continue
        doc.heading(2, f"{_ACTION_HEADINGS[action]} ({len(changes)})")
        doc.table(
            ["Rule ID", "Test Type", "Table", "Column", "Reason"],
            [
                [
                    change.contract_term_id or "",
                    labels.get(change.test_type, change.test_type),
                    change.table_name,
                    change.column_name or "",
                    _TERM_REASON_LABELS[change.reason],
                ]
                for change in changes
            ],
        )

    if plan.unverifiable_rules:
        doc.heading(2, f"Kept as unverifiable ({len(plan.unverifiable_rules)})")
        doc.text(
            "TestGen cannot check these rules. They stay in the contract's document and are not run. "
            "`testgen://contract-rule-mappings` lists the rule shapes that become tests."
        )
        doc.bullets([_inline_text(label) for label in plan.unverifiable_rules])
    if plan.unresolved_declarations:
        doc.heading(2, f"Constraints no test checks ({len(plan.unresolved_declarations)})")
        doc.text("No test checks exactly these constraints. They stay in the contract's document.")
        doc.bullets([_inline_text(label) for label in plan.unresolved_declarations])
    return doc.render()


def _inline_text(value: str) -> str:
    """Text from a document, as one escaped line."""
    return MdDoc.escape(" ".join(str(value).split()))


def _inline_code(value: str) -> str:
    """Text from a document, as one code span."""
    return MdDoc.code(" ".join(str(value).split()))


def _test_type_labels(codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    rows = get_current_session().execute(
        select(TestType.test_type, TestType.test_name_short).where(TestType.test_type.in_(codes))
    )
    return {code: short_name or code for code, short_name in rows}
