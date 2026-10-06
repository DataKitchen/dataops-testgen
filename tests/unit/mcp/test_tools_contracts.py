"""Tests for the MCP contract export tool."""

import hashlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen import settings
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.odcs.render import OrphanedTermError
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND, UnmappedFlavorError
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import ProjectPermissions
from testgen.mcp.tools.contracts import export_contract, split_document

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.contracts"

FROZEN_YAML = (
    f"apiVersion: {ODCS_API_VERSION}\n"
    f"kind: {ODCS_KIND}\n"
    "id: orders-contract\n"
    "version: 3.0.0\n"
)


def _patch_perms(allowed=("demo",)):
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships=dict.fromkeys(allowed, "role_a"), permission="view", username="test_user"
        ),
    )


def _contract(name="Orders"):
    suite = MagicMock()
    suite.id = uuid4()
    suite.test_suite = name
    return suite


def _frozen(version=3):
    return SuiteVersion(
        id=uuid4(), version=version, frozen_document=FROZEN_YAML, frozen_at=datetime(2026, 9, 12, tzinfo=UTC)
    )


def _draft(version=4, document=None):
    return SuiteVersion(
        id=uuid4(),
        version=version,
        metadata_document=document
        or {"apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND, "id": "orders-contract", "version": "4.0.0"},
    )


def _export(suite, target, *, active=True, **kwargs):
    """Run the tool with the suite and target version resolved for it."""
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch(f"{MODULE}.contract_service.version_for_export", return_value=target),
        patch.object(SuiteVersion, "is_active", return_value=active),
    ):
        return export_contract(test_suite_id=str(suite.id), **kwargs)


# --- the bytes ---


def test_a_frozen_version_returns_the_bytes_stored_at_freeze(db_session_mock):
    out = _export(_contract(), _frozen())

    assert FROZEN_YAML in out


def test_a_frozen_version_is_never_rendered(db_session_mock):
    """The stored bytes are the agreement. Rendering them again would make the export a
    fresh opinion that happens to agree, and stop agreeing the day the renderer changes."""
    with patch(
        "testgen.common.odcs.render.render_document", side_effect=AssertionError("rendered a frozen version")
    ):
        out = _export(_contract(), _frozen())

    assert FROZEN_YAML in out


def test_a_draft_is_rendered_fresh_and_reflects_a_later_edit(db_session_mock):
    draft, suite = _draft(), _contract()
    before = {"apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND, "id": "orders", "version": "4.0.0"}
    after = before | {"description": {"purpose": "added since the last export"}}

    with patch("testgen.common.odcs.render.render_document", return_value=before):
        first = _export(suite, draft)
    with patch("testgen.common.odcs.render.render_document", return_value=after):
        second = _export(suite, draft)

    assert "added since the last export" not in first
    assert "added since the last export" in second


# --- naming the version ---


def test_the_response_names_a_version_that_was_asked_for(db_session_mock):
    out = _export(_contract(), _frozen(version=3), active=True, version=3)

    assert "v3 active" in out


def test_the_response_names_the_draft_when_no_version_was_asked_for(db_session_mock):
    with patch("testgen.common.odcs.render.render_document", return_value={"id": "orders"}):
        out = _export(_contract(), _draft(version=4))

    assert "v4 draft" in out


def test_the_response_names_the_active_version_when_no_version_was_asked_for(db_session_mock):
    out = _export(_contract(), _frozen(version=3), active=True)

    assert "v3 active" in out


def test_a_frozen_version_that_is_no_longer_in_force_reads_as_superseded(db_session_mock):
    out = _export(_contract(), _frozen(version=2), active=False, version=2)

    assert "v2 superseded" in out


# --- the ticket's non-errors ---


def test_a_contract_with_no_frozen_version_and_no_terms_is_not_an_error(db_session_mock):
    """A draft being written is a legitimate thing to look at."""
    document = {"apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND, "id": "orders", "version": "1.0.0"}
    with patch("testgen.common.odcs.render.render_document", return_value=document):
        out = _export(_contract(), _draft(version=1, document=document))

    assert "v1 draft" in out
    assert "orders" in out


# --- validation problems ---


def test_validation_problems_are_reported_and_the_document_still_comes_back(db_session_mock):
    """A draft is never validated until something validates it, and freeze is the gate.
    Exporting answers whether the gate would open, without committing to opening it."""
    with patch("testgen.common.odcs.render.render_document", return_value={"kind": "NotAContract"}):
        out = _export(_contract(), _draft())

    assert "NotAContract" in out
    assert "kind" in out


def test_a_document_that_validates_reports_no_problems(db_session_mock):
    out = _export(_contract(), _frozen())

    assert "does not validate" not in out


# --- failures ---


@pytest.mark.parametrize(
    "error",
    [
        OrphanedTermError("term names a table this document does not declare"),
        UnmappedFlavorError("no server type for flavor"),
        ValueError("test type is excluded from contract rendering"),
    ],
    ids=["orphaned-term", "unmapped-flavor", "excluded-type"],
)
def test_a_render_failure_reaches_the_caller_as_a_user_error(error, db_session_mock):
    with patch("testgen.common.odcs.render.render_document", side_effect=error):
        with pytest.raises(MCPUserError, match=str(error)):
            _export(_contract(), _draft())


def test_a_version_the_contract_does_not_have_is_a_user_error(db_session_mock):
    suite = _contract()
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch(
            f"{MODULE}.contract_service.version_for_export",
            side_effect=ValueError("This contract has no version 9."),
        ),
    ):
        with pytest.raises(MCPUserError, match="no version 9"):
            export_contract(test_suite_id=str(suite.id), version=9)


# --- the response is a file an agent can write ---


def test_the_document_sits_in_a_yaml_fence(db_session_mock):
    out = _export(_contract(), _frozen())

    assert f"```yaml\n{FROZEN_YAML}" in out


def test_a_document_containing_a_triple_backtick_escalates_the_fence(db_session_mock):
    """A description field carrying backticks would otherwise close the block early and
    hand the caller a truncated file that looks complete."""
    document = FROZEN_YAML + 'description:\n  purpose: "see ``` the example"\n'
    version = SuiteVersion(
        id=uuid4(), version=3, frozen_document=document, frozen_at=datetime(2026, 9, 12, tzinfo=UTC)
    )

    out = _export(_contract(), version)

    assert "````yaml" in out
    assert document in out


# --- splitting a document that does not fit one response ---


def _lines(count, width=40):
    return "".join(f"{'x' * width} line {i}\n" for i in range(count))


def test_a_document_within_the_threshold_is_not_split():
    document = _lines(5)

    assert split_document(document, 10_000) == [document]


def test_the_pieces_concatenate_back_into_the_document_exactly():
    """The chunks are a transport detail. Reassembled they are the agreement, byte for byte,
    or the caller has written a file that only looks like the contract."""
    document = _lines(500)

    assert "".join(split_document(document, 2_000)) == document


def test_no_piece_exceeds_the_threshold_when_the_lines_fit_inside_it():
    pieces = split_document(_lines(500), 2_000)

    assert len(pieces) > 1
    assert all(len(piece.encode()) <= 2_000 for piece in pieces)


def test_a_single_line_longer_than_the_threshold_becomes_its_own_piece():
    """Cut mid-line and the split can land inside a multi-byte character, which no amount of
    reassembly discipline on the caller's side would repair."""
    document = _lines(2) + "y" * 5_000 + "\n" + _lines(2)

    pieces = split_document(document, 500)

    assert "".join(pieces) == document
    assert any(len(piece.encode()) > 500 for piece in pieces)


def test_splitting_counts_bytes_not_characters():
    """A multi-byte character costs more than one byte of the budget it is measured against."""
    document = "".join(f"{'é' * 50} line {i}\n" for i in range(100))

    pieces = split_document(document, 1_000)

    assert "".join(pieces) == document
    assert all(len(piece.encode()) <= 1_000 for piece in pieces)


# --- the chunked response ---


def _big_contract(lines=400):
    body = "".join(f"  # padding padding padding padding padding line {i}\n" for i in range(lines))
    return FROZEN_YAML + "description:\n  purpose: >\n" + body


def _export_chunked(document, limit, **kwargs):
    version = SuiteVersion(
        id=uuid4(), version=3, frozen_document=document, frozen_at=datetime(2026, 9, 12, tzinfo=UTC)
    )
    with patch.object(settings, "MCP_CONTRACT_EXPORT_CHUNK_BYTES", limit):
        return _export(_contract(), version, **kwargs)


def test_a_document_inside_the_threshold_says_nothing_about_chunks(db_session_mock):
    out = _export_chunked(FROZEN_YAML, 10_000)

    assert "chunk" not in out.lower()


def test_the_first_chunk_reports_the_whole_size_and_the_count_before_any_content(db_session_mock):
    """The cost is known at the first call rather than discovered at the cut."""
    document = _big_contract()
    pieces = split_document(document, 2_000)

    out = _export_chunked(document, 2_000)

    assert f"chunk 1 of {len(pieces)}" in out
    assert out.index(f"chunk 1 of {len(pieces)}") < out.index("```")


def test_the_first_chunk_says_how_to_get_the_next(db_session_mock):
    out = _export_chunked(_big_contract(), 2_000)

    assert "chunk=2" in out


def test_the_chunks_reassemble_into_the_stored_bytes(db_session_mock):
    document = _big_contract()
    pieces = split_document(document, 2_000)

    rebuilt = ""
    for index in range(1, len(pieces) + 1):
        out = _export_chunked(document, 2_000, chunk=index)
        body = out.split("```yaml\n", 1)[1].rsplit("\n```", 1)[0]
        rebuilt += body + "\n" if not body.endswith("\n") else body

    assert rebuilt == document


def test_the_last_chunk_does_not_invite_another(db_session_mock):
    document = _big_contract()
    last = len(split_document(document, 2_000))

    out = _export_chunked(document, 2_000, chunk=last)

    assert f"chunk {last} of {last}" in out
    assert f"chunk={last + 1}" not in out


def test_a_chunk_past_the_end_is_a_user_error_naming_the_count(db_session_mock):
    document = _big_contract()
    count = len(split_document(document, 2_000))

    with pytest.raises(MCPUserError, match=str(count)):
        _export_chunked(document, 2_000, chunk=count + 1)


def test_a_chunk_below_one_is_a_user_error(db_session_mock):
    with pytest.raises(MCPUserError):
        _export_chunked(_big_contract(), 2_000, chunk=0)


def test_validation_problems_are_reported_once_not_on_every_chunk(db_session_mock):
    """They describe the document, not the piece, so repeating them reads as new findings."""
    document = _big_contract() + "kind: NotAContract\n"
    with patch("testgen.common.odcs.render.render_document"):
        first = _export_chunked(document, 2_000, chunk=1)
        second = _export_chunked(document, 2_000, chunk=2)

    assert "NotAContract" in first
    assert "NotAContract" not in second


def test_every_chunk_carries_the_digest_of_the_whole_document(db_session_mock):
    """A draft is rendered afresh for each chunk, so a caller needs a way to tell that the
    pieces it holds came from one document."""
    document = _big_contract()
    count = len(split_document(document, 2_000))
    digest = hashlib.sha256(document.encode()).hexdigest()

    for index in range(1, count + 1):
        assert digest in _export_chunked(document, 2_000, chunk=index)


def test_a_changed_document_carries_a_different_digest(db_session_mock):
    document = _big_contract()
    changed = document + "# edited\n"

    assert hashlib.sha256(changed.encode()).hexdigest() in _export_chunked(changed, 2_000, chunk=2)
    assert hashlib.sha256(document.encode()).hexdigest() not in _export_chunked(changed, 2_000, chunk=2)
