from types import SimpleNamespace
from unittest.mock import patch

import pytest

from testgen.common.table_filter_validation import (
    InvalidTableFilters,
    TableFiltersUnchecked,
    normalize_table_filters,
    table_filter_errors,
    validate_table_filters,
)

pytestmark = pytest.mark.unit

SESSION = "testgen.common.table_filter_validation.target_db_session"


def test_normalize_trims_and_drops_blank_entries():
    value = [
        {"table_name": " orders ", "condition": " region = 'EMEA' "},
        {"table_name": "", "condition": ""},
        {"table_name": None, "condition": None},
    ]
    assert normalize_table_filters(value) == [{"table_name": "orders", "condition": "region = 'EMEA'"}]


@pytest.mark.parametrize("value", [None, [], [{"table_name": " ", "condition": ""}]])
def test_normalize_stores_no_filters_as_none(value):
    assert normalize_table_filters(value) is None


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ([{"table_name": "orders", "condition": " "}], "Enter a filter condition for table orders."),
        ([{"table_name": "", "condition": "a = 1"}], "Each table filter needs a table name."),
        (
            [{"table_name": "orders", "condition": "a = 1"}, {"table_name": "orders ", "condition": "b = 2"}],
            "Table orders has more than one filter.",
        ),
    ],
)
def test_normalize_rejects_incomplete_or_duplicate_entries(value, message):
    with pytest.raises(InvalidTableFilters, match=f"^{message}$"):
        normalize_table_filters(value)


def test_normalize_reports_every_problem_once():
    value = [
        {"table_name": "orders", "condition": ""},
        {"table_name": "", "condition": "a = 1"},
        {"table_name": "", "condition": "b = 2"},
        {"table_name": "returns", "condition": "a = 1"},
        {"table_name": "returns", "condition": "b = 2"},
    ]
    with pytest.raises(InvalidTableFilters) as raised:
        normalize_table_filters(value)

    assert raised.value.messages == [
        "Enter a filter condition for table orders.",
        "Each table filter needs a table name.",
        "Table returns has more than one filter.",
    ]


def _connection():
    return SimpleNamespace(sql_flavor="postgresql", sql_flavor_code="postgresql")


def _runner(failing: str | None = None):
    queries = []

    def run(query, _params=None):
        queries.append(query)
        if failing and f'"{failing}"' in query:
            raise RuntimeError('ERROR: column "regoin" does not exist\nLINE 1: ...')
        return []

    return run, queries


def test_errors_read_one_record_of_each_table_through_its_filter():
    table_group = SimpleNamespace(table_group_schema="sales")
    value = [
        {"table_name": "orders", "condition": "region = 'EMEA'"},
        {"table_name": "returns", "condition": "id IN (SELECT id FROM {DATA_SCHEMA}.keep)"},
    ]
    run, queries = _runner()

    assert table_filter_errors(run, _connection(), table_group, value) == {}
    assert queries == [
        """SELECT  1 AS checked FROM (SELECT * FROM "sales"."orders" WHERE (region = 'EMEA')) "orders" LIMIT 1""",
        'SELECT  1 AS checked FROM (SELECT * FROM "sales"."returns" WHERE (id IN (SELECT id FROM sales.keep))) '
        '"returns" LIMIT 1',
    ]


def test_errors_collect_every_failing_filter_with_its_database_error():
    table_group = SimpleNamespace(table_group_schema="sales")
    value = [
        {"table_name": "orders", "condition": "regoin = 1"},
        {"table_name": "returns", "condition": "kept = 1"},
    ]
    run, queries = _runner(failing="orders")

    assert table_filter_errors(run, _connection(), table_group, value) == {
        "orders": 'ERROR: column "regoin" does not exist',
    }
    assert len(queries) == 2


def test_validate_reports_the_database_error_for_the_first_failing_table():
    table_group = SimpleNamespace(table_group_schema="sales")
    run, _ = _runner(failing="orders")
    with (
        patch(SESSION) as session,
        pytest.raises(
            InvalidTableFilters,
            match='^The filter for table orders is not valid: ERROR: column "regoin" does not exist$',
        ),
    ):
        session.return_value.__enter__.return_value = run
        validate_table_filters(_connection(), table_group, [{"table_name": "orders", "condition": "regoin = 1"}])


def test_validate_opens_no_session_without_filters():
    with patch(SESSION) as session:
        validate_table_filters(_connection(), SimpleNamespace(table_group_schema="sales"), None)

    session.assert_not_called()


def test_validate_reports_an_unreachable_target_as_unchecked_filters():
    # A connection failure is not a fault in the filters, so it raises its own exception type
    with (
        patch(SESSION, side_effect=ConnectionRefusedError("connection refused")),
        pytest.raises(TableFiltersUnchecked, match="^The table filters could not be checked: connection refused$"),
    ):
        validate_table_filters(
            _connection(), SimpleNamespace(table_group_schema="sales"), [{"table_name": "orders", "condition": "a = 1"}]
        )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "000904 (42000): SQL compilation error:\nerror line 1 at position 61\ninvalid identifier 'REGOIN'",
            "000904 (42000): SQL compilation error: error line 1 at position 61 invalid identifier 'REGOIN'",
        ),
        (
            'column "regoin" does not exist\nLINE 1: SELECT  1 AS checked FROM (SELECT * FROM "sales"."orders" WHERE (regoin = 1)...\n'
            "                                                                     ^\n"
            'HINT:  Perhaps you meant to reference the column "orders.region".\n',
            'column "regoin" does not exist HINT:  Perhaps you meant to reference the column "orders.region".',
        ),
        ("", "RuntimeError"),
        ("\n  \n", "RuntimeError"),
    ],
    ids=["multi-line", "postgres-position-lines", "empty", "blank"],
)
def test_errors_keep_the_whole_database_message_on_one_line(message, expected):
    def run(_query, _params=None):
        raise RuntimeError(message)

    errors = table_filter_errors(
        run, _connection(), SimpleNamespace(table_group_schema="sales"), [{"table_name": "orders", "condition": "a = 1"}]
    )

    assert errors == {"orders": expected}
