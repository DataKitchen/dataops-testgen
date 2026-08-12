from unittest.mock import MagicMock, patch

import pytest

from testgen.common.generation_set_service import (
    DEFAULT_GENERATION_SET,
    MONITOR_GENERATION_SET,
    get_generation_set_members,
    get_overriding_test_types,
    list_generation_sets,
    resolve_generation_sets,
)

MODULE = "testgen.common.generation_set_service"


def _suite(generation_sets=None):
    return MagicMock(generation_sets=generation_sets)


def _mock_session(rows):
    session = MagicMock()
    session.execute.return_value.all.return_value = rows
    return session


# --- list_generation_sets ---


@patch(f"{MODULE}.get_current_session")
def test_list_generation_sets_excludes_monitor_by_default(mock_session):
    mock_session.return_value = _mock_session([("Plugin_Set",), ("Monitor",), ("Standard",)])

    assert list_generation_sets() == ["Plugin_Set", "Standard"]


@patch(f"{MODULE}.get_current_session")
def test_list_generation_sets_can_include_monitor(mock_session):
    mock_session.return_value = _mock_session([("Plugin_Set",), ("Monitor",), ("Standard",)])

    assert list_generation_sets(include_monitor=True) == ["Plugin_Set", "Monitor", "Standard"]


@patch(f"{MODULE}.get_current_session")
def test_list_generation_sets_empty_table(mock_session):
    mock_session.return_value = _mock_session([])

    assert list_generation_sets() == []


# --- get_generation_set_members ---


@patch(f"{MODULE}.get_current_session")
def test_get_generation_set_members_groups_by_set(mock_session):
    mock_session.return_value = _mock_session([
        ("Plugin_Set", "Plugin_Type_A"),
        ("Plugin_Set", "Plugin_Type_B"),
        ("Standard", "Pattern_Match"),
    ])

    assert get_generation_set_members() == {
        "Plugin_Set": ["Plugin_Type_A", "Plugin_Type_B"],
        "Standard": ["Pattern_Match"],
    }


# --- get_overriding_test_types ---


@patch(f"{MODULE}.get_current_session")
def test_get_overriding_test_types_groups_by_overridden_type(mock_session):
    mock_session.return_value = _mock_session([
        ("Pattern_Match", "Plugin_Type_A"),
        ("Pattern_Match", "Plugin_Type_B"),
        ("Constant", "Plugin_Type_C"),
    ])

    assert get_overriding_test_types() == {
        "Pattern_Match": ["Plugin_Type_A", "Plugin_Type_B"],
        "Constant": ["Plugin_Type_C"],
    }


@patch(f"{MODULE}.get_current_session")
def test_get_overriding_test_types_empty_when_nothing_overrides(mock_session):
    mock_session.return_value = _mock_session([])

    assert get_overriding_test_types() == {}


# --- resolve_generation_sets: defaulting (requested is None) ---


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_uses_stored_sets_when_nothing_requested(_sets):
    suite = _suite(["Standard", "Plugin_Set"])

    assert resolve_generation_sets(suite, None) == ["Standard", "Plugin_Set"]


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_preserves_stored_order(_sets):
    suite = _suite(["Plugin_Set", "Standard"])

    assert resolve_generation_sets(suite, None) == ["Plugin_Set", "Standard"]


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_falls_back_to_default_when_stored_is_null(_sets):
    assert resolve_generation_sets(_suite(None), None) == [DEFAULT_GENERATION_SET]


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_falls_back_to_default_when_stored_is_empty(_sets):
    assert resolve_generation_sets(_suite([]), None) == [DEFAULT_GENERATION_SET]


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_drops_stored_sets_that_no_longer_exist(_sets):
    suite = _suite(["Standard", "Retired/Plugin"])

    assert resolve_generation_sets(suite, None) == ["Standard"]


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_falls_back_when_every_stored_set_is_gone(_sets):
    suite = _suite(["Retired/Plugin"])

    assert resolve_generation_sets(suite, None) == [DEFAULT_GENERATION_SET]


# --- resolve_generation_sets: explicit request ---


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_returns_requested_sets_ignoring_stored(_sets):
    suite = _suite(["Standard"])

    assert resolve_generation_sets(suite, ["Plugin_Set"]) == ["Plugin_Set"]


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_dedupes_requested_preserving_order(_sets):
    result = resolve_generation_sets(_suite(), ["Standard", "Plugin_Set", "Standard"])

    assert result == ["Standard", "Plugin_Set"]


# --- resolve_generation_sets: rejection ---


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_rejects_a_bare_string(_sets):
    with pytest.raises(TypeError, match="generation_sets must be a list of generation set names, not a string"):
        resolve_generation_sets(_suite(), "Standard")


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_rejects_explicitly_empty_request(_sets):
    with pytest.raises(ValueError, match="At least one generation set is required"):
        resolve_generation_sets(_suite(["Standard"]), [])


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_rejects_monitor_with_its_own_message(_sets):
    with pytest.raises(ValueError, match="'Monitor' cannot be used for a regular test suite"):
        resolve_generation_sets(_suite(), [MONITOR_GENERATION_SET])


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_rejects_monitor_even_alongside_valid_sets(_sets):
    with pytest.raises(ValueError, match="'Monitor' cannot be used for a regular test suite"):
        resolve_generation_sets(_suite(), ["Standard", MONITOR_GENERATION_SET])


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_rejects_unknown_set_and_lists_available(_sets):
    with pytest.raises(ValueError) as excinfo:
        resolve_generation_sets(_suite(), ["Nope"])

    message = str(excinfo.value)
    assert "Nope" in message
    assert "Plugin_Set, Standard" in message


@patch(f"{MODULE}.list_generation_sets", return_value=["Plugin_Set", "Standard"])
def test_resolve_lists_every_unknown_set_sorted(_sets):
    with pytest.raises(ValueError, match="Aaa, Zzz"):
        resolve_generation_sets(_suite(), ["Zzz", "Standard", "Aaa"])
