"""Tests for the shared flavor-identity source of truth."""

import pytest

from testgen.common.flavors import (
    FLAVOR_CODE_TO_FAMILY,
    FLAVOR_CODE_TO_LABEL,
    SqlFlavorLabel,
)

pytestmark = pytest.mark.unit


def test_label_and_family_maps_cover_the_same_codes():
    assert set(FLAVOR_CODE_TO_LABEL) == set(FLAVOR_CODE_TO_FAMILY)


def test_every_label_is_a_known_enum_member():
    assert set(FLAVOR_CODE_TO_LABEL.values()) == set(SqlFlavorLabel)


def test_labels_are_unique_per_code():
    labels = list(FLAVOR_CODE_TO_LABEL.values())
    assert len(labels) == len(set(labels))


def test_azure_variants_share_the_mssql_family():
    assert FLAVOR_CODE_TO_FAMILY["azure_mssql"] == "mssql"
    assert FLAVOR_CODE_TO_FAMILY["synapse_mssql"] == "mssql"
    assert FLAVOR_CODE_TO_FAMILY["mssql"] == "mssql"


def test_label_renders_as_plain_string():
    assert f"{FLAVOR_CODE_TO_LABEL['postgresql']}" == "PostgreSQL"
    assert str(FLAVOR_CODE_TO_LABEL["azure_mssql"]) == "Azure SQL Database"
