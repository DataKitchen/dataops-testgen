import pytest

from testgen.common.run_overrides import resolve_table_name, validate_table_name_map


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "mapping", "expected"),
    [
        ("orders", None, "orders"),
        ("orders", {}, "orders"),
        ("orders", {"orders": "build_orders"}, "build_orders"),
        ("orders", {"customers": "build_customers"}, "orders"),
        ("orders", {"*": "build_*"}, "build_orders"),
        ("orders", {"ord*": "staging_*"}, "staging_ers"),
        ("orders", {"*ers": "*ERS"}, "ordERS"),
        ("orders", {"o*s": "x_*_y"}, "x_rder_y"),
        ("orders", {"*": "fixed"}, "fixed"),
        ("aa", {"a*a": "<*>"}, "<>"),
        ("orders", {"ORDERS": "build_orders"}, "orders"),
        ("ORDERS", {"orders": "build_orders"}, "ORDERS"),
    ],
)
def test_resolve_table_name(name, mapping, expected):
    assert resolve_table_name(name, mapping) == expected


@pytest.mark.unit
def test_exact_key_wins_over_a_pattern_that_also_matches():
    mapping = {"*": "build_*", "orders": "orders_v2"}
    assert resolve_table_name("orders", mapping) == "orders_v2"
    assert resolve_table_name("customers", mapping) == "build_customers"


@pytest.mark.unit
def test_patterns_apply_in_the_order_given():
    """Insertion order decides which pattern wins, so the same keys in the other order differ."""
    first_wins = {"ord*": "a_*", "*ers": "b_*"}
    assert resolve_table_name("orders", first_wins) == "a_ers"

    reordered = {"*ers": "b_*", "ord*": "a_*"}
    assert resolve_table_name("orders", reordered) == "b_ord"


@pytest.mark.unit
@pytest.mark.parametrize("mapping", [None, {}, {"orders": "build_orders"}, {"*": "build_*"}, {"a*": "b*"}])
def test_validate_table_name_map_accepts(mapping):
    assert validate_table_name_map(mapping) is None


@pytest.mark.unit
def test_validate_table_name_map_rejects_more_than_one_star():
    assert validate_table_name_map({"a*b*": "x"}) == "Table name pattern `a*b*` can contain at most one `*`."


@pytest.mark.unit
def test_validate_table_name_map_names_the_offending_key():
    assert validate_table_name_map({"orders": "build_orders", "a*b*c": "x"}) == (
        "Table name pattern `a*b*c` can contain at most one `*`."
    )


@pytest.mark.unit
@pytest.mark.parametrize("missing", [None, ""])
def test_a_test_with_no_table_name_is_left_alone(missing):
    """A CUSTOM test carries no table name; its table is only an output label."""
    assert resolve_table_name(missing, {"*": "build_*"}) == missing


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        'x" ; DROP TABLE y --',
        "o'r",
        "back\\slash",
        "tick`",
        "nul\x00",
        "new\nline",
        "trailing\n",
        "semi;colon",
        "equals=sign",
        "",
        "   ",
        "a" * 101,
    ],
)
def test_validate_table_name_map_rejects_a_value_that_cannot_name_a_table(value):
    """Values reach a table reference and an app-database lookup as text, as a schema override
    does, so they are held to the same shape. ``;`` and ``=`` are excluded on top of that: a
    result records the table it read among its input parameters, whose ``name=value`` pairs are
    joined by ``;``, and a name holding one reads back truncated at it."""
    assert validate_table_name_map({"orders": value}) is not None


@pytest.mark.unit
@pytest.mark.parametrize("value", ["build_orders", "build_*", "Orders 2026", "a" * 100])
def test_validate_table_name_map_accepts_a_usable_value(value):
    assert validate_table_name_map({"orders": value}) is None
