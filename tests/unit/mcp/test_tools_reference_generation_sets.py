from unittest.mock import MagicMock, patch

MODULE = "testgen.mcp.tools.reference"


def _test_type(test_type, test_name_short):
    tt = MagicMock()
    tt.test_type = test_type
    tt.test_name_short = test_name_short
    return tt


@patch(f"{MODULE}.TestType")
@patch(f"{MODULE}.get_generation_set_members")
def test_generation_sets_resource_lists_each_set_and_its_types(mock_members, mock_tt_cls, db_session_mock):
    mock_members.return_value = {
        "Plugin_Set": ["Plugin_Type_A", "Plugin_Type_B"],
        "Standard": ["Pattern_Match"],
    }
    mock_tt_cls.select_where.return_value = [
        _test_type("Plugin_Type_A", "Plugin Type A"),
        _test_type("Plugin_Type_B", "Plugin Type B"),
        _test_type("Pattern_Match", "Pattern Match"),
    ]

    from testgen.mcp.tools.reference import generation_sets_resource

    result = generation_sets_resource()

    assert "Plugin_Set" in result
    assert "Standard" in result
    assert "Plugin Type A" in result
    assert "Plugin Type B" in result
    assert "Pattern Match" in result


@patch(f"{MODULE}.TestType")
@patch(f"{MODULE}.get_generation_set_members")
def test_generation_sets_resource_does_not_leak_test_type_codes(mock_members, mock_tt_cls, db_session_mock):
    mock_members.return_value = {"Standard": ["Pattern_Match", "Alpha_Trunc"]}
    mock_tt_cls.select_where.return_value = [
        _test_type("Pattern_Match", "Pattern Match"),
        _test_type("Alpha_Trunc", "Alpha Truncation"),
    ]

    from testgen.mcp.tools.reference import generation_sets_resource

    result = generation_sets_resource()

    assert "Pattern_Match" not in result
    assert "Alpha_Trunc" not in result


@patch(f"{MODULE}.TestType")
@patch(f"{MODULE}.get_generation_set_members")
def test_generation_sets_resource_falls_back_to_the_code_without_a_short_name(mock_members, mock_tt_cls, db_session_mock):
    mock_members.return_value = {"Standard": ["Pattern_Match"]}
    mock_tt_cls.select_where.return_value = [_test_type("Pattern_Match", None)]

    from testgen.mcp.tools.reference import generation_sets_resource

    assert "Pattern_Match" in generation_sets_resource()


@patch(f"{MODULE}.TestType")
@patch(f"{MODULE}.get_generation_set_members")
def test_generation_sets_resource_omits_sets_with_no_active_types(mock_members, mock_tt_cls, db_session_mock):
    mock_members.return_value = {
        "Retired_Set": ["Retired_Type"],
        "Standard": ["Pattern_Match"],
    }
    mock_tt_cls.select_where.return_value = [_test_type("Pattern_Match", "Pattern Match")]

    from testgen.mcp.tools.reference import generation_sets_resource

    result = generation_sets_resource()

    assert "Retired_Set" not in result
    assert "Pattern Match" in result


@patch(f"{MODULE}.get_generation_set_members", return_value={})
def test_generation_sets_resource_handles_no_sets(_mock_members, db_session_mock):
    from testgen.mcp.tools.reference import generation_sets_resource

    assert generation_sets_resource() == "No generation sets found."
