from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from testgen.common import contract_service
from testgen.common.enums import SuiteType
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.odcs_server import ODCS_API_VERSION, ODCS_KIND
from tests.unit.sql_assertions import equality_conjunct, is_not_null_conjunct, is_null_conjunct

pytestmark = pytest.mark.unit


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


def test_freezing_sets_the_freeze_time_and_does_not_touch_the_document_fields():
    suite = _suite()
    # A pre-existing (sentinel) value proves freeze_version leaves these fields alone in either
    # direction -- a draft always starts with them NULL, so asserting only "still None" would
    # hold even for an implementation that never looked at them at all.
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        frozen_document="sentinel-document", odcs_api_version="sentinel-version",
    )
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        frozen = contract_service.freeze_version(suite, label="first")

    assert frozen.frozen_at is not None
    assert frozen.frozen_document == "sentinel-document"
    assert frozen.odcs_api_version == "sentinel-version"
    assert frozen.label == "first"


def test_freezing_without_a_label_leaves_the_drafts_label_untouched():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, label="carried over")
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        frozen = contract_service.freeze_version(suite)

    assert frozen.label == "carried over"


def test_freezing_does_not_touch_the_drafts_author():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, created_by="original-author")
    with (
        patch.object(SuiteVersion, "draft_for", return_value=draft),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        frozen = contract_service.freeze_version(suite, label="first")

    assert frozen.created_by == "original-author"


def test_freezing_without_a_draft_is_refused():
    suite = _suite()
    with patch.object(SuiteVersion, "draft_for", return_value=None):
        with pytest.raises(ValueError, match="no draft"):
            contract_service.freeze_version(suite)


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
    ):
        version_id = contract_service.save_metadata_document(suite, document)

    assert version_id == draft.id
    assert draft.metadata_document == document


def test_initializing_a_contract_creates_a_first_draft_with_the_prefilled_document():
    suite = _suite()
    suite.test_suite = "Orders contract"
    session = MagicMock()
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch("testgen.common.contract_service.build_server_block", return_value={"type": "postgres"}),
    ):
        contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    draft = session.add.call_args.args[0]
    assert draft.version == 1
    assert draft.frozen_at is None
    assert draft.metadata_document["servers"] == [{"type": "postgres"}]
    assert draft.metadata_document["name"] == "Orders contract"


def test_initializing_a_contract_records_the_contract_generation_set():
    suite = _suite()
    suite.test_suite = "Orders contract"
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
        patch("testgen.common.contract_service.build_server_block", return_value={}),
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
        patch("testgen.common.contract_service.build_server_block", return_value={}) as build,
    ):
        contract_service.initialize_contract(suite, table_group=table_group, connection=connection)

    build.assert_called_once_with(connection, table_group)


def test_initializing_a_contract_stamps_the_supplied_username():
    suite = _suite()
    suite.test_suite = "Orders contract"
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()) as get_session,
        patch("testgen.common.contract_service.build_server_block", return_value={}),
    ):
        contract_service.initialize_contract(
            suite, table_group=MagicMock(), connection=MagicMock(), username="tester"
        )

    draft = get_session.return_value.add.call_args.args[0]
    assert draft.created_by == "tester"


def test_the_declared_tables_are_the_schema_sections_names():
    document = {"schema": [{"name": "orders"}, {"name": "customers"}]}
    assert contract_service.declared_tables(document) == ["orders", "customers"]


def test_a_document_with_no_schema_section_declares_nothing():
    assert contract_service.declared_tables({}) == []
    assert contract_service.declared_tables(None) == []


def test_profiled_columns_scopes_to_the_suites_table_group_and_the_exact_table_and_drop():
    suite = _suite()
    suite.table_groups_id = uuid4()
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    with patch("testgen.common.contract_service.get_current_session", return_value=session):
        contract_service._profiled_columns(suite, "orders")

    statement = session.scalars.call_args.args[0]
    conjuncts = _conjuncts(statement.whereclause)
    assert any(
        equality_conjunct(term, "table_groups_id", "data_column_chars", suite.table_groups_id)
        for term in conjuncts
    )
    assert any(equality_conjunct(term, "table_name", "data_column_chars", "orders") for term in conjuncts)
    assert any(_is_null_conjunct(term, "drop_date", "data_column_chars") for term in conjuncts)

    order_by = statement._order_by_clauses
    assert len(order_by) == 1
    ordering = order_by[0]
    assert getattr(ordering.element, "key", None) == "ordinal_position"
    assert ordering.modifier is operators.asc_op


def test_adding_a_table_appends_a_descriptor_built_from_profiling():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    columns = [
        MagicMock(column_name="id", general_type="N", functional_data_type="ID", column_type="integer"),
        MagicMock(column_name="total", general_type="N", functional_data_type="Amount", column_type="numeric"),
    ]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables") as generate,
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        report = contract_service.add_table(suite, "orders")

    descriptor, = draft.metadata_document["schema"]
    assert descriptor["name"] == "orders"
    assert [p["name"] for p in descriptor["properties"]] == ["id", "total"]
    assert generate.call_args.args[1] == ["orders"]
    assert report["declared"] == ["orders"]
    assert descriptor["properties"] == [
        {
            "name": "id", "physicalType": "integer", "logicalType": "number",
            "customProperties": [{"property": "functionalDataType", "value": "ID"}],
        },
        {
            "name": "total", "physicalType": "numeric", "logicalType": "number",
            "customProperties": [{"property": "functionalDataType", "value": "Amount"}],
        },
    ]


def test_a_column_whose_general_type_has_no_odcs_logical_type_carries_none():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    columns = [MagicMock(column_name="raw_blob", general_type="X", functional_data_type="Other", column_type="text")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "logs")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_ == {
        "name": "raw_blob", "physicalType": "text",
        "customProperties": [{"property": "functionalDataType", "value": "Other"}],
    }


def test_a_time_column_carries_the_odcs_time_logical_type():
    """ODCS v3.2.0 lists ``time`` among its logical types, so a profiled Time column has a
    faithful one and does not have to go without. ``Other`` is the only code that has none.
    """
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    columns = [MagicMock(column_name="shift_start", general_type="T", functional_data_type=None, column_type="time")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "shifts")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_ == {"name": "shift_start", "physicalType": "time", "logicalType": "time"}


def test_a_column_with_no_functional_data_type_carries_no_custom_properties():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    columns = [MagicMock(column_name="flag", general_type="B", functional_data_type=None, column_type="boolean")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables"),
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
    columns = [MagicMock(column_name="id", general_type="N", functional_data_type=None, column_type="integer")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    assert [d["name"] for d in draft.metadata_document["schema"]] == ["orders"]
    descriptor, = draft.metadata_document["schema"]
    assert descriptor["properties"] == [{"name": "id", "physicalType": "integer", "logicalType": "number"}]


def test_readding_a_table_preserves_hand_authored_fields_while_refreshing_profiling_ones():
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
    columns = [MagicMock(column_name="id", general_type="N", functional_data_type=None, column_type="integer")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    descriptor, = draft.metadata_document["schema"]
    assert descriptor["description"] == "Customer orders"
    property_, = descriptor["properties"]
    assert property_ == {
        "name": "id", "description": "Primary key", "primaryKey": True,
        "physicalType": "integer", "logicalType": "number",
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
    columns = [MagicMock(column_name="id", general_type="N", functional_data_type=None, column_type="integer")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    descriptor, = draft.metadata_document["schema"]
    assert [p["name"] for p in descriptor["properties"]] == ["id", "legacy_flag"]
    legacy = next(p for p in descriptor["properties"] if p["name"] == "legacy_flag")
    assert legacy == {"name": "legacy_flag", "description": "Removed from the source table"}


def test_readding_a_table_preserves_other_custom_properties_while_refreshing_functional_data_type():
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
                                {"property": "sourceSystem", "value": "legacy_erp"},
                                {"property": "functionalDataType", "value": "Stale"},
                            ],
                        },
                    ],
                },
            ],
        },
    )
    columns = [MagicMock(column_name="id", general_type="N", functional_data_type="ID", column_type="integer")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_["customProperties"] == [
        {"property": "sourceSystem", "value": "legacy_erp"},
        {"property": "functionalDataType", "value": "ID"},
    ]


def test_readding_a_table_keeps_an_existing_logical_type_when_the_refresh_has_none_to_offer():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={
            "schema": [{"name": "logs", "properties": [{"name": "payload", "logicalType": "string"}]}],
        },
    )
    columns = [MagicMock(column_name="payload", general_type="X", functional_data_type=None, column_type="text")]
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=columns),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "logs")

    descriptor, = draft.metadata_document["schema"]
    property_, = descriptor["properties"]
    assert property_ == {"name": "payload", "logicalType": "string", "physicalType": "text"}


def test_adding_a_table_flags_the_metadata_document_modified():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=[]),
        patch.object(contract_service, "_generate_for_tables"),
        patch.object(contract_service, "flag_modified") as flag_modified,
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    flag_modified.assert_called_once_with(draft, "metadata_document")


def test_adding_a_table_the_group_does_not_hold_declares_it_and_reports_it():
    suite = _suite()
    draft = SuiteVersion(id=uuid4(), test_suite_id=suite.id, version=2, metadata_document={"schema": []})
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})),
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_profiled_columns", return_value=[]),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        report = contract_service.add_table(suite, "ghost")

    assert [d["name"] for d in draft.metadata_document["schema"]] == ["ghost"]
    assert report["unverifiable"] is True


def test_removing_a_table_takes_its_descriptor_and_its_terms():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={"schema": [{"name": "orders"}, {"name": "customers"}]},
    )
    session = MagicMock()
    session.execute.return_value.rowcount = 3
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
    session.execute.return_value.rowcount = 0
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


def test_generating_terms_resolves_a_write_target_and_generates_for_every_declared_table():
    suite = _suite()
    draft = SuiteVersion(
        id=uuid4(), test_suite_id=suite.id, version=2,
        metadata_document={"schema": [{"name": "orders"}, {"name": "customers"}]},
    )
    with (
        patch.object(contract_service, "resolve_write_target", return_value=(draft.id, {})) as resolve,
        patch.object(SuiteVersion, "get", return_value=draft),
        patch.object(contract_service, "_generate_for_tables") as generate,
    ):
        report = contract_service.generate_terms(suite)

    resolve.assert_called_once_with(suite)
    generate.assert_called_once_with(suite, ["orders", "customers"], draft.id)
    assert report["declared"] == ["orders", "customers"]


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
        patch.object(contract_service, "_profiled_columns", return_value=[]),
        patch.object(contract_service, "_generate_for_tables"),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
    ):
        contract_service.add_table(suite, "orders")

    assert contract_service.declared_tables(draft.metadata_document) == ["orders"]


def test_initializing_a_contract_refuses_a_suite_that_keeps_no_versions():
    suite = _suite()
    suite.suite_type = SuiteType.REGULAR
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
        patch("testgen.common.contract_service.build_server_block", return_value={}),
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
        patch("testgen.common.contract_service.build_server_block", return_value={"type": "postgres"}),
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
        patch("testgen.common.contract_service.build_server_block", return_value={}),
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
        patch("testgen.common.contract_service.build_server_block", return_value={}),
    ):
        contract_service.initialize_contract(suite, table_group=MagicMock(), connection=MagicMock())

    assert session.add.call_args.args[0].metadata_document["version"] == "4.0.0"


def test_generation_runs_only_after_the_draft_is_committed():
    """Generation reaches the database on its own connection, so a draft that is merely
    flushed is invisible to it and the terms it inserts violate the version foreign key.
    """
    suite = _suite()
    session = MagicMock()
    calls = []
    session.commit.side_effect = lambda: calls.append("commit")
    with (
        patch("testgen.common.contract_service.get_current_session", return_value=session),
        patch("testgen.common.contract_service.run_test_generation", side_effect=lambda *_args, **_kwargs: calls.append("generate")),
        patch.object(contract_service, "_stamp_term_ids"),
    ):
        contract_service._generate_for_tables(suite, ["orders"], uuid4())

    assert calls.index("commit") < calls.index("generate")


def test_generated_terms_are_stamped_with_a_term_identity():
    suite = _suite()
    term = MagicMock(
        test_type="Row_Ct", schema_name="public", table_name="orders", column_name="order_id"
    )
    session = MagicMock()
    session.scalars.return_value.all.return_value = [term]
    with patch("testgen.common.contract_service.get_current_session", return_value=session):
        contract_service._stamp_term_ids(uuid4())

    assert term.contract_term_id == "Row_Ct-public-orders-order_id"


def test_only_generated_terms_are_stamped_with_an_identity():
    """A manual term is deduped by nothing -- the natural-key indexes are partial on
    ``last_auto_gen_date`` -- so one sharing a generated term's key would slug identically and
    fail the unique index the identity lives in. It keeps no identity instead.
    """
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    with patch("testgen.common.contract_service.get_current_session", return_value=session):
        contract_service._stamp_term_ids(uuid4())

    terms = _conjuncts(session.scalars.call_args.args[0].whereclause)
    assert any(is_not_null_conjunct(term, "last_auto_gen_date", "test_definitions") for term in terms)
    assert any(is_null_conjunct(term, "contract_term_id", "test_definitions") for term in terms)
