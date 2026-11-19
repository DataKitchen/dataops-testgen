"""Tests for the Validate button in the Add/Edit Test dialog, testgen.ui.views.test_definitions.validate_test."""

from unittest.mock import MagicMock, patch

import pytest

from testgen.ui.views import test_definitions as view

pytestmark = pytest.mark.unit

TABLE_GROUP_GET = "testgen.common.custom_test_validation.TableGroup.get"


def test_condition_flag_validation_substitutes_data_schema():
    connection = MagicMock(sql_flavor="postgresql", sql_flavor_code="postgresql")
    test_definition = {
        "test_type": "Condition_Flag",
        "schema_name": "sales",
        "table_name": "orders",
        "custom_query": "cust_id NOT IN (SELECT id FROM {DATA_SCHEMA}.customers)",
    }

    with (
        patch.object(view, "get_connection", return_value=connection),
        patch.object(view, "fetch_from_target_db") as fetch,
        patch(TABLE_GROUP_GET, return_value=MagicMock(table_filters=None)),
    ):
        view.validate_test(test_definition, MagicMock())

    query = fetch.call_args.args[1]
    assert "cust_id NOT IN (SELECT id FROM sales.customers)" in query
    assert "{DATA_SCHEMA}" not in query
    assert query.rstrip().endswith('FROM "sales"."orders";')


def test_condition_flag_validation_reads_through_the_table_filter():
    connection = MagicMock(sql_flavor="postgresql", sql_flavor_code="postgresql")
    test_definition = {
        "test_type": "Condition_Flag", "schema_name": "sales", "table_name": "orders", "custom_query": "amount < 0",
    }
    table_group = MagicMock(table_filters=[{"table_name": "orders", "condition": "region = 'EMEA'"}])

    with (
        patch.object(view, "get_connection", return_value=connection),
        patch.object(view, "fetch_from_target_db") as fetch,
        patch(TABLE_GROUP_GET, return_value=table_group),
    ):
        view.validate_test(test_definition, MagicMock())

    assert """FROM (SELECT * FROM "sales"."orders" WHERE (region = 'EMEA')) "orders";""" in fetch.call_args.args[1]
