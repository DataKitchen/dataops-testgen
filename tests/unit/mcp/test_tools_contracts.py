"""Tests for the MCP contract read tools."""

import copy
import hashlib
import re
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import yaml

from testgen import settings
from testgen.common.contract_service import CheckableRuleError, InvalidContractDocumentError, SavedMetadata
from testgen.common.enums import JobStatus
from testgen.common.models.suite_version import SuiteVersion, SuiteVersionListItem
from testgen.common.models.test_definition import TestDefinition
from testgen.common.odcs.render import OrphanedTermError
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND
from testgen.mcp.exceptions import MCPPermissionDenied, MCPUserError
from testgen.mcp.permissions import ProjectPermissions
from testgen.mcp.tools.contracts import (
    _with_placeholders,
    diff_contract_versions,
    discard_contract_draft,
    export_contract,
    freeze_contract_version,
    get_contract_metadata,
    list_contract_versions,
    split_document,
    update_contract_metadata,
)

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
        ValueError("test type is excluded from contract rendering"),
    ],
    ids=["orphaned-term", "excluded-type"],
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


# --- get_contract_metadata ---


def _read_metadata(suite, target, *, active=True, protected=False, **kwargs):
    with (
        _patch_perms(),
        patch(f"{MODULE}.mcp_source_data_protected", return_value=protected),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch(f"{MODULE}.contract_service.version_for_export", return_value=target) as resolve,
        patch.object(SuiteVersion, "is_active", return_value=active),
    ):
        return get_contract_metadata(test_suite_id=str(suite.id), **kwargs), resolve


def test_metadata_returns_the_stored_document_as_yaml(db_session_mock):
    document = {"schema": [{"name": "orders", "properties": [{"name": "id", "logicalType": "integer"}]}]}

    out, _ = _read_metadata(_contract(), _draft(document=document))

    assert "- name: orders" in out
    assert "logicalType: integer" in out


def test_metadata_names_the_version_it_read(db_session_mock):
    out, _ = _read_metadata(_contract(), _draft(version=4))
    assert "v4 draft" in out

    out, _ = _read_metadata(_contract(), _frozen(version=3), active=True)
    assert "v3 active" in out


def test_metadata_passes_the_requested_version_through(db_session_mock):
    suite = _contract()

    _, resolve = _read_metadata(suite, _frozen(version=2), version=2)

    resolve.assert_called_once_with(suite, 2)


def test_metadata_says_where_the_terms_are(db_session_mock):
    out, _ = _read_metadata(_contract(), _draft())

    assert "The contract's terms are not included" in out
    assert "list_tests" in out
    assert "export_contract" in out


def test_metadata_reports_a_contract_with_no_version_as_a_user_error(db_session_mock):
    suite = _contract()
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch(f"{MODULE}.contract_service.version_for_export", side_effect=ValueError("This contract has no version 9.")),
    ):
        with pytest.raises(MCPUserError, match="no version 9"):
            get_contract_metadata(test_suite_id=str(suite.id), version=9)


def test_a_large_metadata_document_arrives_in_chunks(db_session_mock, monkeypatch):
    monkeypatch.setattr(settings, "MCP_CONTRACT_EXPORT_CHUNK_BYTES", 200)
    document = {"schema": [{"name": f"table_{index}", "description": "x" * 60} for index in range(10)]}

    first, _ = _read_metadata(_contract(), _draft(document=document))
    second, _ = _read_metadata(_contract(), _draft(document=document), chunk=2)

    assert "chunk 1 of" in first
    assert "chunk=2" in first
    assert "chunk 2 of" in second
    assert "The contract's terms are not included" not in second


_DOCUMENT_WITH_SOURCE_VALUES = {
    "schema": [{
        "name": "orders",
        "quality": [{"metric": "rowCount", "mustBeGreaterThan": 100, "description": "Has rows"}],
        "properties": [
            {
                "name": "amount",
                "logicalType": "number",
                "logicalTypeOptions": {"minimum": 0.5, "maximum": 120},
                "customProperties": [{"property": "profiledValues", "value": {"minimum": 0.5, "maximum": 120}}],
                "examples": [42.0],
                "enum": [{"value": 42.0}],
            },
            {
                "name": "status",
                "logicalType": "string",
                "logicalTypeOptions": {"minLength": 2, "maxLength": 8},
                "customProperties": [
                    {"property": "owner", "value": "ops"},
                    {"property": "profiledValues", "value": {"minLength": 2, "maxLength": 8}},
                ],
                "quality": [
                    {"metric": "invalidValues", "arguments": {"validValues": ["open"]}, "mustBe": 0},
                    {"type": "sql", "query": "SELECT COUNT(*) FROM orders WHERE status = 'open'", "mustBe": 0},
                ],
            },
        ],
    }],
}


def test_metadata_under_protection_shows_a_placeholder_for_each_value_that_can_come_from_the_data(db_session_mock):
    out, _ = _read_metadata(_contract(), _draft(document=_DOCUMENT_WITH_SOURCE_VALUES), protected=True)

    document = yaml.safe_load(out.split("```yaml\n", 1)[1].split("```", 1)[0])
    amount, status = document["schema"][0]["properties"]
    hidden = [
        amount["logicalTypeOptions"]["minimum"],
        amount["logicalTypeOptions"]["maximum"],
        amount["customProperties"][0]["value"]["minimum"],
        amount["examples"],
        amount["enum"],
        status["quality"][0]["arguments"],
        status["quality"][0]["mustBe"],
        document["schema"][0]["quality"][0]["mustBeGreaterThan"],
    ]
    assert all(_PLACEHOLDER.fullmatch(value) for value in hidden)
    assert len(set(hidden)) == len(hidden), "equal values (the two 0.5 minimums) must not share a placeholder"
    assert status["logicalTypeOptions"] == {"minLength": 2, "maxLength": 8}
    assert status["customProperties"] == _DOCUMENT_WITH_SOURCE_VALUES["schema"][0]["properties"][1]["customProperties"]
    assert status["quality"][1]["query"] == "SELECT COUNT(*) FROM orders WHERE status = 'open'"
    visible = _PLACEHOLDER.sub("", out)
    assert "0.5" not in visible and "120" not in visible and "42.0" not in visible
    assert "Hidden Fields" in out
    assert "list_tests" in out
    assert "export_contract" not in out


def test_metadata_leaves_the_stored_document_untouched_under_protection(db_session_mock):
    document = copy.deepcopy(_DOCUMENT_WITH_SOURCE_VALUES)

    _read_metadata(_contract(), _draft(document=document), protected=True)

    assert document == _DOCUMENT_WITH_SOURCE_VALUES


def test_metadata_without_protection_returns_every_field(db_session_mock):
    out, _ = _read_metadata(_contract(), _draft(document=_DOCUMENT_WITH_SOURCE_VALUES))

    document = yaml.safe_load(out.split("```yaml\n", 1)[1].split("```", 1)[0])
    assert document == _DOCUMENT_WITH_SOURCE_VALUES
    assert "Hidden Fields" not in out


# --- list_contract_versions, freeze_contract_version, discard_contract_draft ---


def _item(version, frozen_at=None, **kw):
    return SuiteVersionListItem(
        id=uuid4(), version=version, label=kw.get("label"), created_by=kw.get("created_by", "alice"),
        frozen_at=frozen_at, frozen_by=kw.get("frozen_by"), term_count=kw.get("term_count", 40),
        run_count=kw.get("run_count", 0),
        latest_run_id=kw.get("latest_run_id"), latest_run_status=kw.get("latest_run_status"),
        latest_run_started_at=kw.get("latest_run_started_at"),
    )


def _list(suite, items, active_version):
    in_force = SuiteVersion(id=uuid4(), version=active_version) if active_version else None
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch.object(SuiteVersion, "list_for_suite", return_value=(items, len(items))),
        patch.object(SuiteVersion, "in_force_for", return_value=in_force),
    ):
        return list_contract_versions(test_suite_id=str(suite.id))


def test_versions_are_listed_newest_first_with_their_state(db_session_mock):
    frozen = datetime(2026, 9, 12, 14, 3, tzinfo=UTC)
    run_id = uuid4()
    items = [
        _item(4, created_by="bob", term_count=41, run_count=2),
        _item(3, frozen, label="Q3 agreement", run_count=9, latest_run_id=run_id,
              latest_run_status=JobStatus.COMPLETED, latest_run_started_at=frozen),
        _item(2, frozen),
    ]
    out = _list(_contract(), items, active_version=3)
    assert out.index("v4 draft") < out.index("v3 active") < out.index("v2 superseded")
    assert "Q3 agreement" in out
    assert f"`{run_id}` Completed 2026-09-12 14:03 UTC" in out
    assert "| 41 |" in out and "| 9 |" in out


def test_a_latest_run_that_has_not_started_shows_no_time(db_session_mock):
    run_id = uuid4()
    items = [_item(3, datetime(2026, 9, 12, tzinfo=UTC), run_count=1, latest_run_id=run_id,
                   latest_run_status=JobStatus.PENDING, latest_run_started_at=None)]
    out = _list(_contract(), items, active_version=3)
    assert f"`{run_id}` Pending |" in out
    assert "None" not in out


def test_listing_versions_of_a_regular_suite_is_refused(db_session_mock):
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_contract", side_effect=MCPUserError("is not a contract, so it keeps no versions.")),
        pytest.raises(MCPUserError, match="is not a contract"),
    ):
        list_contract_versions(test_suite_id=str(uuid4()))


def _freeze(suite, *, frozen=None, previous=None, draft=True, error=None, **kwargs):
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch.object(SuiteVersion, "in_force_for", return_value=previous),
        patch.object(SuiteVersion, "draft_for", return_value=SuiteVersion(id=uuid4(), version=4) if draft else None),
        patch(f"{MODULE}.contract_service.freeze_version", return_value=frozen, side_effect=error) as freeze,
    ):
        return freeze_contract_version(test_suite_id=str(suite.id), **kwargs), freeze


def test_freezing_reports_what_now_runs_and_that_it_is_final(db_session_mock):
    frozen = SuiteVersion(id=uuid4(), version=4, label="Q4 agreement", frozen_at=datetime(2026, 10, 8, tzinfo=UTC))
    previous = SuiteVersion(id=uuid4(), version=3)
    out, freeze = _freeze(_contract(), frozen=frozen, previous=previous, label="Q4 agreement")
    assert freeze.call_args.kwargs["label"] == "Q4 agreement"
    assert "Froze v4 of contract `Orders`" in out
    assert "**Version:** v4 active" in out
    assert "**Previous version:** v3 superseded" in out
    assert "now run v4 by default" in out
    assert "cannot be changed or unfrozen" in out


def test_freezing_records_the_mcp_user_as_who_froze_it(db_session_mock):
    frozen = SuiteVersion(id=uuid4(), version=4, frozen_at=datetime(2026, 10, 8, tzinfo=UTC))
    with patch(f"{MODULE}.get_mcp_username", return_value="alice"):
        _, freeze = _freeze(_contract(), frozen=frozen)
    assert freeze.call_args.kwargs["username"] == "alice"


def test_freezing_with_no_draft_says_so_rather_than_succeeding(db_session_mock):
    previous = SuiteVersion(id=uuid4(), version=3)
    with pytest.raises(MCPUserError, match="has no draft to freeze. v3 active is already frozen"):
        _freeze(_contract(), previous=previous, draft=False)


def test_freezing_passes_other_refusals_through(db_session_mock):
    with pytest.raises(MCPUserError, match="orphaned term"):
        _freeze(_contract(), error=ValueError("orphaned term"))


def test_freezing_an_invalid_document_lists_the_problems(db_session_mock):
    error = InvalidContractDocumentError(["schema[0].name is required", "version is required"])
    with pytest.raises(MCPUserError, match="schema\\[0\\].name is required") as raised:
        _freeze(_contract(), error=error)
    assert "version is required" in str(raised.value)


def _discard(suite, *, count=0, now_at=None, error=None):
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch.object(SuiteVersion, "draft_for", return_value=SuiteVersion(id=uuid4(), version=4)),
        patch.object(SuiteVersion, "in_force_for", return_value=now_at),
        patch(f"{MODULE}.contract_service.discard_draft", return_value=count, side_effect=error),
    ):
        return discard_contract_draft(test_suite_id=str(suite.id))


def test_discarding_reports_tests_removed_and_the_version_returned_to(db_session_mock):
    out = _discard(_contract(), count=41, now_at=SuiteVersion(id=uuid4(), version=3))
    assert "Discarded v4 draft of contract `Orders`" in out
    assert "**Tests removed besides schema conformance:** 41" in out
    assert "**Contract is now at:** v3 active" in out


def test_discarding_when_the_service_refuses_is_a_user_error(db_session_mock):
    error = ValueError("This contract has no frozen version behind its draft; discarding it would leave ...")
    with pytest.raises(MCPUserError, match="no frozen version behind its draft"):
        _discard(_contract(), error=error)


# --- get_contract_metadata narrowing ---


_WIDE_DOCUMENT = {
    "apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND, "id": "orders-contract", "version": "4.0.0",
    "support": [{"channel": "#orders", "url": "https://chat.example.com/orders"}],
    "schema": [
        {"name": "orders", "properties": [{"name": "amount", "logicalType": "number"}, {"name": "placed_at"}]},
        {"name": "customers", "properties": [{"name": "email", "logicalType": "string"}]},
    ],
}


def _narrowed(out):
    return yaml.safe_load(out.split("```yaml\n", 1)[1].split("```", 1)[0])


def test_metadata_narrows_to_one_section(db_session_mock):
    out, _ = _read_metadata(_contract(), _draft(document=_WIDE_DOCUMENT), section="support")

    assert _narrowed(out) == {"support": _WIDE_DOCUMENT["support"]}
    assert "**Filters:** section `support`" in out


def test_metadata_narrows_to_one_table_without_the_rest_of_the_schema(db_session_mock):
    out, _ = _read_metadata(_contract(), _draft(document=_WIDE_DOCUMENT), table_name="orders")

    assert _narrowed(out) == {"schema": [_WIDE_DOCUMENT["schema"][0]]}
    assert "customers" not in out


def test_metadata_narrows_to_one_column_inside_its_table(db_session_mock):
    out, _ = _read_metadata(_contract(), _draft(document=_WIDE_DOCUMENT), table_name="orders", column_name="amount")

    assert _narrowed(out) == {"schema": [{"name": "orders", "properties": [{"name": "amount", "logicalType": "number"}]}]}
    assert "**Filters:** table `orders`, column `amount`" in out


_PHYSICAL_DOCUMENT = {
    "apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND, "id": "orders-contract", "version": "4.0.0",
    "schema": [
        {"name": "orders", "physicalName": "tbl_orders", "properties": [
            {"name": "total", "physicalName": "amt", "logicalType": "number"}, {"name": "placed_at"},
        ]},
        {"name": "customers", "properties": [{"name": "email", "logicalType": "string"}]},
    ],
}


@pytest.mark.parametrize(("table_name", "column_name"), [("tbl_orders", "amt"), ("orders", "total")])
def test_metadata_narrows_to_a_column_by_its_name_or_its_physical_name(db_session_mock, table_name, column_name):
    out, _ = _read_metadata(
        _contract(), _draft(document=_PHYSICAL_DOCUMENT), table_name=table_name, column_name=column_name
    )

    assert _narrowed(out) == {"schema": [{
        "name": "orders", "physicalName": "tbl_orders",
        "properties": [{"name": "total", "physicalName": "amt", "logicalType": "number"}],
    }]}


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"column_name": "amount"}, "`column_name` requires `table_name`"),
        ({"table_name": "orders", "section": "support"}, "Tables are in the `schema` section"),
        ({"section": "price"}, "no `price` section. Its sections are `apiVersion`"),
        ({"table_name": "invoices"}, "no table `invoices`. Its tables are `orders`, `customers`"),
        ({"table_name": "orders", "column_name": "email"}, "declares no column `email`. Its columns are `amount`, `placed_at`"),
    ],
)
def test_metadata_narrowing_errors_name_what_exists(db_session_mock, kwargs, message):
    with pytest.raises(MCPUserError, match=re.escape(message)):
        _read_metadata(_contract(), _draft(document=_WIDE_DOCUMENT), **kwargs)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"table_name": "invoices"}, "Its tables are `orders` (`tbl_orders`), `customers`."),
        ({"table_name": "orders", "column_name": "email"}, "Its columns are `total` (`amt`), `placed_at`."),
    ],
)
def test_metadata_narrowing_errors_name_the_physical_names_they_accept(db_session_mock, kwargs, message):
    with pytest.raises(MCPUserError, match=re.escape(message)):
        _read_metadata(_contract(), _draft(document=_PHYSICAL_DOCUMENT), **kwargs)


# --- update_contract_metadata ---


def _saved(version_id, **fields):
    return SavedMetadata(
        version_id=version_id,
        unverifiable_rules=fields.get("unverifiable_rules", []),
        unresolved_declarations=fields.get("unresolved_declarations", []),
        untested_declarations=fields.get("untested_declarations", []),
        overridden_declarations=fields.get("overridden_declarations", []),
        problems=fields.get("problems", []),
    )


def _update(suite, current, *, saved=None, error=None, protected=False, **kwargs):
    landed = SuiteVersion(id=uuid4(), version=5)
    with (
        _patch_perms(),
        patch(f"{MODULE}.mcp_source_data_protected", return_value=protected),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch.object(SuiteVersion, "draft_for", return_value=current),
        patch.object(SuiteVersion, "get", return_value=landed),
        patch(
            f"{MODULE}.contract_service.save_metadata_document",
            return_value=saved or _saved(landed.id), side_effect=error,
        ) as save,
    ):
        return update_contract_metadata(test_suite_id=str(suite.id), **kwargs), save


def test_a_merge_patch_changes_one_field_and_keeps_every_other_section(db_session_mock):
    out, save = _update(_contract(), _draft(document=_WIDE_DOCUMENT), patch={"description": {"purpose": "Orders"}})

    document = save.call_args.args[1]
    assert document == {**_WIDE_DOCUMENT, "description": {"purpose": "Orders"}}
    assert "**Version:** v5 draft" in out


def test_a_merge_patch_after_a_rename_applies_to_the_contracts_name(db_session_mock):
    stored = {"name": "Old name", "status": "draft"}
    _, save = _update(_contract("Orders"), _draft(document=stored), patch={"status": "active"})

    assert save.call_args.args[1] == {"name": "Orders", "status": "active"}


def test_a_merge_patch_replaces_a_list_whole(db_session_mock):
    _, save = _update(_contract(), _draft(document=_WIDE_DOCUMENT), patch={"schema": [{"name": "orders"}]})

    assert save.call_args.args[1]["schema"] == [{"name": "orders"}]


def test_replace_mode_stores_the_patch_as_the_document(db_session_mock):
    replacement = {"name": "Orders", "schema": []}
    _, save = _update(_contract(), _draft(document=_WIDE_DOCUMENT), patch=replacement, mode="replace")

    assert save.call_args.args[1] == replacement


def test_a_checkable_rule_is_refused_with_its_path(db_session_mock):
    error = CheckableRuleError(["$.schema[0].quality[0]: orders: orders-rows is checked by the Row Count test type"])
    with pytest.raises(MCPUserError) as raised:
        _update(_contract(), _draft(document=_WIDE_DOCUMENT), patch={"name": "x"}, error=error)

    assert "No changes saved" in str(raised.value)
    assert "`create_test`" in str(raised.value)
    assert "$.schema[0].quality[0]" in str(raised.value)


def test_an_invalid_result_is_refused_with_its_path(db_session_mock):
    error = InvalidContractDocumentError(["$.status: 42 is not of type 'string'"])
    with pytest.raises(MCPUserError, match=r"\$\.status: 42"):
        _update(_contract(), _draft(document=_WIDE_DOCUMENT), patch={"status": 42}, error=error)


def test_the_response_lists_what_no_test_checks(db_session_mock):
    saved = _saved(
        uuid4(),
        unverifiable_rules=["orders.amount: amount-dupes"],
        untested_declarations=["orders.amount: Maximum Value"],
        unresolved_declarations=["orders.amount: logicalTypeOptions.exclusiveMinimum"],
        problems=["$.status: 42 is not of type 'string'"],
    )
    out, _ = _update(_contract(), _draft(document=_WIDE_DOCUMENT), patch={"name": "x"}, saved=saved)

    assert "## Stored as unverifiable (1)" in out
    assert "## Declarations with no test (1)" in out
    assert "## Declarations no test checks (1)" in out
    assert "## Problems the document already had (1)" in out


def test_an_unknown_mode_is_refused(db_session_mock):
    with pytest.raises(MCPUserError, match="Invalid mode `patch`"):
        _update(_contract(), _draft(), patch={}, mode="patch")


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_updating_metadata_without_edit_is_denied_before_the_contract_is_looked_up(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(memberships={"demo": "role_c"}, permission="edit", username="test_user")
    with (
        patch(f"{MODULE}.resolve_contract") as resolve,
        pytest.raises(MCPPermissionDenied),
    ):
        update_contract_metadata(test_suite_id=str(uuid4()), patch={"name": "x"})

    resolve.assert_not_called()


# --- diff_contract_versions ---

_EARLIER = datetime(2026, 9, 1, tzinfo=UTC)
_LATER = datetime(2026, 10, 1, tzinfo=UTC)


def _term(term_id, **fields):
    return TestDefinition(
        id=uuid4(), contract_term_id=term_id, test_type=fields.pop("test_type", "Required"),
        table_name=fields.pop("table_name", "orders"), column_name=fields.pop("column_name", "amount"),
        last_auto_gen_date=fields.pop("last_auto_gen_date", _EARLIER),
        last_manual_update=fields.pop("last_manual_update", None), **fields,
    )


def _diff(suite, source, target, before, after, **kwargs):
    terms = {source.id: {term.contract_term_id: term for term in before}, target.id: {term.contract_term_id: term for term in after}}
    with (
        _patch_perms(),
        patch(f"{MODULE}.resolve_contract", return_value=suite),
        patch(f"{MODULE}.resolve_contract_version", side_effect=lambda _suite, number: source if number == source.version else target),
        patch.object(SuiteVersion, "draft_for", return_value=target),
        patch.object(SuiteVersion, "is_active", return_value=True),
        patch(f"{MODULE}._terms_by_identity", side_effect=lambda version_id: terms[version_id]),
        patch(f"{MODULE}._test_type_labels", return_value={"Required": "Required Entry", "Max_Val": "Maximum Value"}),
        patch(f"{MODULE}.mcp_source_data_protected", return_value=kwargs.pop("protected", False)),
    ):
        return diff_contract_versions(test_suite_id=str(suite.id), from_version=source.version, **kwargs)


def test_a_diff_tells_a_regenerated_term_from_an_edited_one(db_session_mock):
    before = [
        _term("max-amount", test_type="Max_Val", baseline_value="100"),
        _term("amount-required", threshold_value="0"),
    ]
    after = [
        _term("max-amount", test_type="Max_Val", baseline_value="120", last_auto_gen_date=_LATER),
        _term("amount-required", threshold_value="5", last_manual_update=_LATER),
    ]
    out = _diff(_contract(), _frozen(3), _draft(4), before, after)

    assert "| Regenerated | max-amount | Maximum Value | orders | amount | baseline_value |" in out
    assert "| Edited | amount-required | Required Entry | orders | amount | threshold_value |" in out
    assert "**Regenerated:** 1" in out and "**Edited:** 1" in out


def test_a_term_whose_column_changed_reads_as_one_change(db_session_mock):
    out = _diff(
        _contract(), _frozen(3), _draft(4),
        [_term("amount-required")], [_term("amount-required", column_name="total", last_manual_update=_LATER)],
    )

    assert "**Edited:** 1" in out
    assert "**Added:**" not in out and "**Removed:**" not in out
    assert "| `column_name` | amount | total |" in out


def test_a_diff_lists_added_and_removed_terms(db_session_mock):
    out = _diff(_contract(), _frozen(3), _draft(4), [_term("gone")], [_term("new")])

    assert "**Added:** 1" in out and "**Removed:** 1" in out


def test_a_diff_pages_its_terms(db_session_mock):
    after = [_term(f"term-{index:02}", column_name=f"col_{index:02}") for index in range(5)]
    out = _diff(_contract(), _frozen(3), _draft(4), [], after, limit=2, page=2)

    assert "term-02" in out and "term-03" in out
    assert "term-00" not in out and "term-04" not in out
    assert "## Metadata document" not in out


def test_a_diff_lists_the_metadata_document_changes_by_path(db_session_mock):
    source = _frozen(3)
    source.metadata_document = {"name": "Orders", "schema": [{"name": "orders", "description": "Old"}, {"name": "gone"}]}
    target = _draft(4, document={"name": "Orders", "team": {"name": "Data"}, "schema": [{"name": "orders", "description": "New"}]})

    out = _diff(_contract(), source, target, [], [])

    assert "| `$.schema[orders].description` | Changed |" in out
    assert "| `$.schema[gone]` | Removed |" in out
    assert "| `$.team` | Added |" in out


def test_a_diff_hides_calibration_values_under_protection(db_session_mock):
    out = _diff(
        _contract(), _frozen(3), _draft(4),
        [_term("max-amount", test_type="Max_Val", baseline_value="100")],
        [_term("max-amount", test_type="Max_Val", baseline_value="120", last_auto_gen_date=_LATER)],
        protected=True,
    )

    assert "120" not in out
    assert "**Omitted Fields:** baseline_value" in out


def test_a_diff_of_a_version_with_itself_is_refused(db_session_mock):
    version = _frozen(3)
    with pytest.raises(MCPUserError, match="both v3"):
        _diff(_contract(), version, version, [], [], to_version=3)


_PLACEHOLDER = re.compile(r"<hidden:[0-9a-f]{16}\.[0-9a-f]{16}>")


@pytest.fixture(autouse=True)
def _placeholder_key():
    with patch(f"{MODULE}.get_jwt_signing_key", return_value=b"k" * 32):
        yield


_PROTECTED_DOCUMENT = {
    "schema": [{
        "name": "orders",
        "quality": [
            {"type": "text", "description": "Few late", "mustBeLessThan": 5},
            {"type": "text", "description": "Some rows", "mustBeGreaterThan": 0},
        ],
        "properties": [
            {"name": "amount", "description": "Old", "logicalTypeOptions": {"maximum": 500, "multipleOf": 1}, "examples": [12.5]},
            {"name": "status", "enum": ["open"]},
        ],
    }],
}


def _protected_write(edit, document=_PROTECTED_DOCUMENT):
    read_back = _with_placeholders(document)
    edit(read_back["schema"][0])
    _, save = _update(_contract(), _draft(document=document), patch={"schema": read_back["schema"]}, protected=True)
    return save.call_args.args[1]["schema"][0]


def test_under_protection_a_write_built_from_a_read_keeps_the_hidden_values(db_session_mock):
    table = _protected_write(lambda table: table["properties"][0].update(description="New"))

    expected = copy.deepcopy(_PROTECTED_DOCUMENT["schema"][0])
    expected["properties"][0]["description"] = "New"
    assert table == expected


def test_under_protection_hidden_values_follow_reordered_removed_and_edited_rules(db_session_mock):
    def edit(table):
        late, rows = table["quality"]
        late["description"] = "Very few late"
        table["quality"] = [{"type": "text", "description": "New"}, rows, late]

    table = _protected_write(edit)

    assert table["quality"] == [
        {"type": "text", "description": "New"},
        {"type": "text", "description": "Some rows", "mustBeGreaterThan": 0},
        {"type": "text", "description": "Very few late", "mustBeLessThan": 5},
    ]


def test_under_protection_each_read_gives_new_placeholders_that_all_resolve(db_session_mock):
    first, second = _with_placeholders(_PROTECTED_DOCUMENT), _with_placeholders(_PROTECTED_DOCUMENT)
    assert first["schema"][0]["properties"][1]["enum"] != second["schema"][0]["properties"][1]["enum"]

    second["schema"][0]["properties"][1]["enum"] = first["schema"][0]["properties"][1]["enum"]
    _, save = _update(_contract(), _draft(document=_PROTECTED_DOCUMENT), patch={"schema": second["schema"]}, protected=True)

    assert save.call_args.args[1]["schema"] == _PROTECTED_DOCUMENT["schema"]


def test_under_protection_a_renamed_column_keeps_its_hidden_values(db_session_mock):
    table = _protected_write(lambda table: table["properties"][0].update(name="order_amount"))

    assert table["properties"][0] == {**_PROTECTED_DOCUMENT["schema"][0]["properties"][0], "name": "order_amount"}


def test_under_protection_a_placeholder_left_out_removes_its_value(db_session_mock):
    def edit(table):
        del table["properties"][1]["enum"]
        late = table["quality"][0]
        late["mustBeGreaterThan"] = 1
        del late["mustBeLessThan"]

    table = _protected_write(edit)

    assert table["properties"][1] == {"name": "status"}
    assert table["quality"][0] == {"type": "text", "description": "Few late", "mustBeGreaterThan": 1}


def _refused_protected_write(edit):
    read_back = _with_placeholders(_PROTECTED_DOCUMENT)
    edit(read_back["schema"][0])
    with patch(f"{MODULE}.contract_service.save_metadata_document") as save, pytest.raises(MCPUserError) as raised:
        _update(_contract(), _draft(document=_PROTECTED_DOCUMENT), patch={"schema": read_back["schema"]}, protected=True)
    save.assert_not_called()
    return str(raised.value)


def test_under_protection_a_placeholder_moved_where_reads_show_it_is_refused(db_session_mock):
    def edit(table):
        table["properties"][1]["description"] = f"Values: {table['properties'][1]['enum']}"

    message = _refused_protected_write(edit)

    assert "`$.schema[0].properties[1].description`" in message
    assert "open" not in message


def test_under_protection_a_placeholder_nested_inside_a_hidden_field_is_refused(db_session_mock):
    def edit(table):
        table["properties"][0]["examples"] = [table["properties"][1]["enum"]]

    assert "`$.schema[0].properties[0].examples[0]`" in _refused_protected_write(edit)


def test_a_placeholder_for_a_value_the_contract_no_longer_holds_is_refused(db_session_mock):
    def edit(table):
        table["properties"][1]["enum"] = "<hidden:0123456789abcdef.0123456789abcdef>"

    message = _refused_protected_write(edit)

    assert "`$.schema[0].properties[1].enum`" in message
    assert "get_contract_metadata" in message


def test_under_protection_the_document_changes_name_a_hidden_field_and_nothing_inside_it(db_session_mock):
    def column(examples):
        return {"name": "orders", "properties": [{"name": "amount", "examples": examples}]}

    source = _frozen(3)
    source.metadata_document = {"schema": [column([{"name": "Jane Doe", "ssn": "123"}, {"name": "John Roe"}])]}
    target = _draft(4, document={"schema": [column([{"name": "Jane Doe", "ssn": "999"}])]})

    out = _diff(_contract(), source, target, [], [], protected=True)

    assert "| `$.schema[orders].properties[amount].examples` | Changed |" in out
    assert "Jane" not in out and "John" not in out


def test_under_protection_an_unchanged_hidden_value_is_not_a_document_change(db_session_mock):
    document = {"schema": [{"name": "orders", "properties": [{"name": "amount", "examples": [12.5]}]}]}
    source = _frozen(3)
    source.metadata_document = copy.deepcopy(document)

    out = _diff(_contract(), source, _draft(4, document=document), [], [], protected=True)

    assert "## Metadata document\n\nNo change." in out


def test_a_merge_patch_is_not_refused_for_placeholder_text_the_stored_document_already_holds(db_session_mock):
    stored = {"name": "Orders", "description": {"usage": "Copied <hidden:0123456789abcdef.0123456789abcdef> from a read"}}
    _, save = _update(_contract(), _draft(document=stored), patch={"name": "Orders v2"}, protected=True)

    assert save.call_args.args[1] == {**stored, "name": "Orders v2"}


def test_under_protection_a_rules_recorded_baselines_are_hidden(db_session_mock):
    rule = {
        "metric": "rowCount",
        "mustBeBetween": [90, 110],
        "customProperties": [
            {"property": "testType", "value": "Row_Ct_Pct", "vendor": "testgen"},
            {"property": "baselineCount", "value": 100, "vendor": "testgen"},
            {"property": "thresholdPercent", "value": 10, "vendor": "testgen"},
        ],
    }

    properties = _with_placeholders({"quality": [rule]})["quality"][0]["customProperties"]

    assert properties[0]["value"] == "Row_Ct_Pct"
    assert all(_PLACEHOLDER.fullmatch(entry["value"]) for entry in properties[1:])


def test_a_write_without_placeholders_does_not_need_the_signing_key(db_session_mock):
    with patch(f"{MODULE}.get_jwt_signing_key", side_effect=AttributeError("no signing key configured")):
        _, save = _update(_contract(), _draft(document=_PROTECTED_DOCUMENT), patch={"name": "Orders v2"})

    assert save.call_args.args[1]["name"] == "Orders v2"


def test_without_protection_a_write_replaces_what_it_sends(db_session_mock):
    sent = copy.deepcopy(_PROTECTED_DOCUMENT["schema"])
    del sent[0]["properties"][0]["examples"]
    _, save = _update(_contract(), _draft(document=_PROTECTED_DOCUMENT), patch={"schema": sent})

    assert save.call_args.args[1]["schema"] == sent


def test_under_protection_validation_problems_name_only_the_path(db_session_mock):
    error = InvalidContractDocumentError(["$.schema[0].properties[0].examples: '123-45-6789' is not of type 'array'"])
    with pytest.raises(MCPUserError) as raised:
        _update(_contract(), _draft(document=_WIDE_DOCUMENT), patch={"name": "x"}, error=error, protected=True)

    assert "123-45-6789" not in str(raised.value)
    assert "$.schema[0].properties[0].examples: does not match the ODCS schema." in str(raised.value)


def test_the_update_lists_what_changed_by_path(db_session_mock):
    landed = SuiteVersion(id=uuid4(), version=5, metadata_document={**_WIDE_DOCUMENT, "description": {"purpose": "x"}, "schema": []})
    with (
        _patch_perms(),
        patch(f"{MODULE}.mcp_source_data_protected", return_value=False),
        patch(f"{MODULE}.resolve_contract", return_value=_contract()),
        patch.object(SuiteVersion, "draft_for", return_value=_draft(document=_WIDE_DOCUMENT)),
        patch.object(SuiteVersion, "get", return_value=landed),
        patch(f"{MODULE}.contract_service.save_metadata_document", return_value=_saved(landed.id)),
    ):
        out = update_contract_metadata(test_suite_id=str(uuid4()), patch={})

    assert "## Changes" in out
    assert "| `$.description` | Added |" in out
    assert "| `$.schema[orders]` | Removed |" in out


def test_freezing_under_protection_names_only_the_path_of_each_problem(db_session_mock):
    error = InvalidContractDocumentError(["$.schema[0].properties[0].examples: '123-45-6789' is not of type 'array'"])
    with (
        patch(f"{MODULE}.mcp_source_data_protected", return_value=True),
        pytest.raises(MCPUserError) as raised,
    ):
        _freeze(_contract(), error=error)

    assert "123-45-6789" not in str(raised.value)
    assert "$.schema[0].properties[0].examples: does not match the ODCS schema." in str(raised.value)


def test_a_diff_page_past_the_last_says_so(db_session_mock):
    after = [_term(f"term-{index}", column_name=f"col_{index}") for index in range(3)]
    out = _diff(_contract(), _frozen(3), _draft(4), [], after, limit=2, page=5)

    assert "No tests on page 5 (total: 3)." in out
    assert "## Tests" not in out


def test_values_a_column_stores_alike_are_not_a_change(db_session_mock):
    out = _diff(
        _contract(), _frozen(3), _draft(4),
        [_term("amount-required", window_days=None, history_lookback=None, test_description="")],
        [_term("amount-required", window_days=0, history_lookback=0, test_description=None)],
    )

    assert "No test changed." in out
