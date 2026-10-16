from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.sql import operators

from testgen.common import contract_document
from testgen.common.data_catalog_service import TAG_FIELDS
from tests.unit.sql_assertions import conjuncts, equality_conjunct, is_null_conjunct

pytestmark = pytest.mark.unit


def _governance(**fields) -> dict:
    return {
        "description": None, "critical_data_element": None, "pii_flag": None, "excluded_data_element": None,
        "functional_table_type": None, **dict.fromkeys(TAG_FIELDS), **fields,
    }


def _column(name: str, logical_type: str | None = "string", functional_data_type: str | None = None, **fields):
    return SimpleNamespace(
        column_name=name, db_data_type="text", logical_type=logical_type, functional_data_type=functional_data_type,
        **_governance(**fields),
    )


def _table_group(description: str | None = None, **tags):
    return SimpleNamespace(
        id=uuid4(), description=description, **{**dict.fromkeys(TAG_FIELDS), "data_location": None, **tags}
    )


def _refresh(document: dict, columns: list, table=None, table_group=None) -> dict[str, int]:
    with (
        patch.object(contract_document, "catalog_columns", return_value=columns),
        patch.object(contract_document, "_catalog_table", return_value=table),
    ):
        table_group = table_group or _table_group()
        contract_document.refresh_identity(document, table_group)
        return contract_document.refresh_tables(document, table_group, ["orders"])


def _custom(node: dict) -> dict:
    return {entry["property"]: entry["value"] for entry in node.get("customProperties", [])}


# --- declared tables and the catalog read ---


def test_the_declared_tables_are_the_schema_sections_names():
    document = {"schema": [{"name": "orders"}, {"name": "customers"}]}
    assert contract_document.declared_tables(document) == ["orders", "customers"]


def test_a_null_schema_section_declares_nothing_and_a_refresh_replaces_it():
    assert contract_document.declared_tables({"schema": None}) == []

    document = {"schema": None}
    _refresh(document, [_column("id")])

    assert contract_document.declared_tables(document) == ["orders"]


def test_a_document_with_no_schema_section_declares_nothing():
    assert contract_document.declared_tables({}) == []
    assert contract_document.declared_tables(None) == []


def test_catalog_columns_scopes_to_the_table_group_and_the_exact_table_and_drop():
    table_groups_id = uuid4()
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    with patch.object(contract_document, "get_current_session", return_value=session):
        contract_document.catalog_columns(table_groups_id, "orders")

    statement = session.scalars.call_args.args[0]
    terms = conjuncts(statement.whereclause)
    assert any(equality_conjunct(term, "table_groups_id", "data_column_chars", table_groups_id) for term in terms)
    assert any(equality_conjunct(term, "table_name", "data_column_chars", "orders") for term in terms)
    assert any(is_null_conjunct(term, "drop_date", "data_column_chars") for term in terms)

    ordering, = statement._order_by_clauses
    assert getattr(ordering.element, "key", None) == "ordinal_position"
    assert ordering.modifier is operators.asc_op


# --- refresh_tables: governance ---


def test_refreshing_declares_a_table_not_yet_declared_and_counts_its_columns():
    document = {"schema": []}

    counts = _refresh(document, [_column("id")])

    assert contract_document.declared_tables(document) == ["orders"]
    assert counts == {"orders": 1}


def test_a_column_carries_its_description_classification_and_tags():
    document = {"schema": []}

    _refresh(document, [
        _column("id", description="Order key", data_classification="internal", source_system="erp"),
    ])

    prop, = document["schema"][0]["properties"]
    assert prop["description"] == "Order key"
    assert prop["classification"] == "internal"
    assert _custom(prop)["sourceSystem"] == "erp"
    assert "dataClassification" not in _custom(prop)


def test_a_column_carries_only_the_tags_it_sets_itself():
    document = {"schema": []}
    table = SimpleNamespace(**_governance(business_domain="sales"))

    _refresh(
        document,
        [_column("id"), _column("total", business_domain="finance")],
        table=table,
        table_group=_table_group(business_domain="corporate", data_product="orders-360"),
    )

    by_name = {prop["name"]: _custom(prop) for prop in document["schema"][0]["properties"]}
    assert by_name["id"] == {}
    assert by_name["total"] == {"businessDomain": "finance"}


def test_a_table_carries_only_the_tags_it_sets_itself():
    document = {"schema": []}
    table = SimpleNamespace(**_governance(business_domain="sales"))

    _refresh(
        document, [_column("id")], table=table,
        table_group=_table_group(business_domain="corporate", source_system="erp"),
    )

    assert _custom(document["schema"][0]) == {"businessDomain": "sales"}
    assert (document["domain"], _custom(document)) == ("corporate", {"sourceSystem": "erp"})


def test_a_column_flagged_as_pii_carries_a_pii_custom_property():
    document = {"schema": []}

    _refresh(document, [_column("email", pii_flag="A/CONTACT"), _column("id")])

    by_name = {prop["name"]: _custom(prop) for prop in document["schema"][0]["properties"]}
    assert by_name["email"] == {"pii": True}
    assert "pii" not in by_name["id"]


def test_a_column_of_a_critical_table_is_a_critical_data_element():
    document = {"schema": []}
    table = SimpleNamespace(**_governance(critical_data_element=True))

    _refresh(document, [_column("id")], table=table)

    prop, = document["schema"][0]["properties"]
    assert prop["criticalDataElement"] is True


def test_a_column_that_is_not_critical_carries_no_flag():
    document = {"schema": []}

    _refresh(document, [_column("id", critical_data_element=False)])

    prop, = document["schema"][0]["properties"]
    assert "criticalDataElement" not in prop


def test_a_table_carries_its_description_flag_and_tags_as_custom_properties():
    document = {"schema": []}
    table = SimpleNamespace(**_governance(
        description="Customer orders", critical_data_element=True, data_classification="internal",
    ))

    _refresh(document, [_column("id")], table=table)

    descriptor = document["schema"][0]
    assert descriptor["description"] == "Customer orders"
    assert _custom(descriptor) == {"criticalDataElement": True, "dataClassification": "internal"}
    assert "classification" not in descriptor


def test_a_refresh_replaces_catalog_values_and_keeps_fields_no_source_supplies():
    document = {"schema": [{
        "name": "orders",
        "description": "Orders as the counterparty sees them",
        "authoritativeDefinitions": [{"type": "businessDefinition", "url": "https://example.com/orders"}],
        "properties": [{
            "name": "id",
            "description": "Hand-written",
            "classification": "public",
            "examples": ["1001"],
            "customProperties": [
                {"property": "sourceSystem", "value": "hand-picked"},
                {"property": "owner", "value": "sales-ops"},
            ],
        }],
    }]}
    table = SimpleNamespace(**_governance(description="Catalog description"))

    _refresh(
        document,
        [_column("id", description="Catalog", data_classification="internal", source_system="erp")],
        table=table,
    )

    descriptor = document["schema"][0]
    assert descriptor["description"] == "Catalog description"
    assert descriptor["authoritativeDefinitions"] == [
        {"type": "businessDefinition", "url": "https://example.com/orders"},
    ]
    prop, = descriptor["properties"]
    assert prop["description"] == "Catalog"
    assert prop["classification"] == "internal"
    assert prop["examples"] == ["1001"]
    assert prop["customProperties"] == [
        {"property": "sourceSystem", "value": "erp"},
        {"property": "owner", "value": "sales-ops"},
    ]


def test_values_the_catalog_no_longer_holds_are_removed():
    document = {"schema": []}
    _refresh(document, [_column(
        "id", description="Order key", data_classification="internal", source_system="erp",
        critical_data_element=True, pii_flag=True, excluded_data_element=True,
    )])

    _refresh(document, [_column("id")])

    prop, = document["schema"][0]["properties"]
    assert prop == {"name": "id", "physicalType": "text", "logicalType": "string"}


def test_a_table_the_catalog_no_longer_flags_loses_its_table_fields():
    document = {"schema": []}
    _refresh(document, [_column("id")], table=SimpleNamespace(**_governance(
        description="Orders", critical_data_element=True, source_system="erp",
        functional_table_type="cumulative-transaction",
    )))

    _refresh(document, [_column("id")], table=SimpleNamespace(**_governance()))

    descriptor = document["schema"][0]
    assert set(descriptor) == {"name", "properties"}


def test_a_column_the_catalog_no_longer_holds_is_left_as_it_is():
    dropped = {"name": "legacy_code", "physicalType": "text", "description": "Retired", "primaryKey": True}
    document = {"schema": [{"name": "orders", "properties": [dict(dropped)]}]}

    _refresh(document, [_column("id")])

    assert document["schema"][0]["properties"][0] == {k: v for k, v in dropped.items() if k != "primaryKey"}
    assert [prop["name"] for prop in document["schema"][0]["properties"]] == ["legacy_code", "id"]


def test_a_table_the_catalog_does_not_hold_keeps_its_descriptor():
    descriptor = {
        "name": "orders", "description": "Orders",
        "customProperties": [{"property": "criticalDataElement", "value": True}],
        "properties": [{"name": "id", "description": "Order key", "primaryKey": True, "primaryKeyPosition": 1}],
    }
    document = {"schema": [dict(descriptor)]}

    counts = _refresh(document, [], table=None)

    assert counts == {"orders": 0}
    assert document["schema"][0] == descriptor


def test_refreshing_twice_adds_no_custom_property_twice():
    document = {"schema": []}
    columns = [_column("id", source_system="erp")]

    _refresh(document, columns)
    _refresh(document, columns)

    prop, = document["schema"][0]["properties"]
    assert [entry["property"] for entry in prop["customProperties"]] == ["sourceSystem"]


# --- refresh_tables: identity, table type, keys, formats, excluded columns ---


def test_the_contract_identity_comes_from_the_table_group():
    document = {"schema": []}

    _refresh(
        document, [_column("id")],
        table_group=_table_group(description="Retail orders", business_domain="retail", data_product="orders-360"),
    )

    assert document["domain"] == "retail"
    assert document["dataProduct"] == "orders-360"
    assert document["description"] == {"purpose": "Retail orders"}


def test_the_table_group_s_other_tags_are_contract_custom_properties():
    document = {"schema": []}

    _refresh(
        document, [_column("id")],
        table_group=_table_group(
            business_domain="retail", source_system="erp", stakeholder_group="sales-ops", data_location="Cloud",
        ),
    )

    assert _custom(document) == {"sourceSystem": "erp", "stakeholderGroup": "sales-ops", "dataLocation": "Cloud"}


def test_a_contract_custom_property_no_table_group_field_supplies_is_kept():
    document = {"schema": [], "customProperties": [{"property": "aggregationLevel", "value": "daily"}]}

    _refresh(document, [_column("id")], table_group=_table_group())

    assert _custom(document) == {"aggregationLevel": "daily"}


def test_a_contract_tag_takes_the_table_group_s_value_and_other_custom_properties_are_kept():
    document = {"schema": [], "customProperties": [
        {"property": "sourceSystem", "value": "hand-picked"},
        {"property": "owner", "value": "sales-ops"},
    ]}

    _refresh(document, [_column("id")], table_group=_table_group(source_system="erp"))

    assert document["customProperties"] == [
        {"property": "sourceSystem", "value": "erp"},
        {"property": "owner", "value": "sales-ops"},
    ]


def test_the_contract_identity_is_refreshed_and_the_rest_of_its_description_kept():
    document = {"schema": [], "domain": "sales", "description": {"purpose": "Hand-written", "usage": "Reporting"}}

    _refresh(
        document, [_column("id")],
        table_group=_table_group(description="Retail orders", business_domain="retail"),
    )

    assert document["domain"] == "retail"
    assert document["description"] == {"purpose": "Retail orders", "usage": "Reporting"}


def test_an_identity_the_table_group_no_longer_holds_is_removed():
    document = {"schema": [], "domain": "sales", "description": {"purpose": "Hand-written"}}

    _refresh(document, [_column("id")], table_group=_table_group())

    assert "domain" not in document
    assert "description" not in document


def test_a_description_with_no_purpose_gains_one():
    document = {"schema": [], "description": {"usage": "Reporting"}}

    _refresh(document, [_column("id")], table_group=_table_group(description="Retail orders"))

    assert document["description"] == {"usage": "Reporting", "purpose": "Retail orders"}


@pytest.mark.parametrize(("table_type", "granularity"), [
    ("cumulative-transaction", "One row per transaction; rows accumulate and are not removed."),
    ("window-summary",
     "One row per combination of grouping keys, holding aggregated measures; older rows roll off as new rows arrive."),
    ("cumulative-domain", "Rows accumulate and are not removed."),
])
def test_a_table_states_the_granularity_profiling_inferred(table_type, granularity):
    document = {"schema": []}

    _refresh(document, [_column("id")], table=SimpleNamespace(**_governance(functional_table_type=table_type)))

    descriptor = document["schema"][0]
    assert descriptor["dataGranularityDescription"] == granularity
    assert _custom(descriptor)["functionalTableType"] == table_type


def test_the_identifying_column_becomes_the_primary_key():
    document = {"schema": []}

    _refresh(document, [_column("id", "integer", "ID-Unique"), _column("code", "string", "ID-Secondary")])

    key, code = document["schema"][0]["properties"]
    assert (key["primaryKey"], key["primaryKeyPosition"]) == (True, 1)
    assert "primaryKey" not in code


def test_a_surrogate_key_is_preferred_as_the_primary_key():
    document = {"schema": []}

    _refresh(document, [_column("natural", "string", "ID-Unique"), _column("sk", "integer", "ID-Unique-SK")])

    assert [prop["name"] for prop in document["schema"][0]["properties"] if prop.get("primaryKey")] == ["sk"]


def test_two_identifying_columns_declare_no_primary_key():
    document = {"schema": []}

    _refresh(document, [_column("a", "integer", "ID-Unique"), _column("b", "integer", "ID-Unique")])

    assert not any("primaryKey" in prop for prop in document["schema"][0]["properties"])


def test_the_primary_key_follows_the_identifying_column_profiling_finds():
    document = {"schema": [{"name": "orders", "properties": [{"name": "code", "primaryKey": True}]}]}

    _refresh(document, [_column("id", "integer", "ID-Unique"), _column("code")])

    assert [prop["name"] for prop in document["schema"][0]["properties"] if prop.get("primaryKey")] == ["id"]


def test_a_primary_key_profiling_no_longer_identifies_is_removed():
    document = {"schema": [{"name": "orders", "properties": [
        {"name": "id", "primaryKey": True, "primaryKeyPosition": 1},
    ]}]}

    _refresh(document, [_column("id", "integer")])

    assert document["schema"][0]["properties"][0].keys() == {"name", "physicalType", "logicalType"}


def test_a_recognized_string_column_declares_its_format():
    document = {"schema": []}

    _refresh(document, [
        _column("email", "string", "Email"),
        _column("zip", "string", "Zip"),
        _column("zip_number", "integer", "Zip"),
        _column("note", "string", "Description"),
    ])

    options = {prop["name"]: prop.get("logicalTypeOptions") for prop in document["schema"][0]["properties"]}
    assert options == {"email": {"format": "email"}, "zip": {"format": "us-zip"}, "zip_number": None, "note": None}


def test_a_format_profiling_no_longer_recognizes_is_removed_and_other_options_kept():
    document = {"schema": [{"name": "orders", "properties": [
        {"name": "email", "logicalTypeOptions": {"format": "email", "pattern": "^.+@.+$"}},
        {"name": "zip", "logicalTypeOptions": {"format": "us-zip"}},
    ]}]}

    _refresh(document, [_column("email", "string", "Description"), _column("zip", "integer", "Zip")])

    options = {prop["name"]: prop.get("logicalTypeOptions") for prop in document["schema"][0]["properties"]}
    assert options == {"email": {"pattern": "^.+@.+$"}, "zip": None}


def test_a_format_joins_type_options_left_empty_by_hand():
    document = {"schema": [{"name": "orders", "properties": [{"name": "email", "logicalTypeOptions": None}]}]}

    _refresh(document, [_column("email", "string", "Email")])

    assert document["schema"][0]["properties"][0]["logicalTypeOptions"] == {"format": "email"}


def test_profiled_table_names_keeps_the_tables_the_run_has_results_for_in_order():
    session = MagicMock()
    session.scalars.return_value = ["customers", "orders"]
    run_id = uuid4()
    with patch.object(contract_document, "get_current_session", return_value=session):
        assert contract_document.profiled_table_names(run_id, ["orders", "products", "customers"]) == [
            "orders", "customers",
        ]

    terms = conjuncts(session.scalars.call_args.args[0].whereclause)
    assert any(equality_conjunct(term, "profile_run_id", "profile_results", run_id) for term in terms)


def test_an_excluded_column_stays_declared_and_marked_with_no_key_or_format():
    document = {"schema": []}

    _refresh(document, [
        _column("id", "integer", "ID-Unique", excluded_data_element=True),
        _column("email", "string", "Email", excluded_data_element=True),
    ])

    for prop in document["schema"][0]["properties"]:
        assert contract_document.is_excluded(prop), prop["name"]
        assert "primaryKey" not in prop
        assert "logicalTypeOptions" not in prop


def test_a_column_newly_excluded_loses_its_profiled_values_but_keeps_its_options():
    document = {"schema": [{"name": "orders", "properties": [
        {"name": "amount", "logicalType": "number", "logicalTypeOptions": {"maximum": 120, "multipleOf": 0.5},
         "customProperties": [{"property": "profiledValues", "value": {"minimum": 0.5, "maximum": 120}}]},
    ]}]}

    _refresh(document, [_column("amount", "number", excluded_data_element=True)])

    prop, = document["schema"][0]["properties"]
    assert contract_document.is_excluded(prop)
    assert prop["logicalTypeOptions"] == {"maximum": 120, "multipleOf": 0.5}
    assert _profiled_values(prop) is None


# --- fill_profiled_values ---


def _profile(table: str, column: str, **values):
    fields = dict.fromkeys(("min_value", "max_value", "min_date", "max_date", "min_length", "max_length"))
    return SimpleNamespace(table_name=table, column_name=column, **{**fields, **values})


def _fill(document: dict, profiles: list) -> None:
    session = MagicMock()
    session.scalar.return_value = datetime(2026, 10, 14, 9, 30)
    session.scalars.return_value = profiles
    with patch.object(contract_document, "get_current_session", return_value=session):
        contract_document.fill_profiled_values(document, uuid4(), ["orders"])


def _document(*props: dict) -> dict:
    return {"schema": [{"name": "orders", "properties": [dict(prop) for prop in props]}]}


def _profiled_values(prop: dict) -> dict | None:
    return next(
        (entry["value"] for entry in prop.get("customProperties") or [] if entry["property"] == "profiledValues"),
        None,
    )


@pytest.mark.parametrize(("logical_type", "observed", "expected"), [
    ("number", {"min_value": 0.5, "max_value": 120.0}, {"minimum": 0.5, "maximum": 120}),
    ("integer", {"min_value": 1.5, "max_value": 9.0}, {"maximum": 9}),
    ("string", {"min_length": 2, "max_length": 8}, {"minLength": 2, "maxLength": 8}),
    ("date", {"min_date": datetime(2024, 1, 2), "max_date": datetime(2025, 6, 30)},
     {"minimum": "2024-01-02", "maximum": "2025-06-30"}),
], ids=["number", "integer", "string", "date"])
def test_a_column_gets_what_profiling_observed_as_profiled_values(logical_type, observed, expected):
    document = _document({"name": "c", "logicalType": logical_type})

    _fill(document, [_profile("orders", "c", **observed)])

    prop = document["schema"][0]["properties"][0]
    assert _profiled_values(prop) == expected
    assert "logicalTypeOptions" not in prop
    entry, = prop["customProperties"]
    assert entry["description"] == (
        "Values TestGen profiling observed on 2026-10-14. A description of the data, not part of the agreement."
    )


def test_profiled_values_leave_the_columns_options_alone():
    document = _document({
        "name": "amount", "logicalType": "number", "logicalTypeOptions": {"maximum": 1000, "multipleOf": 0.5},
    })

    _fill(document, [_profile("orders", "amount", min_value=0.5, max_value=120.0)])

    prop = document["schema"][0]["properties"][0]
    assert prop["logicalTypeOptions"] == {"maximum": 1000, "multipleOf": 0.5}
    assert _profiled_values(prop) == {"minimum": 0.5, "maximum": 120}


def test_profiled_values_take_the_runs_values_and_date_in_place():
    document = _document({"name": "code", "logicalType": "string", "customProperties": [
        {"property": "owner", "value": "ops"},
        {"property": "profiledValues", "value": {"minimum": 1, "maximum": 9}},
    ]})

    _fill(document, [_profile("orders", "code", min_length=1, max_length=1)])

    assert document["schema"][0]["properties"][0]["customProperties"] == [
        {"property": "owner", "value": "ops"},
        {"property": "profiledValues", "value": {"minLength": 1, "maxLength": 1}, "description": (
            "Values TestGen profiling observed on 2026-10-14. A description of the data, not part of the agreement."
        )},
    ]


def test_a_column_the_run_has_no_results_for_keeps_its_profiled_values():
    prop = {"name": "amount", "logicalType": "number", "customProperties": [
        {"property": "profiledValues", "value": {"minimum": 0}},
    ]}
    document = _document(prop)

    _fill(document, [])

    assert document["schema"][0]["properties"][0] == prop


def test_a_column_with_no_logical_type_or_an_excluded_column_gets_no_profiled_values():
    document = _document(
        {"name": "blob"},
        {"name": "secret", "logicalType": "string",
         "customProperties": [{"property": "excludedDataElement", "value": True}]},
    )

    _fill(document, [_profile("orders", "blob", min_length=1), _profile("orders", "secret", min_length=1)])

    assert all(_profiled_values(prop) is None for prop in document["schema"][0]["properties"])
