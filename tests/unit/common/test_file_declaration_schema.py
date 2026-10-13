"""Tests for the file declaration as a request and response field."""

import pytest
from pydantic import ValidationError

from testgen.common.enums import FileFormat
from testgen.common.file_declaration_schema import FileDeclarationSpec, declarations_from_payload

pytestmark = pytest.mark.unit


def test_to_payload_gathers_the_csv_settings_that_are_set():
    spec = FileDeclarationSpec(name="orders", uri="sales/*.csv", format="csv", delimiter="|", header=False)

    assert spec.to_payload() == {
        "name": "orders",
        "uri": "sales/*.csv",
        "format": "csv",
        "options": {"delimiter": "|", "header": False},
    }


def test_to_payload_stores_no_options_for_another_format():
    spec = FileDeclarationSpec(name="products", uri="catalog/products.json", format="json")

    assert spec.to_payload()["options"] == {}


def test_csv_settings_are_rejected_on_another_format():
    with pytest.raises(ValidationError, match="delimiter applies to a CSV file"):
        FileDeclarationSpec(name="orders", uri="orders.parquet", format="parquet", delimiter="|")


def test_a_stored_declaration_reads_back_as_written():
    spec = FileDeclarationSpec(name="orders", uri="sales/*.csv", format="csv", delimiter="|", quote='"')

    assert [declaration.model_dump() for declaration in declarations_from_payload([spec.to_payload()])] == [
        spec.model_dump()
    ]


def test_the_ui_shape_without_options_reads_back():
    stored = [{"name": "claims", "uri": "claims.parquet", "format": "parquet"}]

    [declaration] = declarations_from_payload(stored)

    assert declaration.format is FileFormat.PARQUET
    assert (declaration.delimiter, declaration.header, declaration.quote, declaration.escape) == (None,) * 4


def test_a_stored_value_a_write_would_refuse_is_still_shown():
    stored = [{"name": "claims", "uri": "claims.csv", "format": "csv", "options": {"quote": "ab"}}]

    [declaration] = declarations_from_payload(stored)

    assert declaration.quote == "ab"


def test_settings_stored_on_another_format_are_not_shown():
    stored = [{"name": "claims", "uri": "claims.json", "format": "json", "options": {"delimiter": "|"}}]

    [declaration] = declarations_from_payload(stored)

    assert declaration.delimiter is None


def test_a_format_testgen_cannot_read_is_skipped():
    stored = [
        {"name": "claims", "uri": "claims.xlsx", "format": "xlsx"},
        {"name": "orders", "uri": "orders.csv", "format": "csv"},
    ]

    assert [declaration.name for declaration in declarations_from_payload(stored)] == ["orders"]


def test_no_stored_declarations_read_as_an_empty_list():
    assert declarations_from_payload(None) == []


def test_the_requested_model_is_built():
    class Subclass(FileDeclarationSpec):
        pass

    [declaration] = declarations_from_payload([{"name": "orders", "uri": "orders.csv", "format": "csv"}], Subclass)

    assert type(declaration) is Subclass
