from testgen.mcp.prompts.workflows import hygiene_triage


def test_hygiene_triage_with_table_group_id_interpolates_id():
    tg_id = "abc-123-def"
    result = hygiene_triage(table_group_id=tg_id)

    assert tg_id in result
    assert f"table_group_id='{tg_id}'" in result
    # Without the inventory step:
    assert "get_data_inventory" not in result
    assert "Pick a table group" not in result
    assert "Focus on table group" in result


def test_hygiene_triage_without_table_group_id_uses_placeholder():
    result = hygiene_triage()

    assert "Pick a table group" in result
    assert "get_data_inventory" in result
    # With the discovery step we expect the placeholder form for the call examples:
    assert "table_group_id='...'" in result


def test_hygiene_triage_steps_numbered_consecutively_with_id():
    result = hygiene_triage(table_group_id="abc")

    # With table_group_id supplied, the inventory step is omitted → 5 steps numbered 1-5.
    for n in (1, 2, 3, 4, 5):
        assert f"{n}. " in result
    assert "6. " not in result


def test_hygiene_triage_steps_numbered_consecutively_without_id():
    result = hygiene_triage()

    # Without table_group_id, the inventory step is included → 6 steps numbered 1-6.
    for n in (1, 2, 3, 4, 5, 6):
        assert f"{n}. " in result
    assert "7. " not in result


def test_hygiene_triage_offers_all_three_dispositions():
    """The prompt should not push 'Dismissed' as the action — review feedback."""
    result = hygiene_triage()

    assert "Confirmed" in result
    assert "Dismissed" in result
    assert "Muted" in result
    assert "update_hygiene_issue" in result


def test_hygiene_triage_references_resource_for_unfamiliar_types():
    result = hygiene_triage()
    assert "testgen://hygiene-issue-types" in result
