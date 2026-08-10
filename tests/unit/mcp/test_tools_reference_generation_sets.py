from unittest.mock import patch

MODULE = "testgen.mcp.tools.reference"


@patch(f"{MODULE}.get_generation_set_members")
def test_generation_sets_resource_lists_each_set_and_its_types(mock_members, db_session_mock):
    mock_members.return_value = {
        "Plugin_Set": ["Plugin_Type_A", "Plugin_Type_B"],
        "Standard": ["Pattern_Match"],
    }

    from testgen.mcp.tools.reference import generation_sets_resource

    result = generation_sets_resource()

    assert "Plugin_Set" in result
    assert "Plugin_Type_A" in result
    assert "Standard" in result
    assert "Pattern_Match" in result


@patch(f"{MODULE}.get_generation_set_members", return_value={})
def test_generation_sets_resource_handles_no_sets(_mock_members, db_session_mock):
    from testgen.mcp.tools.reference import generation_sets_resource

    assert generation_sets_resource() == "No generation sets found."
