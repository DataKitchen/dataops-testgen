import json
from importlib import resources

import pytest
import yaml

from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.common.odcs.quality_rules import project_rule
from testgen.common.odcs.serialize import (
    PROPERTY_KEY_ORDER,
    ROOT_KEY_ORDER,
    RULE_KEY_ORDER,
    SCHEMA_KEY_ORDER,
    serialize_document,
)
from testgen.common.odcs.servers import ServerType

pytestmark = pytest.mark.unit


def _schema() -> dict:
    return json.loads(
        resources.files("testgen.common.odcs.schemas").joinpath("odcs-json-schema-v3.2.0.json").read_text()
    )


# Every key order this module exposes must be read off the pinned schema itself, not
# retyped by hand -- a schema bump that reorders or adds a key then fails here instead of
# silently changing everyone's diffs.
def test_root_key_order_matches_the_schemas_own_root_property_order():
    assert ROOT_KEY_ORDER == list(_schema()["properties"].keys())


def test_schema_key_order_matches_the_schemas_own_schemaobject_property_order():
    assert SCHEMA_KEY_ORDER == list(_schema()["$defs"]["SchemaObject"]["properties"].keys())


def test_property_key_order_matches_the_schemas_own_schemabaseproperty_property_order():
    assert PROPERTY_KEY_ORDER == list(_schema()["$defs"]["SchemaBaseProperty"]["properties"].keys())


def test_rule_key_order_matches_the_schemas_own_dataquality_property_order():
    assert RULE_KEY_ORDER == list(_schema()["$defs"]["DataQuality"]["properties"].keys())


def _full_root_document() -> dict:
    """One value per root key, so a canonical-order assertion has every key to reorder."""
    return {
        "version": "1.0.0",
        "kind": "DataContract",
        "apiVersion": "v3.2.0",
        "id": "contract-1",
        "name": "Customer contract",
        "tenant": "acme",
        "tags": ["pii"],
        "status": "active",
        "servers": [],
        "dataProduct": "customers",
        "description": {"purpose": "..."},
        "domain": "sales",
        "context": {},
        "schema": [],
        "support": [],
        "price": {},
        "team": [],
        "roles": [],
        "slaDefaultElement": "customers.id",
        "slaProperties": [],
        "authoritativeDefinitions": [],
        "customProperties": [],
        "contractCreatedTs": "2024-01-01T00:00:00Z",
    }


def test_root_keys_are_emitted_in_canonical_order_whatever_order_they_arrive_in():
    shuffled = dict(reversed(list(_full_root_document().items())))
    result = yaml.safe_load(serialize_document(shuffled))
    assert list(result.keys()) == ROOT_KEY_ORDER


def test_keys_the_order_does_not_name_follow_the_ones_it_does():
    # Unknowns keep their own relative order and land after every named key -- this is not
    # the same claim as "nothing is dropped": a serialiser that alphabetized unknown keys,
    # or interleaved them with known ones, would still pass a set-equality check but fail
    # this one.
    document = {
        "zzz_future_field": "z",
        "version": "1.0.0",
        "aaa_future_field": "a",
        "kind": "DataContract",
    }
    result_keys = list(yaml.safe_load(serialize_document(document)).keys())
    assert result_keys == ["version", "kind", "zzz_future_field", "aaa_future_field"]


def test_no_key_is_dropped():
    # The serialiser orders; it does not filter. Keys the order does not name, at every
    # nesting level (root, table, column, rule), must all survive -- dict equality ignores
    # key order, so this genuinely only checks presence/value, not ordering.
    document = {
        "version": "1.0.0",
        "futureRootField": "root-extra",
        "schema": [
            {
                "name": "customers",
                "futureTableField": "table-extra",
                "properties": [
                    {
                        "name": "email",
                        "futurePropertyField": "property-extra",
                        "quality": [
                            {"type": "text", "description": "not blank", "futureRuleField": "rule-extra"},
                        ],
                    }
                ],
                "quality": [
                    {"type": "text", "description": "at least one row", "futureRuleField": "rule-extra-2"},
                ],
            }
        ],
    }
    result = yaml.safe_load(serialize_document(document))
    assert result == document


def test_nested_schema_properties_and_rules_are_ordered_too():
    # Every nested dict is shuffled relative to its canonical order. If the serialiser only
    # reordered the root document and left nested dicts in whatever order they arrived in,
    # this would fail -- a bug the earlier, root-only ordering tests cannot catch.
    document = {
        "version": "1.0.0",
        "schema": [
            {
                "quality": [{"severity": "error", "type": "text", "id": "rule-table"}],
                "relationships": [],
                "properties": [
                    {
                        "quality": [{"severity": "warning", "type": "text", "id": "rule-column"}],
                        "unique": True,
                        "required": True,
                        "name": "email",
                        "logicalType": "string",
                    }
                ],
                "logicalType": "object",
                "name": "customers",
            }
        ],
    }
    result = yaml.safe_load(serialize_document(document))
    table = result["schema"][0]
    assert list(table.keys()) == ["name", "logicalType", "properties", "relationships", "quality"]
    column = table["properties"][0]
    assert list(column.keys()) == ["name", "logicalType", "required", "unique", "quality"]
    assert list(table["quality"][0].keys()) == ["id", "severity", "type"]
    assert list(column["quality"][0].keys()) == ["id", "severity", "type"]


def _term(**overrides) -> TestDefinition:
    defaults = {
        "test_type": "Required",
        "contract_term_id": "term-1",
        "column_name": "email",
        "table_name": "customers",
        "schema_name": "public",
        "threshold_value": "0",
    }
    defaults.update(overrides)
    return TestDefinition(**defaults)


def _test_type(test_type_code: str, **overrides) -> TestType:
    defaults = {
        "test_type": test_type_code,
        "dq_dimension": "Completeness",
        "test_name_short": "",
        "test_name_long": "",
    }
    defaults.update(overrides)
    return TestType(**defaults)


def _real_projected_rule() -> dict:
    # A hand-built rule dict is string keys by construction and proves nothing about what
    # project_rule actually emits -- this rule is the real projection, carrying both
    # DataQuality's own keys (id, dimension, customProperties, type) and library-shape keys
    # the ordering does not name (metric, unit, mustBeLessOrEqualTo), so the round trip
    # below exercises both branches of the ordering logic and would surface a leaked
    # StrEnum member from the real production code path, not a fixture built to avoid one.
    term = _term()
    return project_rule(term, _test_type("Required"), ServerType.POSTGRES)


def test_reserialising_a_parsed_document_is_byte_identical():
    document = {
        "schema": [
            {
                "properties": [
                    {
                        "name": "email",
                        "quality": [_real_projected_rule()],
                        "unknownColumnField": "kept",
                    }
                ],
                "name": "customers",
                "unknownTableField": "kept",
            }
        ],
        "unknownRootField": "kept",
        "kind": "DataContract",
        "version": "1.0.0",
    }
    once = serialize_document(document)
    assert serialize_document(yaml.safe_load(once)) == once


def test_a_multiline_query_stays_readable():
    query = "SELECT COUNT(*)\nFROM customers\nWHERE email IS NULL\n"
    document = {
        "version": "1.0.0",
        "schema": [{"name": "customers", "quality": [{"type": "sql", "query": query}]}],
    }
    output = serialize_document(document)
    assert "query: |" in output
    assert "\\n" not in output
    reloaded = yaml.safe_load(output)
    assert reloaded["schema"][0]["quality"][0]["query"] == query
