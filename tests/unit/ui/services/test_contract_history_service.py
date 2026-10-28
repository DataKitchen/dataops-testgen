from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.contract_comparison import TermChange, TermChangeKind
from testgen.common.contract_service import ExportedDocument
from testgen.common.enums import JobStatus
from testgen.common.models.suite_version import SuiteVersion, SuiteVersionListItem
from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.common.models.test_suite import TestSuite
from testgen.ui.services import contract_history_service as service

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
LATEST_RUN = datetime(2026, 10, 11, 16, 20, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _item(version: int, frozen: bool, **overrides) -> SuiteVersionListItem:
    fields = {
        "id": uuid4(), "version": version, "label": None, "created_by": None,
        "frozen_at": FROZEN if frozen else None, "frozen_by": "alice" if frozen else None,
        "term_count": 150, "run_count": 0, "latest_run_id": None, "latest_run_status": None,
        "latest_run_started_at": None,
    }
    fields.update(overrides)
    return SuiteVersionListItem(**fields)


def _suite() -> TestSuite:
    return TestSuite(id=uuid4(), test_suite="orders_contract")


def _history(items, term_counts=None):
    counts = term_counts or {}
    with (
        patch.object(service.SuiteVersion, "list_for_suite", return_value=(items, len(items))),
        patch.object(service.contract_service, "term_count", side_effect=lambda version_id: counts.get(version_id, 147)),
    ):
        return service.version_history(_suite())


def test_the_history_lists_every_version_newest_first_with_its_state():
    history = _history([_item(4, False), _item(3, True, label="Q3 agreement"), _item(2, True), _item(1, True)])

    assert history["contract"] == "orders_contract"
    assert [(v["version"], v["state"], v["caption"]) for v in history["versions"]] == [
        (4, "draft", "Draft"),
        (3, "active", "Active · Q3 agreement"),
        (2, "superseded", "Superseded"),
        (1, "superseded", "Superseded"),
    ]
    assert history["options"] == [
        {"value": 4, "label": "v4 draft"},
        {"value": 3, "label": "v3 active"},
        {"value": 2, "label": "v2 superseded"},
        {"value": 1, "label": "v1 superseded"},
    ]


def test_a_draft_shows_its_state_terms_and_runs():
    run_id = uuid4()
    draft = _item(4, False, run_count=2, latest_run_id=run_id, latest_run_status=JobStatus.ERROR, latest_run_started_at=LATEST_RUN)
    history = _history([draft, _item(3, True)], term_counts={draft.id: 147})

    assert history["versions"][0]["detail"] == {
        "title": "Version 4",
        "state": "Draft",
        "terms": 147,
        "runs": {"count": 2, "latest_run_id": str(run_id), "latest_started_at": _ms(LATEST_RUN), "latest_status": "Error"},
        "label": None,
        "frozen_by": None,
        "frozen_at": None,
        "frozen": False,
        "comparison": {"source": 3, "target": 4},
    }


def test_a_frozen_version_shows_its_label_and_who_froze_it_and_when():
    detail = _history([_item(3, True, label="Q3 agreement")])["versions"][0]["detail"]

    assert detail["frozen"] is True
    assert detail["label"] == "Q3 agreement"
    assert detail["frozen_by"] == "alice"
    assert detail["frozen_at"] == _ms(FROZEN)


def test_a_version_without_runs_has_no_latest_run():
    runs = _history([_item(3, True)])["versions"][0]["detail"]["runs"]

    assert runs == {"count": 0, "latest_run_id": None, "latest_started_at": None, "latest_status": None}


def _comparisons(history) -> dict[int, dict | None]:
    return {v["version"]: v["detail"]["comparison"] for v in history["versions"]}


def test_the_newest_version_compares_the_active_version_against_the_draft():
    history = _history([_item(4, False), _item(3, True), _item(2, True)])

    assert _comparisons(history)[4] == {"source": 3, "target": 4}
    assert history["compare_disabled_reason"] is None


def test_without_a_draft_the_newest_version_compares_the_two_newest_versions():
    assert _comparisons(_history([_item(3, True), _item(2, True)]))[3] == {"source": 2, "target": 3}


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([_item(4, False), _item(3, True), _item(2, True)], {3: {"source": 3, "target": 4}, 2: {"source": 2, "target": 4}}),
        ([_item(3, True), _item(2, True), _item(1, True)], {2: {"source": 2, "target": 3}, 1: {"source": 1, "target": 3}}),
    ],
    ids=["with-draft", "without-draft"],
)
def test_an_older_version_compares_itself_against_the_newest_version(items, expected):
    comparisons = _comparisons(_history(items))

    assert {number: comparisons[number] for number in expected} == expected


def test_a_contract_with_one_version_has_nothing_to_compare():
    history = _history([_item(1, False)])

    assert _comparisons(history) == {1: None}
    assert history["compare_disabled_reason"] == "There is only one version."


def _version(versions: dict[int, SuiteVersion], number: int) -> SuiteVersion:
    if number not in versions:
        raise ValueError(f"This contract has no version {number}.")
    return versions[number]


def _compare(source, target, documents):
    suite = _suite()
    versions = {
        4: SuiteVersion(id=uuid4(), version=4, frozen_at=None),
        3: SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN),
    }
    with (
        patch.object(service.contract_service, "version_for_export", side_effect=lambda _, number: _version(versions, number)),
        patch.object(service.contract_service, "export_version", side_effect=documents) as export_version,
        patch.object(service.SuiteVersion, "in_force_for", return_value=versions[3]),
    ):
        result = service.version_comparison(suite, source, target)
    assert {call.kwargs["contract_name"] for call in export_version.call_args_list} == {suite.test_suite}
    return result


def test_a_comparison_carries_both_documents_named_by_version():
    result = _compare(3, 4, [ExportedDocument("a: 1\n", []), ExportedDocument("a: 2\n", [])])

    assert result == {
        "source": 3,
        "target": 4,
        "source_label": "v3 active",
        "target_label": "v4 draft",
        "source_document": "a: 1\n",
        "target_document": "a: 2\n",
        "error": None,
    }


def test_a_version_that_cannot_be_rendered_is_reported():
    result = _compare(3, 4, [ExportedDocument("a: 1\n", []), ValueError("Term 12 names an undeclared column.")])

    assert result["error"] == "v4 draft could not be rendered. Term 12 names an undeclared column."
    assert result["source_document"] is None
    assert result["target_document"] is None


def test_a_version_that_no_longer_exists_is_reported():
    result = _compare(3, 5, [ExportedDocument("a: 1\n", [])])

    assert result["error"] == "This contract has no version 5."
    assert result["target_label"] == "v5"
    assert result["source_document"] is None
    assert result["target_document"] is None


# --- Changes: quality rules ---

EARLIER = datetime(2026, 9, 1, tzinfo=UTC)


def _term(term_id, **fields):
    return TestDefinition(
        id=uuid4(), contract_term_id=term_id, test_type=fields.pop("test_type", "Max_Val"),
        table_name=fields.pop("table_name", "orders"), column_name=fields.pop("column_name", "amount"),
        last_auto_gen_date=EARLIER, **fields,
    )


_TEST_TYPES = {
    "Max_Val": TestType(
        test_type="Max_Val", test_name_short="Maximum Value",
        default_parm_columns="baseline_value,threshold_value", default_parm_prompts="Baseline Value,Threshold",
    ),
    "Required": TestType(test_type="Required", test_name_short="Required Entry", default_parm_columns=""),
}


def _rules(changes, pii=frozenset(), limit=None):
    with (
        patch.object(service.contract_comparison, "term_changes", return_value=changes),
        patch.object(service, "_test_types", side_effect=lambda codes: {c: _TEST_TYPES[c] for c in codes}),
        patch.object(service, "IMPORT_PREVIEW_ROW_LIMIT", limit or 500),
    ):
        return service.rule_changes(uuid4(), uuid4(), pii_columns=pii)


def _change(kind, before=None, after=None, fields=()):
    return TermChange(kind, before, after, list(fields))


def test_rule_rows_list_removals_then_changes_then_additions():
    rules = _rules([
        _change(TermChangeKind.ADDED, after=_term("a", column_name="a")),
        _change(TermChangeKind.EDITED, _term("e", column_name="b"), _term("e", column_name="b", severity="Warning"), ["severity"]),
        _change(TermChangeKind.REMOVED, before=_term("r", column_name="c")),
        _change(TermChangeKind.REGENERATED, _term("g", column_name="d"), _term("g", column_name="d"), []),
    ])

    assert [(row["change"], row["column"]) for row in rules["rows"]] == [
        ("Removed", "c"), ("Edited", "b"), ("Regenerated", "d"), ("Added", "a"),
    ]


def test_a_changed_rule_shows_each_field_before_and_after():
    [row] = _rules([_change(
        TermChangeKind.EDITED,
        _term("m", baseline_value="10000", test_active=True),
        _term("m", baseline_value="25000", test_active=False),
        ["test_active", "baseline_value"],
    )])["rows"]

    assert (row["table"], row["column"], row["test_type"]) == ("orders", "amount", "Maximum Value")
    assert row["fields"] == [
        {"label": "Active", "before": "Yes", "after": "No"},
        {"label": "Baseline Value", "before": "10000", "after": "25000"},
    ]


def test_the_summary_leaves_out_zero_counts():
    edited = _change(TermChangeKind.EDITED, _term("e"), _term("e"), [])
    rules = _rules([_change(TermChangeKind.ADDED, after=_term("a")), edited, edited])

    assert rules["summary"] == "1 added · 2 changed"
    assert rules["empty_state"] is None


def test_with_no_rule_changes_the_empty_state_shows():
    rules = _rules([])

    assert rules["summary"] is None
    assert rules["empty_state"] == "No quality rules changed."
    assert rules["rows"] == []


def test_a_field_the_test_type_does_not_prompt_for_still_gets_a_label():
    [row] = _rules([_change(
        TermChangeKind.EDITED,
        _term("m", test_type="Max_Val", window_days=None),
        _term("m", test_type="Required", window_days=7),
        ["test_type", "window_days"],
    )])["rows"]

    assert row["test_type"] == "Required Entry"
    assert row["fields"] == [
        {"label": "Test Type", "before": "Maximum Value", "after": "Required Entry"},
        {"label": "Window days", "before": "—", "after": "7"},
    ]


def test_a_rule_on_a_pii_column_shows_its_calibration_fields_redacted():
    [row] = _rules(
        [_change(
            TermChangeKind.REGENERATED,
            _term("m", baseline_value="1", severity="Fail"),
            _term("m", baseline_value="2", severity="Warning"),
            ["severity", "baseline_value"],
        )],
        pii={("orders", "amount")},
    )["rows"]

    assert row["fields"] == [
        {"label": "Severity", "before": "Fail", "after": "Warning"},
        {"label": "Baseline Value", "before": "[PII Redacted]", "after": "[PII Redacted]"},
    ]


def test_a_rule_on_another_column_shows_its_calibration_values():
    [row] = _rules(
        [_change(TermChangeKind.EDITED, _term("m", baseline_value="1"), _term("m", baseline_value="2"), ["baseline_value"])],
        pii={("orders", "email")},
    )["rows"]

    assert row["fields"] == [{"label": "Baseline Value", "before": "1", "after": "2"}]


def test_rule_rows_are_capped_at_the_preview_limit():
    rules = _rules([_change(TermChangeKind.ADDED, after=_term(f"a{i}")) for i in range(3)], limit=2)

    assert len(rules["rows"]) == 2
    assert (rules["total_rows"], rules["truncated"]) == (3, True)
    assert rules["summary"] == "3 added"


# --- Changes: metadata ---


def _metadata(before, after, pii=frozenset()):
    source = SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN, metadata_document=before)
    target = SuiteVersion(id=uuid4(), version=4, frozen_at=None, metadata_document=after)
    return service.metadata_changes(source, target, _suite(), pii_columns=pii)


def _rows(metadata):
    return [(row["section"], row["field"], row["before"], row["after"]) for row in metadata["rows"]]


def test_metadata_rows_are_grouped_under_section_names():
    before = {
        "description": {"purpose": "Orders"},
        "team": {"members": [{"username": "ana@acme.com"}]},
        "schema": [{"name": "orders", "properties": [{"name": "ship_date", "criticalDataElement": False}]}],
        "slaProperties": [{"property": "latency", "value": 6}],
    }
    after = {
        "description": {"purpose": "Orders", "limitations": "Excludes marketplace orders"},
        "team": {"members": [{"username": "ana@acme.com"}, {"username": "li@acme.com", "role": "steward"}]},
        "schema": [{"name": "orders", "properties": [{"name": "ship_date", "criticalDataElement": True}]}],
        "slaProperties": [{"property": "latency", "value": 4}],
    }

    metadata = _metadata(before, after)

    assert _rows(metadata) == [
        ("Overview", "Description · Limitations", "—", "Excludes marketplace orders"),
        ("Schema", "orders.ship_date · Critical data element", "No", "Yes"),
        ("Team", "li@acme.com", "—", "Added"),
        ("Service Levels", "latency · Value", "6", "4"),
    ]
    assert metadata["summary"] == "4 changed"
    assert metadata["empty_state"] is None


def test_metadata_rows_are_ordered_by_section():
    before = {"domain": "sales", "price": {"priceAmount": 5}, "support": [{"channel": "#orders"}], "tenant": "emea"}
    after = {"domain": "commerce", "price": {"priceAmount": 6}, "team": {"name": "Data"}, "tags": ["a"]}

    assert [(row["section"], row["field"]) for row in _metadata(before, after)["rows"]] == [
        ("Overview", "Domain"),
        ("Overview", "Tenant"),
        ("Overview", "Tags"),
        ("Team", "Team"),
        ("Support", "Support"),
        ("Other", "Price · Price amount"),
    ]


def test_a_removed_section_and_an_unmodeled_one_read_as_such():
    assert _rows(_metadata({"support": [{"channel": "#orders"}]}, {"price": {"priceAmount": 5}})) == [
        ("Support", "Support", "Removed", "—"),
        ("Other", "Price", "—", "Added"),
    ]


def test_a_list_changed_whole_shows_both_sides():
    assert _rows(_metadata({"tags": ["a"]}, {"tags": ["a", "b"]})) == [("Overview", "Tags", '["a"]', '["a", "b"]')]


def _column(examples=None):
    column = {"name": "amount"}
    if examples is not None:
        column["examples"] = examples
    return {"schema": [{"name": "orders", "properties": [column]}]}


def test_an_added_pii_column_with_examples_reads_added_only():
    before = {"schema": [{"name": "orders", "properties": []}]}

    rows = _rows(_metadata(before, _column(["Jane Doe"]), pii={("orders", "amount")}))

    assert rows == [("Schema", "orders.amount", "—", "Added")]


def test_a_changed_example_of_a_pii_column_reads_redacted():
    rows = _rows(_metadata(_column(["Jane Doe"]), _column(["John Roe"]), pii={("orders", "amount")}))

    assert rows == [("Schema", "orders.amount · Examples", "[PII Redacted]", "[PII Redacted]")]


def test_a_changed_example_of_another_column_shows_both_values():
    rows = _rows(_metadata(_column(["Jane Doe"]), _column(["John Roe"]), pii={("orders", "email")}))

    assert rows == [("Schema", "orders.amount · Examples", '["Jane Doe"]', '["John Roe"]')]


def test_with_no_metadata_changes_the_empty_state_shows():
    metadata = _metadata({"status": "active", "domain": "sales"}, {"status": "draft", "domain": "sales"})

    assert (metadata["rows"], metadata["summary"], metadata["empty_state"]) == ([], None, "No metadata changed.")


# --- Changes: the pair ---


def _version_changes(source, target, mask_pii=False, missing=()):
    versions = {
        4: SuiteVersion(id=uuid4(), version=4, frozen_at=None, metadata_document={"domain": "sales"}),
        3: SuiteVersion(id=uuid4(), version=3, frozen_at=FROZEN, metadata_document={"domain": "retail"}),
    }

    def resolve(_suite, number):
        if number in missing:
            raise ValueError(f"This contract has no version {number}.")
        return versions[number]

    with (
        patch.object(service.contract_service, "version_for_export", side_effect=resolve),
        patch.object(service, "rule_changes", return_value={"rows": []}) as rules,
        patch.object(service, "metadata_changes", return_value={"rows": []}) as metadata,
        patch.object(service.contract_comparison, "pii_columns", return_value={("orders", "email")}) as pii,
    ):
        result = service.version_changes(_suite(), source, target, mask_pii=mask_pii)
    return result, rules, metadata, versions, pii


def test_version_changes_compares_the_two_versions_it_names():
    result, rules, metadata, versions, pii = _version_changes(3, 4, mask_pii=True)

    assert (result["source"], result["target"], result["error"]) == (3, 4, None)
    pii.assert_called_once()
    assert pii.call_args.args[1:] == (versions[3], versions[4])
    rules.assert_called_once_with(versions[3].id, versions[4].id, pii_columns={("orders", "email")})
    assert metadata.call_args.args[:2] == (versions[3], versions[4])
    assert metadata.call_args.kwargs == {"pii_columns": {("orders", "email")}}


def test_version_changes_without_masking_redacts_nothing():
    _, rules, metadata, _, pii = _version_changes(3, 4, mask_pii=False)

    pii.assert_not_called()
    assert rules.call_args.kwargs == {"pii_columns": frozenset()}
    assert metadata.call_args.kwargs == {"pii_columns": frozenset()}


def test_version_changes_of_a_version_with_itself_shows_both_empty_states():
    with patch.object(service.contract_service, "version_for_export", return_value=SuiteVersion(
        id=uuid4(), version=3, frozen_at=FROZEN, metadata_document={"domain": "sales"},
    )), patch.object(service.contract_comparison, "term_changes", return_value=[]):
        result = service.version_changes(_suite(), 3, 3, mask_pii=False)

    assert result["error"] is None
    assert result["rules"]["empty_state"] == "No quality rules changed."
    assert result["metadata"]["empty_state"] == "No metadata changed."


def test_version_changes_reports_an_unknown_version_as_an_error():
    result, rules, _, _, _ = _version_changes(3, 9, missing=(9,))

    assert result["error"] == "This contract has no version 9."
    assert (result["rules"], result["metadata"]) == (None, None)
    rules.assert_not_called()
