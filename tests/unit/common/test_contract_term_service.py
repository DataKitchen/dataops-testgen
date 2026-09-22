import re

import pytest

from testgen.common.contract_term_service import TERM_ID_MAX_LENGTH, slugify_term_id

pytestmark = pytest.mark.unit

TERM_ID_PATTERN = r"^[A-Za-z0-9_-]+$"


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Row_Ct", "public", "orders", "order_id"), "Row_Ct-public-orders-order_id"),
        # A metric-trend term carries a display label, not a column name.
        (
            ("Metric_Trend", "public", "orders", "Average Product Price"),
            "Metric_Trend-public-orders-Average_Product_Price",
        ),
        # An aggregate-balance term carries an expression.
        (
            ("Aggregate_Balance", "public", "orders", "SUM(total_amount)"),
            "Aggregate_Balance-public-orders-SUM_total_amount",
        ),
        (("Volume_Trend", "public", "orders", None), "Volume_Trend-public-orders"),
        (("Schema_Drift", "public", None, None), "Schema_Drift-public"),
        (("Row_Ct", "public", "orders", "  spaced  out  "), "Row_Ct-public-orders-spaced_out"),
        (("Row_Ct", "public", "orders", "a//b\\c"), "Row_Ct-public-orders-a_b_c"),
        # Non-ASCII is dropped rather than transliterated: no dependency, and the identity is
        # kept unique by its index rather than by being readable.
        (("Row_Ct", "public", "orders", "çafé"), "Row_Ct-public-orders-af"),
        (("Row_Ct", "public", "orders", "already-valid_1"), "Row_Ct-public-orders-already-valid_1"),
    ],
)
def test_slugify_produces_the_expected_identity(parts, expected):
    assert slugify_term_id(*parts) == expected


@pytest.mark.parametrize(
    "parts",
    [
        ("Row_Ct", "public", "orders", "order_id"),
        ("Metric_Trend", "public", "orders", "Average Product Price"),
        ("Aggregate_Balance", "public", "orders", "SUM(total_amount)"),
        ("Row_Ct", "public", "orders", "!!!"),
        ("Row_Ct", "public", "orders", "çafé"),
        ("Row_Ct", "public", "orders", "a" * 300),
    ],
)
def test_every_slug_matches_the_odcs_identifier_pattern(parts):
    assert re.match(TERM_ID_PATTERN, slugify_term_id(*parts))


def test_a_slug_is_bounded_to_the_column_width():
    slug = slugify_term_id("Row_Ct", "public", "o" * 200, "c" * 200)

    assert len(slug) <= TERM_ID_MAX_LENGTH
    assert re.match(TERM_ID_PATTERN, slug)


def test_separators_do_not_repeat_or_dangle():
    assert slugify_term_id("Row_Ct", "", "orders", "  ") == "Row_Ct-orders"


def test_repeated_invalid_characters_collapse():
    assert slugify_term_id("Row_Ct", "public", "orders", "a???b") == "Row_Ct-public-orders-a_b"


def test_an_input_that_slugs_to_nothing_raises():
    with pytest.raises(ValueError):
        slugify_term_id("!!!", None, None, None)


def test_no_parts_at_all_raises():
    with pytest.raises(ValueError):
        slugify_term_id()


def test_two_keys_that_differ_only_past_the_cut_slug_differently():
    """The slug is the term's identity in a unique index, so a truncation that collapses two
    natural keys into one string makes the second term's stamp fail the index.
    """
    schema, table = "analytics_prod", "customer_subscription_billing_events"
    net = slugify_term_id("Value_Match", schema, table, "monthly_recurring_revenue_usd_amount_net")
    gross = slugify_term_id("Value_Match", schema, table, "monthly_recurring_revenue_usd_amount_gross")

    assert net != gross
    assert len(net) <= TERM_ID_MAX_LENGTH
    assert len(gross) <= TERM_ID_MAX_LENGTH
    assert re.match(TERM_ID_PATTERN, net)
    assert re.match(TERM_ID_PATTERN, gross)


def test_a_truncated_slug_is_still_a_pure_function_of_the_key():
    # The identity has to survive a freeze, so the same key must slug the same way every time.
    parts = ("Value_Match", "analytics_prod", "customer_subscription_billing_events", "c" * 80)
    assert slugify_term_id(*parts) == slugify_term_id(*parts)


def test_a_key_that_fits_is_not_given_a_digest():
    assert slugify_term_id("Row_Ct", "public", "orders", "order_id") == "Row_Ct-public-orders-order_id"
