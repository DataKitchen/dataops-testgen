import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from testgen.common.clean_sql import escape_bind_colons
from testgen.common.database.database_service import replace_params
from testgen.common.table_filters import (
    filtered_table_ref,
    parse_table_filters,
    table_filter_condition,
    table_filter_params,
)

FILTERS = [
    {"table_name": "orders", "condition": "region = 'EMEA'"},
    {"table_name": "Orders", "condition": "region = 'APAC'"},
    {"table_name": "customers", "condition": "  "},
    {"table_name": "", "condition": "x = 1"},
]


def test_parse_skips_entries_without_table_or_condition():
    assert [(f.table_name, f.condition) for f in parse_table_filters(FILTERS)] == [
        ("orders", "region = 'EMEA'"),
        ("Orders", "region = 'APAC'"),
    ]


def test_parse_handles_no_filters():
    assert parse_table_filters(None) == []


def test_condition_matches_table_name_exactly():
    assert table_filter_condition(FILTERS, "orders") == "region = 'EMEA'"
    assert table_filter_condition(FILTERS, "Orders") == "region = 'APAC'"
    assert table_filter_condition(FILTERS, "ORDERS") is None
    assert table_filter_condition(FILTERS, "customers") is None
    assert table_filter_condition(FILTERS, None) is None


def test_case_fallback_uses_the_one_filter_differing_only_in_case():
    filters = [{"table_name": "Orders", "condition": "region = 'APAC'"}]

    assert table_filter_condition(filters, "orders") is None
    assert table_filter_condition(filters, "orders", case_fallback=True) == "region = 'APAC'"
    assert table_filter_condition(filters, "returns", case_fallback=True) is None


def test_case_fallback_prefers_an_exact_match_and_skips_an_ambiguous_one():
    assert table_filter_condition(FILTERS, "Orders", case_fallback=True) == "region = 'APAC'"
    assert table_filter_condition(FILTERS, "ORDERS", case_fallback=True) is None


def test_unfiltered_params_leave_the_table_ref_unchanged():
    template = 'SELECT COUNT(*) FROM {TABLE_FILTER_OPEN}"s"."orders"{TABLE_FILTER_CLOSE} WHERE x > 0'
    params = table_filter_params(None, "orders", "s", '"')

    assert replace_params(template, params) == 'SELECT COUNT(*) FROM "s"."orders" WHERE x > 0'


def test_filtered_params_read_a_derived_table_aliased_by_the_table_name():
    template = 'SELECT COUNT(*) FROM {TABLE_FILTER_OPEN}"s"."orders"{TABLE_FILTER_CLOSE} WHERE x > 0'
    params = table_filter_params("region = 'EMEA'", "orders", "s", '"')

    assert replace_params(template, params) == (
        "SELECT COUNT(*) FROM (SELECT * FROM \"s\".\"orders\" WHERE (region = 'EMEA')) \"orders\" WHERE x > 0"
    )


def test_unaliased_close_leaves_the_alias_to_the_template():
    template = "SELECT a.x FROM {MATCH_TABLE_FILTER_OPEN}`s`.`orders`{MATCH_TABLE_FILTER_CLOSE_UNALIASED} a"
    params = table_filter_params("x > 1", "orders", "s", "`", prefix="MATCH_")

    assert replace_params(template, params) == "SELECT a.x FROM (SELECT * FROM `s`.`orders` WHERE (x > 1)) a"


def test_condition_expands_data_schema():
    params = table_filter_params("id IN (SELECT id FROM {DATA_SCHEMA}.keep)", "orders", "sales", '"')

    assert params["TABLE_FILTER_CLOSE"] == ' WHERE (id IN (SELECT id FROM sales.keep))) "orders"'


def test_condition_text_is_not_expanded_as_a_parameter():
    template = "FROM {TABLE_FILTER_OPEN}t{TABLE_FILTER_CLOSE_UNALIASED} WHERE {SUBSET_CONDITION}"
    params = {**table_filter_params("note = '{SUBSET_CONDITION}'", "t", "s", '"'), "SUBSET_CONDITION": "1=1"}

    assert replace_params(template, params) == "FROM (SELECT * FROM t WHERE (note = '{SUBSET_CONDITION}')) WHERE 1=1"


def test_filtered_table_ref():
    assert filtered_table_ref('"s"."t"', None, "s", '"t"') == '"s"."t"'
    assert filtered_table_ref('"s"."t"', "a = 1", "s", '"t"') == '(SELECT * FROM "s"."t" WHERE (a = 1)) "t"'
    assert filtered_table_ref('"s"."t"', "a = 1", "s", None) == '(SELECT * FROM "s"."t" WHERE (a = 1))'


@pytest.mark.parametrize(
    "sql",
    [
        "code = ':EU' AND note = ' :x'",
        "REGEXP_LIKE(addr, '[[:space:]][[:alnum:]_]')",
        "payload['a']:type::string = 'x'",
        "ts < '2026-01-01 10:30:00' AND n::int > 0",
        "a = '\\:c'",
    ],
)
def test_escaped_colons_reach_the_database_as_written(sql):
    rendered = str(text(escape_bind_colons(sql)).compile(dialect=postgresql.dialect()))

    assert rendered == sql


def test_condition_colons_are_escaped_unless_the_caller_escapes_the_query():
    escaped = table_filter_params("code = ':EU'", "t", "s", '"')
    raw = table_filter_params("code = ':EU'", "t", "s", '"', escape_colons=False)

    assert escaped["TABLE_FILTER_CLOSE_UNALIASED"] == " WHERE (code = '\\:EU'))"
    assert raw["TABLE_FILTER_CLOSE_UNALIASED"] == " WHERE (code = ':EU'))"
    assert filtered_table_ref("t", "code = ':EU'", "s", None) == "(SELECT * FROM t WHERE (code = '\\:EU'))"
    assert filtered_table_ref("t", "code = ':EU'", "s", None, escape_colons=False) == (
        "(SELECT * FROM t WHERE (code = ':EU'))"
    )
