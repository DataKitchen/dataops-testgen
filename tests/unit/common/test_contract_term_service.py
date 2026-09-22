import itertools
import re

import pytest

from testgen.common.contract_term_service import TERM_ID_MAX_LENGTH, slugify_term_id

pytestmark = pytest.mark.unit

TERM_ID_PATTERN = r"^[A-Za-z0-9_-]+$"
DIGEST_SUFFIX = re.compile(r"-[0-9a-f]{8}$")


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Row_Ct", "public", "orders", "order_id"), "Row_Ct-public-orders-order_id"),
        (("Volume_Trend", "public", "orders", None), "Volume_Trend-public-orders"),
        (("Schema_Drift", "public", None, None), "Schema_Drift-public"),
    ],
)
def test_a_key_the_slug_renders_exactly_keeps_the_readable_identity(parts, expected):
    assert slugify_term_id(*parts) == expected


@pytest.mark.parametrize(
    ("parts", "stem"),
    [
        # A metric-trend term carries a display label, not a column name.
        (("Metric_Trend", "public", "orders", "Average Product Price"),
         "Metric_Trend-public-orders-Average_Product_Price"),
        # An aggregate-balance term carries an expression.
        (("Aggregate_Balance", "public", "orders", "SUM(total_amount)"),
         "Aggregate_Balance-public-orders-SUM_total_amount"),
        (("Row_Ct", "public", "orders", "  spaced  out  "), "Row_Ct-public-orders-spaced_out"),
        (("Row_Ct", "public", "orders", "a//b\\c"), "Row_Ct-public-orders-a_b_c"),
        # Non-ASCII is dropped rather than transliterated: no dependency, and the identity is
        # kept unique by its index rather than by being readable.
        (("Row_Ct", "public", "orders", "çafé"), "Row_Ct-public-orders-af"),
        # A '-' inside a part is indistinguishable from the one joining parts.
        (("Row_Ct", "public", "orders", "already-valid_1"), "Row_Ct-public-orders-already-valid_1"),
        # An absent part in the middle shifts the ones after it.
        (("Row_Ct", None, "orders", "order_id"), "Row_Ct-orders-order_id"),
    ],
)
def test_a_key_the_slug_reduces_carries_a_digest(parts, stem):
    slug = slugify_term_id(*parts)

    assert slug.startswith(f"{stem}-")
    assert DIGEST_SUFFIX.search(slug)


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


def test_an_input_that_slugs_to_nothing_raises():
    with pytest.raises(ValueError):
        slugify_term_id("!!!", None, None, None)


def test_no_parts_at_all_raises():
    with pytest.raises(ValueError):
        slugify_term_id()


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # A run of disallowed characters collapses to one '_', whatever it was.
        (("Row_Ct", "public", "orders", "order id"), ("Row_Ct", "public", "orders", "order_id")),
        (("Row_Ct", "public", "orders", "total (usd)"), ("Row_Ct", "public", "orders", "total%usd")),
        (("Row_Ct", "public", "orders", "a  b"), ("Row_Ct", "public", "orders", "a??b")),
        # The join separator is lossy independently of that.
        (("Row_Ct", "sales", "q1-2026", "net"), ("Row_Ct", "sales", "q1", "2026-net")),
        # So is dropping an absent part.
        (("Row_Ct", "public", "orders", None), ("Row_Ct", "public", None, "orders")),
        # And so is the bound.
        (("Value_Match", "analytics_prod", "customer_subscription_billing_events",
          "monthly_recurring_revenue_usd_amount_net"),
         ("Value_Match", "analytics_prod", "customer_subscription_billing_events",
          "monthly_recurring_revenue_usd_amount_gross")),
    ],
)
def test_keys_the_slug_maps_onto_one_string_stay_distinct(left, right):
    """The identity sits in a unique index, so two natural keys the reduction cannot tell apart
    would make the second term's stamp fail it and wedge the contract permanently.
    """
    assert slugify_term_id(*left) != slugify_term_id(*right)


def _adversarial_keys() -> set[tuple[str | None, ...]]:
    """Keys spanning every way the reduction loses information, and their near misses."""
    alphabet = ["a", "b", "_", "-", " ", "%", None, "a_b", "a-b", "a b", "__", "--", " a "]
    long_part = "z" * 45
    keys = {("Row_Ct", *combo) for combo in itertools.product(alphabet, repeat=3)}
    keys |= {
        ("Value_Match", *combo, None)
        for combo in itertools.product([long_part, long_part + "x", long_part + "-", long_part + " "], repeat=2)
    }
    return keys


def test_distinct_keys_never_share_an_identity():
    slugs = {}
    for key in _adversarial_keys():
        try:
            slug = slugify_term_id(*key)
        except ValueError:
            continue
        assert slug not in slugs, f"{key} and {slugs[slug]} both slug to {slug}"
        slugs[slug] = key

    assert len(slugs) > 2000, "the corpus stopped covering the key space"


def test_every_adversarial_key_stays_within_the_column_and_the_pattern():
    for key in _adversarial_keys():
        try:
            slug = slugify_term_id(*key)
        except ValueError:
            continue
        assert len(slug) <= TERM_ID_MAX_LENGTH, f"{key} slugs past the column width"
        assert re.match(TERM_ID_PATTERN, slug), f"{key} slugs outside the identifier pattern"


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Row_Ct", "public", "orders", "order_id"), "Row_Ct-public-orders-order_id"),
        (("Row_Ct", "public", "orders", "order id"), "Row_Ct-public-orders-order_id-ee41a2af"),
        (("Metric_Trend", "public", "orders", "Average Product Price"),
         "Metric_Trend-public-orders-Average_Product_Price-3ef06dea"),
    ],
)
def test_an_identity_is_pinned_to_its_key(parts, expected):
    """A stamped identity is never recomputed, and a frozen document carries it, so a change to
    what a key slugs to splits terms stamped before it from terms stamped after.
    """
    assert slugify_term_id(*parts) == expected
