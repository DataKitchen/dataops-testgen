from itertools import permutations

import pytest

from testgen.common.run_overrides import (
    OVERRIDE_LABELS,
    labelled_overrides,
    overrides_from_kwargs,
    resolve_table_name,
    validate_table_name_map,
)


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
def test_the_most_specific_pattern_wins():
    """A catch-all alongside a narrower pattern maps only what the narrower one leaves."""
    mapping = {"orders_*": "archive_*", "*": "build_*"}

    assert resolve_table_name("orders_2024", mapping) == "archive_2024"
    assert resolve_table_name("customers", mapping) == "build_customers"


def test_the_same_patterns_resolve_the_same_way_however_they_are_written():
    """The map reaches the run through a JSONB column, which orders an object's keys itself, so a
    result that depended on how the caller wrote them would not survive being queued."""
    pairs = [("ord*", "a_*"), ("*ers", "b_*"), ("o*s", "c_*")]
    resolved = {resolve_table_name("orders", dict(order)) for order in permutations(pairs)}

    assert len(resolved) == 1


def test_a_longer_pattern_wins_from_either_side_of_the_name():
    """Specificity counts the characters outside the `*`, wherever in the key they sit."""
    assert resolve_table_name("tt_orders_pass", {"tt_orders_*": "a_*", "tt_*": "b_*"}) == "a_pass"
    assert resolve_table_name("tt_orders_pass", {"*_orders_pass": "a_*", "*_pass": "b_*"}) == "a_tt"


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
@pytest.mark.parametrize("value", ["build_orders", "Orders 2026", "a" * 100])
def test_validate_table_name_map_accepts_a_usable_value(value):
    assert validate_table_name_map({"orders": value}) is None


@pytest.mark.unit
def test_validate_table_name_map_rejects_a_star_in_a_value_whose_key_has_none():
    """A `*` in a value stands for what the key's `*` matched, so an exact key leaves it with
    nothing to stand for and it would reach SQL as a literal `*`."""
    assert validate_table_name_map({"orders": "build_*"}) == (
        "Table name `build_*` can only contain `*` when its key `orders` does."
    )


@pytest.mark.unit
def test_a_pattern_that_expands_to_nothing_is_an_error():
    """`orders` matches `orders*` with nothing in place of the `*`, so the value expands to an
    empty name. Returning it would fall back to the test's own table and read the table group
    while the run reports the override as applied."""
    with pytest.raises(ValueError, match="empty name"):
        resolve_table_name("orders", {"orders*": "*"})


@pytest.mark.unit
def test_a_pattern_that_expands_to_a_name_is_resolved():
    """The same mapping against a longer name has something to put in place of the `*`."""
    assert resolve_table_name("orders_2026", {"orders*": "*"}) == "_2026"


@pytest.mark.unit
def test_a_run_s_overrides_are_read_back_from_its_payload():
    kwargs = {
        "test_suite_id": "suite-123",
        "version_id": "version-1",
        "schema_name": "build_20261104",
        "table_names": {"orders": "build_orders"},
        "variables": {"END_DATE": "2026-10-17"},
    }

    assert overrides_from_kwargs(kwargs) == {
        "schema_name": "build_20261104",
        "table_names": {"orders": "build_orders"},
        "variables": {"END_DATE": "2026-10-17"},
    }


@pytest.mark.unit
@pytest.mark.parametrize("kwargs", [None, {}, {"test_suite_id": "suite-123"}])
def test_a_run_with_no_overrides_reads_back_none(kwargs):
    assert overrides_from_kwargs(kwargs) == {}


@pytest.mark.unit
def test_overrides_are_labelled_in_a_fixed_order():
    """The order comes from the declaration, not from the caller, so one run's overrides read the
    same way as another's."""
    labelled = labelled_overrides(
        variables={"END_DATE": "2026-10-17"},
        schema_name="build_20261104",
        match_schema_name="reference_2026_09_10",
    )

    assert list(labelled) == ["Schema", "Match schema", "Variables"]
    assert labelled["Schema"] == "build_20261104"


@pytest.mark.unit
def test_an_override_a_run_did_not_apply_is_left_out():
    assert labelled_overrides(schema_name="build_20261104", table_names=None, variables={}) == {
        "Schema": "build_20261104"
    }


@pytest.mark.unit
def test_every_override_has_a_label():
    """The labels are what a reader sees for a run, so an override added without one would be
    applied and never shown."""
    assert set(OVERRIDE_LABELS) == {
        "schema_name",
        "table_names",
        "match_schema_name",
        "match_table_names",
        "variables",
    }
