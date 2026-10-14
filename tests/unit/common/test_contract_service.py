from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import yaml
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from testgen.commands.test_generation import ContractGenerationResult
from testgen.common import contract_document, contract_service
from testgen.common.data_catalog_service import TAG_FIELDS
from testgen.common.enums import SuiteType
from testgen.common.flavors import SqlFlavorCode
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition
from testgen.common.odcs import render, serialize
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND, CustomServerReason, ServerBlock, ServerType
from testgen.common.odcs.validation import validate_document
from tests.unit.sql_assertions import equality_conjunct

pytestmark = pytest.mark.unit

# A merged document carrying only the ODCS root's own required keys (``version``,
# ``apiVersion``, ``kind``, ``id``) -- everything else at the root is optional, so this is
# already a valid document on its own.
_VALID_MERGED_DOCUMENT = {
    "version": "1.0.0", "apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND, "id": "orders-contract",
}


def _column(**fields):
    """A catalog column carrying no description, flag or tags unless the test sets them."""
    return MagicMock(**{
        "description": None, "critical_data_element": None, "pii_flag": None, "excluded_data_element": None,
        **dict.fromkeys(TAG_FIELDS), **fields,
    })


@contextmanager
def _generation_stubs(columns=()):
    """Patch ``run_contract_generation`` with a stand-in that runs only the document merge
    (``contract_document.refresh_tables``) on the draft ``SuiteVersion.get`` returns, reading
    ``columns`` from an in-memory catalog with no catalog table entry. Yields the patched mock."""
    table_group = MagicMock(id=uuid4(), description=None, data_location=None, **dict.fromkeys(TAG_FIELDS))

    def stand_in(_suite_id, table_names, **_kwargs):
        draft = SuiteVersion.get(None)
        document = draft.metadata_document if draft.metadata_document is not None else {}
        counts = contract_document.refresh_tables(document, table_group, table_names)
        draft.metadata_document = document
        return ContractGenerationResult(
            term_count=0, tables_declared=table_names,
            tables_not_in_catalog=[name for name in table_names if not counts[name]],
            tables_not_profiled=table_names,
        )

    with (
        patch.object(contract_document, "catalog_columns", return_value=list(columns)),
        patch.object(contract_document, "_catalog_table", return_value=None),
        patch.object(contract_service, "run_contract_generation", side_effect=stand_in) as generate,
    ):
        yield generate


def _suite():
    suite = MagicMock()
    suite.id = uuid4()
    suite.suite_type = SuiteType.CONTRACT
    return suite


def test_an_existing_draft_receives_the_write_and_nothing_is_copied():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    with patch.object(SuiteVersion, "draft_for", return_value=draft):
        version_id, id_map = contract_service.resolve_write_target(suite)

    assert version_id == draft.id
    assert id_map == {}


def test_freezing_sets_the_freeze_time():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(contract_service.render, "render_document", return_value=_VALID_MERGED_DOCUMENT),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        frozen = contract_service.freeze_version(suite, label="first")

    assert frozen.frozen_at is not None
    assert frozen.label == "first"


def test_freezing_stores_the_rendered_bytes():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(contract_service.render, "render_document", return_value=_VALID_MERGED_DOCUMENT),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        frozen = contract_service.freeze_version(suite)

    assert frozen.frozen_document
    assert yaml.safe_load(frozen.frozen_document)["kind"] == ODCS_KIND


def test_freezing_records_the_api_version_the_bytes_were_validated_against():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, odcs_api_version=None)
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(contract_service.render, "render_document", return_value=_VALID_MERGED_DOCUMENT),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        frozen = contract_service.freeze_version(suite)

    assert frozen.odcs_api_version == ODCS_API_VERSION


def test_freezing_without_a_label_leaves_the_drafts_label_untouched():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, label="carried over")
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(contract_service.render, "render_document", return_value=_VALID_MERGED_DOCUMENT),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        frozen = contract_service.freeze_version(suite)

    assert frozen.label == "carried over"


def test_freezing_does_not_touch_the_drafts_author():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, created_by="original-author")
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(contract_service.render, "render_document", return_value=_VALID_MERGED_DOCUMENT),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        frozen = contract_service.freeze_version(suite, label="first")

    assert frozen.created_by == "original-author"


def test_freezing_without_a_draft_is_refused():
    suite = _suite()
    with patch.object(SuiteVersion, "draft_for", return_value=None):
        with pytest.raises(ValueError, match="no draft"):
            contract_service.freeze_version(suite)


def test_an_invalid_merge_blocks_the_freeze_and_leaves_the_draft_a_draft():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    invalid_document = {"version": "1.0.0", "apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND}  # no id
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(contract_service.render, "render_document", return_value=invalid_document),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        with pytest.raises(contract_service.InvalidContractDocumentError):
            contract_service.freeze_version(suite)

    assert draft.frozen_at is None
    assert draft.frozen_document is None


def test_the_validators_own_messages_reach_the_caller():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    invalid_document = {"version": "1.0.0", "apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND}  # no id
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(contract_service.render, "render_document", return_value=invalid_document),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        with pytest.raises(contract_service.InvalidContractDocumentError) as excinfo:
            contract_service.freeze_version(suite)

    assert excinfo.value.problems == validate_document(invalid_document)


def test_freezing_a_document_declaring_an_unbundled_api_version_is_refused_not_crashed():
    """The standard allows eight api versions and we bundle those from v3.1.0 on, so a document may legally
    declare a version we have no schema for. That is a document we cannot check, and the
    caller is documented to receive InvalidContractDocumentError for exactly that."""
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    document = {"version": "1.0.0", "apiVersion": "v3.0.2", "kind": ODCS_KIND, "id": "c1"}
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(contract_service.render, "render_document", return_value=document),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        with pytest.raises(contract_service.InvalidContractDocumentError) as excinfo:
            contract_service.freeze_version(suite)

    assert any("v3.0.2" in problem for problem in excinfo.value.problems)


def test_exporting_checks_the_document_against_the_version_it_declares():
    """``odcs_api_version`` on the row and ``apiVersion`` in the text are two answers to one
    question. Checking the text against the row's answer reports clean on a document whose own
    declaration was never checked."""
    suite = _suite()
    version = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=1, odcs_api_version=ODCS_API_VERSION,
        frozen_document=f"apiVersion: v3.0.2\nkind: {ODCS_KIND}\nid: c1\nversion: '1.0.0'\n",
    )

    exported = contract_service.export_version(version)

    assert any("v3.0.2" in problem for problem in exported.problems)


def test_discarding_without_a_draft_is_refused():
    suite = _suite()
    with patch.object(SuiteVersion, "draft_for", return_value=None):
        with pytest.raises(ValueError, match="no draft"):
            contract_service.discard_draft(suite)


def test_discarding_deletes_the_draft_row():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    frozen = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=1, frozen_at=datetime.now(UTC))
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch("testgen.common.contract_service._active_version", return_value=frozen),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
    ):
        contract_service.discard_draft(suite)

    session.delete.assert_called_once_with(draft)


def test_discarding_returns_the_number_of_terms_removed():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    frozen = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=1, frozen_at=datetime.now(UTC))
    session = MagicMock()
    session.scalar.return_value = 3
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch("testgen.common.contract_service._active_version", return_value=frozen),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
    ):
        term_count = contract_service.discard_draft(suite)

    statement = session.scalar.call_args.args[0]
    conjuncts = _conjuncts(statement.whereclause)
    assert any(equality_conjunct(term, "version_id", "test_definitions", draft.id) for term in conjuncts)
    assert any(
        getattr(term.left, "key", None) == "test_type" and term.operator is operators.not_in_op
        for term in conjuncts
    )
    assert term_count == 3


def test_discarding_the_contracts_only_version_is_refused():
    """With no frozen version behind it, discarding the draft would leave the contract with
    zero suite_versions rows, and both resolvers fall through to the shared placeholder."""
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=1)
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch("testgen.common.contract_service._active_version", return_value=None),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
    ):
        with pytest.raises(ValueError, match="no frozen version"):
            contract_service.discard_draft(suite)

    session.delete.assert_not_called()


def test_save_metadata_document_writes_to_the_resolved_version_and_returns_its_id():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    document = {"schema": [{"name": "orders"}]}
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch("testgen.common.contract_service.reconcile_contract_conformance"),
        patch.object(TestDefinition, "assign_missing_term_ids"),
    ):
        version_id = contract_service.save_metadata_document(suite, document)

    assert version_id == draft.id
    assert draft.metadata_document == document


def test_saving_a_document_marks_it_modified_even_when_it_is_the_drafts_own_object():
    """A caller that edits the draft's document in place and passes it back hands the column the
    object it already holds; without the flag no UPDATE is issued and the commit stores nothing."""
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    document = draft.metadata_document
    document["schema"].append({"name": "orders"})
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
        patch("testgen.common.contract_service.reconcile_contract_conformance"),
        patch.object(TestDefinition, "assign_missing_term_ids"),
        patch("testgen.common.contract_service.flag_modified") as flagged,
    ):
        contract_service.save_metadata_document(suite, document)

    flagged.assert_called_once_with(draft, "metadata_document")


def test_saving_a_document_reconciles_conformance_tests_after_committing_it():
    """Conformance generation reads the declared tables on its own connection, so the document
    has to be committed before it runs or the reconciliation sees the previous declaration."""
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    session = MagicMock()
    calls = []
    session.commit.side_effect = lambda: calls.append("commit")
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch(
            "testgen.common.contract_service.reconcile_contract_conformance",
            side_effect=lambda *_args, **_kwargs: calls.append("reconcile"),
        ),
        patch.object(TestDefinition, "assign_missing_term_ids"),
    ):
        contract_service.save_metadata_document(suite, {"schema": [{"name": "orders"}]})

    assert calls == ["commit", "reconcile"]


def test_initializing_a_contract_creates_a_first_draft_with_the_prefilled_document():
    suite = _suite()
    suite.test_suite = "Orders contract"
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock({"type": "postgres"})),
    ):
        contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    draft = session.add.call_args.args[0]
    assert draft.version == 1
    assert draft.frozen_at is None
    assert draft.metadata_document["servers"] == [{"type": "postgres"}]
    assert draft.metadata_document["name"] == "Orders contract"


def test_initializing_a_contract_returns_why_its_server_entry_is_custom():
    suite = _suite()
    reason = CustomServerReason(server_type=ServerType.BIGQUERY, missing_fields=("project",))
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
        patch(
            "testgen.common.contract_service.build_server_block",
            return_value=ServerBlock({"server": "bq", "type": "custom"}, reason),
        ),
    ):
        initialized = contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    assert initialized.custom_server_reason == reason
    assert initialized.draft.metadata_document["servers"] == [{"server": "bq", "type": "custom"}]


def test_initializing_a_contract_records_the_contract_generation_set():
    suite = _suite()
    suite.test_suite = "Orders contract"
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock({})),
    ):
        contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    assert suite.generation_sets == [contract_service.CONTRACT_GENERATION_SET]


def test_initializing_a_contract_passes_the_connection_and_table_group_to_the_server_builder():
    suite = _suite()
    suite.test_suite = "Orders contract"
    table_group = MagicMock()
    connection = MagicMock()
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock({})) as build,
    ):
        contract_service.initialize_contract(suite, table_group=table_group, connection=connection)

    build.assert_called_once_with(connection, table_group)


def test_initializing_a_contract_stamps_the_supplied_username():
    suite = _suite()
    suite.test_suite = "Orders contract"
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()) as get_session,
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock({})),
    ):
        contract_service.initialize_contract(
            suite, table_group=MagicMock(), connection=MagicMock(), username="tester"
        )

    draft = get_session.return_value.add.call_args.args[0]
    assert draft.created_by == "tester"


def test_adding_a_table_appends_a_descriptor_built_from_profiling():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    columns = [
        _column(column_name="id", functional_data_type="ID", db_data_type="integer", logical_type="integer"),
        _column(column_name="total", functional_data_type="Amount", db_data_type="numeric", logical_type="number"),
    ]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns) as generate,
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        report = contract_service.add_table(suite, "orders")

    descriptor, = draft.metadata_document["schema"]
    assert descriptor["name"] == "orders"
    assert [p["name"] for p in descriptor["properties"]] == ["id", "total"]
    generate.assert_called_once_with(suite.id, table_names=["orders"], refresh_identity=False)
    assert report.tables_declared == ["orders"]
    assert descriptor["properties"] == [
        {
            "name": "id", "physicalType": "integer", "logicalType": "integer",
            "customProperties": [{"property": "functionalDataType", "value": "ID"}],
        },
        {
            "name": "total", "physicalType": "numeric", "logicalType": "number",
            "customProperties": [{"property": "functionalDataType", "value": "Amount"}],
        },
    ]


def test_a_column_the_catalog_gives_no_odcs_logical_type_carries_none():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    columns = [_column(column_name="raw_blob", functional_data_type="Other", db_data_type="interval", logical_type=None)]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "logs")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_ == {
        "name": "raw_blob", "physicalType": "interval",
        "customProperties": [{"property": "functionalDataType", "value": "Other"}],
    }


def test_a_time_column_carries_the_odcs_time_logical_type():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    columns = [_column(column_name="shift_start", functional_data_type=None, db_data_type="time without time zone", logical_type="time")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "shifts")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_ == {"name": "shift_start", "physicalType": "time without time zone", "logicalType": "time"}


def test_a_column_with_no_functional_data_type_carries_no_custom_properties():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    columns = [_column(column_name="flag", functional_data_type=None, db_data_type="boolean", logical_type="boolean")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "flags")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_ == {"name": "flag", "physicalType": "boolean", "logicalType": "boolean"}


def test_adding_a_table_twice_produces_exactly_one_descriptor_for_it():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={
            "schema": [{"name": "orders", "properties": [{"name": "id", "physicalType": "text"}]}],
        },
    )
    columns = [_column(column_name="id", functional_data_type=None, db_data_type="integer", logical_type="integer")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    assert [d["name"] for d in draft.metadata_document["schema"]] == ["orders"]
    descriptor, = draft.metadata_document["schema"]
    assert descriptor["properties"] == [{"name": "id", "physicalType": "integer", "logicalType": "integer"}]


def test_readding_a_table_refreshes_its_catalog_fields_and_keeps_the_table_s_when_the_catalog_has_no_entry():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={
            "schema": [
                {
                    "name": "orders",
                    "description": "Customer orders",
                    "properties": [
                        {"name": "id", "description": "Primary key", "primaryKey": True, "physicalType": "text"},
                    ],
                },
            ],
        },
    )
    columns = [_column(
        column_name="id", functional_data_type="ID-Unique", db_data_type="integer", logical_type="integer",
        description="Order key",
    )]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    descriptor, = draft.metadata_document["schema"]
    assert descriptor["description"] == "Customer orders"
    property_, = descriptor["properties"]
    assert property_ == {
        "name": "id", "description": "Order key", "physicalType": "integer", "logicalType": "integer",
        "customProperties": [{"property": "functionalDataType", "value": "ID-Unique"}],
        "primaryKey": True, "primaryKeyPosition": 1,
    }


def test_readding_a_table_keeps_a_hand_authored_column_no_longer_profiled():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={
            "schema": [
                {
                    "name": "orders",
                    "properties": [
                        {"name": "id", "physicalType": "integer"},
                        {"name": "legacy_flag", "description": "Removed from the source table"},
                    ],
                },
            ],
        },
    )
    columns = [_column(column_name="id", functional_data_type=None, db_data_type="integer", logical_type="integer")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    descriptor, = draft.metadata_document["schema"]
    assert [p["name"] for p in descriptor["properties"]] == ["id", "legacy_flag"]
    legacy = next(p for p in descriptor["properties"] if p["name"] == "legacy_flag")
    assert legacy == {"name": "legacy_flag", "description": "Removed from the source table"}


def test_readding_a_table_refreshes_functional_data_type_and_keeps_other_custom_properties():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={
            "schema": [
                {
                    "name": "orders",
                    "properties": [
                        {
                            "name": "id",
                            "customProperties": [
                                {"property": "owner", "value": "sales-ops"},
                                {"property": "functionalDataType", "value": "Stale"},
                            ],
                        },
                    ],
                },
            ],
        },
    )
    columns = [_column(column_name="id", functional_data_type="ID", db_data_type="integer", logical_type="integer")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_["customProperties"] == [
        {"property": "owner", "value": "sales-ops"},
        {"property": "functionalDataType", "value": "ID"},
    ]


def test_readding_a_table_removes_a_logical_type_the_catalog_no_longer_maps():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={
            "schema": [{"name": "logs", "properties": [{"name": "payload", "logicalType": "string"}]}],
        },
    )
    columns = [_column(column_name="payload", functional_data_type=None, db_data_type="interval", logical_type=None)]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "logs")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_ == {"name": "payload", "physicalType": "interval"}


def test_removing_a_table_takes_its_descriptor_and_its_terms():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={"schema": [{"name": "orders"}, {"name": "customers"}]},
    )
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [
        "Required", "Unique", "Schema_Conformance", "Row_Ct",
    ]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
    ):
        report = contract_service.remove_table(suite, "orders")

    assert [d["name"] for d in draft.metadata_document["schema"]] == ["customers"]
    assert report["terms_removed"] == 3


def test_removing_a_table_flags_the_metadata_document_modified():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={"schema": [{"name": "orders"}]},
    )
    session = MagicMock()
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "flag_modified") as flag_modified,
        patch("testgen.common.contract_service.get_current_session", return_value=session),
    ):
        contract_service.remove_table(suite, "orders")

    flag_modified.assert_called_once_with(draft, "metadata_document")


def _conjuncts(clause) -> list:
    """The terms a WHERE clause ANDs together, flattened."""
    if clause is None:
        return []
    if isinstance(clause, BooleanClauseList) and clause.operator is operators.and_:
        return [term for child in clause.clauses for term in _conjuncts(child)]
    return [clause]


def _is_null_conjunct(term, column_key: str, table_name: str) -> bool:
    if not isinstance(term, BinaryExpression) or term.operator is not operators.is_:
        return False
    left = term.left
    return getattr(left, "key", None) == column_key and getattr(left.table, "name", None) == table_name


def test_removing_a_table_scopes_the_term_delete_to_the_version_and_the_table():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={"schema": [{"name": "orders"}, {"name": "customers"}]},
    )
    session = MagicMock()
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
    ):
        contract_service.remove_table(suite, "orders")

    statement = session.execute.call_args.args[0]
    conjuncts = _conjuncts(statement.whereclause)
    assert any(equality_conjunct(term, "version_id", "test_definitions", draft.id) for term in conjuncts)
    assert any(equality_conjunct(term, "table_name", "test_definitions", "orders") for term in conjuncts)


def test_resolving_a_write_target_refuses_a_suite_that_keeps_no_versions():
    """Only a contract has versions. Resolving a write target for a regular or monitor suite
    inserts a version row it should never own, and every test definition on it -- stamped
    with the placeholder -- then falls outside the suite's resolved version.
    """
    suite = _suite()
    suite.suite_type = SuiteType.REGULAR
    with (
        patch.object(SuiteVersion, "draft_for", return_value=None),
        patch.object(contract_service, "_active_version", return_value=None),
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        with pytest.raises(ValueError):
            contract_service.resolve_write_target(suite)


def test_adding_a_table_to_a_draft_that_carries_no_document_declares_it():
    """A draft copied forward from a version with no metadata document carries none itself,
    and a contract can be created by import or by hand rather than from a prefilled document.
    """
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=1, metadata_document=None)
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs([]),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    assert contract_document.declared_tables(draft.metadata_document) == ["orders"]


def test_initializing_a_contract_refuses_a_suite_that_keeps_no_versions():
    suite = _suite()
    suite.suite_type = SuiteType.REGULAR
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock({})),
    ):
        with pytest.raises(ValueError):
            contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())


def test_the_prefilled_document_carries_every_field_odcs_requires():
    suite = _suite()
    suite.test_suite = "Orders contract"
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock({"type": "postgres"})),
    ):
        contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    document = session.add.call_args.args[0].metadata_document
    # Top-level required properties of the ODCS schema, which also sets additionalProperties
    # and unevaluatedProperties to false -- a document missing any of them is rejected whole.
    assert document["apiVersion"] == ODCS_API_VERSION
    assert document["kind"] == ODCS_KIND
    assert document["id"] == str(suite.id)
    assert document["version"] == "1.0.0"


def test_the_prefilled_document_records_the_api_version_it_was_authored_against():
    suite = _suite()
    suite.test_suite = "Orders contract"
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock({})),
    ):
        contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    assert session.add.call_args.args[0].odcs_api_version == ODCS_API_VERSION


def test_the_documents_contract_version_tracks_the_suite_version():
    suite = _suite()
    suite.test_suite = "Orders contract"
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=4),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock({})),
    ):
        contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    assert session.add.call_args.args[0].metadata_document["version"] == "4.0.0"


def test_a_new_contracts_prefilled_document_validates():
    """The four keys ``test_the_prefilled_document_carries_every_field_odcs_requires`` asserts
    are present must also be legal ODCS values, not merely present -- a UUID string for ``id``
    and an invented ``version`` string are exactly the kind of value the schema could reject
    without either of them being absent.
    """
    suite = _suite()
    suite.test_suite = "Orders contract"
    session = MagicMock()
    server_block = {
        "server": "main_pg", "type": "postgres", "host": "db.example.com",
        "port": 5432, "database": "analytics", "schema": "public",
    }
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch("testgen.common.contract_service.build_server_block", return_value=ServerBlock(server_block)),
    ):
        contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    draft = session.add.call_args.args[0]
    assert validate_document(draft.metadata_document) == []


def test_a_carried_forward_document_still_validates_after_its_version_is_restated():
    # open_draft rewrites the carried document's root `version`; `document_version`'s
    # `N.0.0` has to stay a legal semantic version string for every N, not just the first.
    suite_id = uuid4()
    source_document = {
        "apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND, "id": str(suite_id), "version": "1.0.0",
        "name": "Orders contract",
        "servers": [
            {
                "server": "main_pg", "type": "postgres", "host": "db.example.com",
                "port": 5432, "database": "analytics", "schema": "public",
            },
        ],
        "schema": [],
    }
    source = SuiteVersion(
        id=uuid4(), test_suite_id=suite_id, version=1,
        frozen_at=datetime.now(UTC), metadata_document=source_document, odcs_api_version=ODCS_API_VERSION,
    )
    with (
        patch.object(SuiteVersion, "in_force_for", return_value=source),
        patch.object(SuiteVersion, "next_version_for", return_value=7),
        patch("testgen.common.models.suite_version.get_current_session", return_value=MagicMock()),
    ):
        draft, _ = SuiteVersion.open_draft(suite_id)

    assert draft.metadata_document["version"] == "7.0.0"
    assert validate_document(draft.metadata_document) == []


def test_a_document_built_through_the_real_contract_path_serializes():
    """Guards the whole enum-leak class in one assertion, rather than one field at a time.

    ``yaml.safe_dump`` is the only thing in this stack that tells a ``StrEnum`` member apart
    from its own value: the schema does not (jsonschema's type and enum checks pass a member
    the same as its value), dict equality does not, and ``isinstance`` does not (``StrEnum``
    subclasses ``str``). So the guard against every present and future instance of this class
    is to build a document through the real production path and serialize it for real, rather
    than asserting about one field's type.

    Real: ``initialize_contract``, ``build_server_block``, ``add_table``'s document merge
    (``contract_document.refresh_tables``), ``render_document``'s root-fundamentals fill, and
    ``serialize_document``.

    Substituted: the database session everywhere (``get_current_session`` -> ``MagicMock``,
    so nothing here reaches a real connection), the catalog reads
    (``contract_document.catalog_columns`` and ``_catalog_table`` -> in-memory objects, never
    queried), and the generation ``add_table`` hands off to, which keeps only its document merge
    and generates no terms. Because the contract ends up with no terms,
    ``render_document`` returns after filling the root and reusing the schema
    ``add_table`` wrote, without needing a real ``TableGroup``, ``Connection``, ``TestType``,
    or ``cat_test_conditions`` row -- the term-projection chain has its own leak coverage in
    ``test_rule_projection.py`` and is not what this test is proving.
    """
    suite = _suite()
    suite.test_suite = "Orders contract"

    connection = MagicMock()
    connection.sql_flavor_code = SqlFlavorCode.POSTGRESQL
    connection.connection_name = "main_pg"
    connection.project_host = "db.example.com"
    connection.project_port = "5432"
    connection.project_db = "analytics"
    connection.parameters = {}
    table_group = MagicMock()
    table_group.table_group_schema = "public"

    session_for_init = MagicMock()
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=session_for_init),
    ):
        contract_service.initialize_contract(suite, table_group=table_group, connection=connection)
    draft = session_for_init.add.call_args.args[0]

    columns = [
        _column(column_name="id", functional_data_type="ID", db_data_type="integer", logical_type="integer"),
        _column(column_name="order_date", functional_data_type=None, db_data_type="date", logical_type="date"),
    ]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        _generation_stubs(columns),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    with patch("testgen.common.odcs.render.get_current_session") as render_session:
        render_session.return_value.scalars.return_value = []
        document = render.render_document(draft)

    assert type(document["servers"][0]["type"]) is str
    serialize.serialize_document(document)


def test_adding_a_table_generates_that_table_alone_without_the_contract_identity():
    suite = _suite()
    result = ContractGenerationResult(
        term_count=5, tables_declared=["orders"], tables_not_in_catalog=[], tables_not_profiled=[],
    )
    with patch.object(contract_service, "run_contract_generation", return_value=result) as generate:
        assert contract_service.add_table(suite, "orders") is result

    generate.assert_called_once_with(suite.id, table_names=["orders"], refresh_identity=False)


def test_generated_terms_are_stamped_with_a_term_identity():
    term = MagicMock(
        test_type="Row_Ct", schema_name="public", table_name="orders", column_name="order_id"
    )
    session = MagicMock()
    session.scalars.return_value.all.return_value = [term]
    session.scalar.return_value = None
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.SuiteVersion.is_suite_owned", return_value=True),
    ):
        TestDefinition.assign_missing_term_ids(uuid4())

    assert term.contract_term_id == "Row_Ct-public-orders-order_id"


def _frozen_version(**overrides) -> SuiteVersion:
    fields = {
        "id": uuid4(), "test_suite_id": uuid4(), "version": 1,
        "frozen_at": datetime.now(UTC),
        "frozen_document": yaml.dump(_VALID_MERGED_DOCUMENT),
        "odcs_api_version": ODCS_API_VERSION,
    }
    fields.update(overrides)
    return SuiteVersion(**fields)


def test_exporting_a_frozen_version_returns_its_stored_bytes():
    frozen = _frozen_version()
    assert contract_service.export_version(frozen).text == frozen.frozen_document


def test_a_frozen_version_exports_identically_after_the_serialiser_changes(monkeypatch):
    # Without the monkeypatch this proves nothing -- a re-render would produce the same
    # string today. Reversing the serialiser's own root key order changes what a fresh
    # serialization would produce, so an unchanged result here can only come from the
    # stored bytes, never from rendering and serializing again.
    frozen = _frozen_version()
    before = contract_service.export_version(frozen).text
    monkeypatch.setattr(serialize, "ROOT_KEY_ORDER", list(reversed(serialize.ROOT_KEY_ORDER)))
    assert contract_service.export_version(frozen).text == before


def test_exporting_a_frozen_version_renders_nothing(monkeypatch):
    # The coalesce short-circuits: no terms are read and no rules are projected.
    def _raises(*_args, **_kwargs):
        raise AssertionError("render_document must not run for a frozen export")

    frozen = _frozen_version()
    monkeypatch.setattr(contract_service.render, "render_document", _raises)
    assert contract_service.export_version(frozen).text == frozen.frozen_document


def test_exporting_a_frozen_version_reports_whether_it_still_validates():
    frozen = _frozen_version()
    assert contract_service.export_version(frozen).problems == []


def test_exporting_a_draft_renders_it_fresh():
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=uuid4(), version=2, odcs_api_version=ODCS_API_VERSION,
    )
    with patch.object(contract_service.render, "render_document", return_value=_VALID_MERGED_DOCUMENT) as render_mock:
        exported = contract_service.export_version(draft)

    render_mock.assert_called_once_with(draft)
    assert yaml.safe_load(exported.text)["kind"] == ODCS_KIND
    assert exported.problems == []


def test_exporting_a_draft_that_does_not_validate_still_returns_a_document():
    # A preview that refuses to show itself because it is not yet valid is the opposite of
    # useful.
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=uuid4(), version=2, odcs_api_version=ODCS_API_VERSION,
    )
    invalid_document = {"version": "1.0.0", "apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND}  # no id
    with patch.object(contract_service.render, "render_document", return_value=invalid_document):
        exported = contract_service.export_version(draft)

    assert exported.text
    assert exported.problems


def test_exporting_without_a_number_prefers_the_draft():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=4)
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch.object(SuiteVersion, "in_force_for", return_value=SuiteVersion(id=uuid4(), version=3)),
    ):
        assert contract_service.version_for_export(suite) is draft


def test_exporting_without_a_number_falls_back_to_the_version_in_force():
    suite = _suite()
    active = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=3)
    with (
        patch.object(SuiteVersion, "draft_for", return_value=None),
        patch.object(SuiteVersion, "in_force_for", return_value=active),
    ):
        assert contract_service.version_for_export(suite) is active


def test_exporting_a_contract_with_neither_a_draft_nor_a_frozen_version_is_refused():
    suite = _suite()
    with (
        patch.object(SuiteVersion, "draft_for", return_value=None),
        patch.object(SuiteVersion, "in_force_for", return_value=None),
    ):
        with pytest.raises(ValueError, match="no version"):
            contract_service.version_for_export(suite)


def test_exporting_a_named_number_returns_that_version_without_consulting_the_default():
    suite = _suite()
    asked_for = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2)
    with (
        patch.object(SuiteVersion, "for_number", return_value=asked_for) as for_number,
        patch.object(SuiteVersion, "draft_for") as draft_for,
    ):
        assert contract_service.version_for_export(suite, 2) is asked_for

    for_number.assert_called_once_with(suite.id, 2)
    draft_for.assert_not_called()


def test_exporting_a_number_the_contract_has_no_version_at_names_the_number():
    suite = _suite()
    with patch.object(SuiteVersion, "for_number", return_value=None):
        with pytest.raises(ValueError, match="7"):
            contract_service.version_for_export(suite, 7)


def test_exporting_a_suite_that_keeps_no_versions_is_refused():
    suite = _suite()
    suite.suite_type = SuiteType.REGULAR
    with pytest.raises(ValueError, match="not a contract"):
        contract_service.version_for_export(suite)
