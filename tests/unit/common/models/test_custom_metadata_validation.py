"""Tests for the reserved ``odcs`` subtree inside ``custom_metadata``, validated at save."""

import pytest

from testgen.common.models.test_definition import validate_custom_metadata

pytestmark = pytest.mark.unit


def test_a_dimension_outside_the_odcs_enum_is_refused():
    # "validity" is TestGen's own most-used quality dimension, and it is not a valid ODCS
    # dimension (ODCS uses "conformity" instead) -- exactly the value a user is likely to type.
    assert validate_custom_metadata({"odcs": {"dimension": "validity"}})


def test_a_translated_dimension_is_accepted():
    assert validate_custom_metadata({"odcs": {"dimension": "conformity"}}) is None


def test_tags_must_be_a_list_of_strings():
    assert validate_custom_metadata({"odcs": {"tags": ["finance", "sensitive"]}}) is None
    assert validate_custom_metadata({"odcs": {"tags": "finance"}})
    assert validate_custom_metadata({"odcs": {"tags": ["finance", 1]}})


def test_custom_properties_entries_must_carry_a_property_and_a_value():
    assert validate_custom_metadata(
        {"odcs": {"customProperties": [{"property": "vendor", "value": "acme"}]}}
    ) is None
    assert validate_custom_metadata({"odcs": {"customProperties": [{"property": "vendor"}]}})
    assert validate_custom_metadata({"odcs": {"customProperties": [{"value": "acme"}]}})
    assert validate_custom_metadata({"odcs": {"customProperties": "not-a-list"}})


def test_custom_property_entries_accept_their_optional_fields():
    # The pinned schema's CustomProperty item allows id/description/vendor beyond
    # property/value -- all five, together, must still be accepted.
    assert validate_custom_metadata(
        {"odcs": {"customProperties": [
            {"id": "cp1", "property": "vendor", "value": "acme", "description": "d", "vendor": "testgen"}
        ]}}
    ) is None


def test_a_stray_key_inside_a_custom_property_entry_is_refused():
    # The item object is sealed (`additionalProperties: false`) in the pinned schema: a term
    # carrying this would save cleanly here and then block its contract version's freeze.
    assert validate_custom_metadata(
        {"odcs": {"customProperties": [{"property": "vendor", "value": "acme", "stray": "z"}]}}
    )


@pytest.mark.parametrize("bad_id", ["has spaces", "a.b", "a#b", "a/b", "a\\b", "a@b", "a!b", "a%b", "a&b", "a^b"])
def test_a_custom_property_id_that_violates_stable_id_is_refused(bad_id):
    # CustomProperty.id is a $ref to StableId (`^[^\s.#/\\@!%&^]+$`) in the pinned schema: a
    # non-conforming id, same as a stray key, saves cleanly here and breaks the freeze later.
    assert validate_custom_metadata(
        {"odcs": {"customProperties": [{"property": "vendor", "value": "acme", "id": bad_id}]}}
    )


def test_a_conforming_custom_property_id_is_accepted():
    assert validate_custom_metadata(
        {"odcs": {"customProperties": [{"property": "vendor", "value": "acme", "id": "cp-1"}]}}
    ) is None


def test_authoritative_definitions_entries_must_carry_a_url_and_a_type():
    assert validate_custom_metadata(
        {"odcs": {"authoritativeDefinitions": [{"url": "https://example.com/policy", "type": "glossary"}]}}
    ) is None
    assert validate_custom_metadata({"odcs": {"authoritativeDefinitions": [{"url": "https://example.com/policy"}]}})
    assert validate_custom_metadata({"odcs": {"authoritativeDefinitions": [{"type": "glossary"}]}})
    assert validate_custom_metadata({"odcs": {"authoritativeDefinitions": "not-a-list"}})


def test_authoritative_definition_entries_accept_their_optional_fields():
    assert validate_custom_metadata(
        {"odcs": {"authoritativeDefinitions": [
            {"id": "ad1", "url": "https://example.com/policy", "type": "glossary", "description": "d"}
        ]}}
    ) is None


def test_a_stray_key_inside_an_authoritative_definition_entry_is_refused():
    # Same sealed-item risk as customProperties, on the field the reserved-subtree
    # docstring used to describe as having "no stated constraint" -- it does now.
    assert validate_custom_metadata(
        {"odcs": {"authoritativeDefinitions": [
            {"url": "https://example.com/policy", "type": "glossary", "bogus": 1}
        ]}}
    )


@pytest.mark.parametrize("bad_id", ["has spaces", "a.b", "a#b", "a/b", "a\\b", "a@b", "a!b", "a%b", "a&b", "a^b"])
def test_an_authoritative_definition_id_that_violates_stable_id_is_refused(bad_id):
    # AuthoritativeDefinitions[].id is the same StableId $ref as CustomProperty.id.
    assert validate_custom_metadata(
        {"odcs": {"authoritativeDefinitions": [
            {"url": "https://example.com/policy", "type": "glossary", "id": bad_id}
        ]}}
    )


def test_a_conforming_authoritative_definition_id_is_accepted():
    assert validate_custom_metadata(
        {"odcs": {"authoritativeDefinitions": [
            {"url": "https://example.com/policy", "type": "glossary", "id": "ad-1"}
        ]}}
    ) is None


@pytest.mark.parametrize("field", ["name", "businessImpact", "method", "schedule", "scheduler"])
def test_string_only_fields_reject_non_strings_and_accept_strings(field):
    assert validate_custom_metadata({"odcs": {field: "some text"}}) is None
    assert validate_custom_metadata({"odcs": {field: 123}})
    assert validate_custom_metadata({"odcs": {field: ["some text"]}})
    assert validate_custom_metadata({"odcs": {field: {"nested": "object"}}})


def test_an_unrecognised_key_inside_the_reserved_subtree_is_accepted():
    # Not emitted at render; refusing it would break a document written by a newer version.
    assert validate_custom_metadata({"odcs": {"somethingNewer": 1}}) is None


def test_the_reserved_subtree_must_be_an_object():
    assert validate_custom_metadata({"odcs": "conformity"})


def test_a_users_own_keys_are_still_accepted():
    assert validate_custom_metadata({"owner_team": "payments"}) is None
