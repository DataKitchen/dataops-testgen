from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def session_mock():
    with patch("testgen.mcp.services.inventory_service.get_current_session") as mock:
        yield mock.return_value


@pytest.fixture(autouse=True)
def table_group_select_summary_mock():
    with patch("testgen.mcp.services.inventory_service.TableGroup.select_summary") as mock:
        mock.return_value = ([], 0)
        yield mock


@pytest.fixture(autouse=True)
def scorecards_by_project_mock():
    with patch(
        "testgen.mcp.services.inventory_service.ScoreDefinition.list_with_table_group_targets"
    ) as mock:
        mock.return_value = []
        yield mock


def _make_row(project_code="demo", project_name="Demo", connection_id=1, connection_name="main",
              table_group_id=None, table_groups_name="core",
              table_group_schema="public", test_suite_id=None, test_suite="Quality"):
    row = MagicMock()
    row.project_code = project_code
    row.project_name = project_name
    row.connection_id = connection_id
    row.connection_name = connection_name
    row.table_group_id = table_group_id or uuid4()
    row.table_groups_name = table_groups_name
    row.table_group_schema = table_group_schema
    row.test_suite_id = test_suite_id or uuid4()
    row.test_suite = test_suite
    return row


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_basic(mock_select, session_mock):
    tg_id = uuid4()
    row = _make_row(table_group_id=tg_id)
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "Data Inventory" in result
    assert "Demo" in result
    assert "main" in result
    assert "core" in result
    assert "Quality" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_empty(mock_select, session_mock):
    session_mock.execute.return_value.all.return_value = []

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "Data Inventory" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_project_no_connections(mock_select, session_mock):
    row = _make_row(connection_id=None)
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "Demo" in result
    assert "No connections" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_includes_list_tables_hint(mock_select, session_mock):
    session_mock.execute.return_value.all.return_value = [_make_row()]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "list_tables" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_compact_groups(mock_select, session_mock):
    """When >50 groups, group output uses single-line compact format."""
    rows = [
        _make_row(
            table_group_id=uuid4(),
            table_groups_name=f"Group_{i}",
            test_suite=f"Suite_{i}",
            test_suite_id=uuid4(),
        )
        for i in range(55)
    ]
    session_mock.execute.return_value.all.return_value = rows

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    # Compact groups: single line with "test suites: N", no "#### Table Group:" headers
    assert "test suites:" in result
    assert "#### Table Group:" not in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_without_view_hides_connections_and_suites(mock_select, session_mock):
    """Without view permission: connection names hidden, table groups shown in compact format, suites hidden."""
    tg_id = uuid4()
    suite_id = uuid4()
    row = _make_row(table_group_id=tg_id, test_suite_id=suite_id, test_suite="Secret Suite")
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=[])

    assert "Demo" in result
    assert "main" not in result  # connection name hidden
    assert "core" in result  # table group still shown
    assert str(tg_id) in result  # table group id still shown
    assert "Secret Suite" not in result  # suite name hidden
    assert str(suite_id) not in result  # suite id hidden
    assert "test suites: 1" in result  # suite count shown


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_with_view_shows_all_details(mock_select, session_mock):
    """With view permission: connections, table groups, and suites all shown."""
    tg_id = uuid4()
    suite_id = uuid4()
    row = _make_row(table_group_id=tg_id, test_suite_id=suite_id, test_suite="Visible Suite")
    session_mock.execute.return_value.all.return_value = [row]

    from testgen.mcp.services.inventory_service import get_inventory

    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "main" in result  # connection name shown
    assert "**Test Suites:**" in result
    assert "Visible Suite" in result
    assert str(suite_id) in result
    assert "requires `view` permission" not in result


# ----------------------------------------------------------------------
# Profiling fragment merge (TG-1028)
# ----------------------------------------------------------------------


def _profiling_summary(tg_id, *, profiled=True, hygiene_issues=(2, 2, 11)):
    s = MagicMock()
    s.id = tg_id
    s.dq_score_profiling = 95.0
    s.dq_score_testing = 80.0
    s.latest_profile_id = uuid4() if profiled else None
    s.latest_profile_job_execution_id = uuid4() if profiled else None
    s.latest_profile_start = MagicMock()
    s.latest_profile_start.strftime.return_value = "2026-04-23"
    definite, likely, possible = hygiene_issues
    s.latest_hygiene_issues_definite_ct = definite
    s.latest_hygiene_issues_likely_ct = likely
    s.latest_hygiene_issues_possible_ct = possible
    return s


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_includes_profiling_fragment_when_view(
    mock_select, session_mock, table_group_select_summary_mock,
):
    """With view permission, the per-TG profiling one-liner appears under the TG."""
    tg_id = uuid4()
    summary = _profiling_summary(tg_id)
    table_group_select_summary_mock.return_value = ([summary], 1)
    session_mock.execute.return_value.all.return_value = [_make_row(table_group_id=tg_id)]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "Score" in result
    assert "hygiene issues 15" in result  # 2+2+11
    assert "last profiled 2026-04-23" in result
    assert f"profiling run `{summary.latest_profile_job_execution_id}`" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_omits_profiling_fragment_without_view(
    mock_select, session_mock, table_group_select_summary_mock,
):
    """Catalog-only access skips the profiling fragment entirely (no select_summary lookup)."""
    tg_id = uuid4()
    session_mock.execute.return_value.all.return_value = [_make_row(table_group_id=tg_id)]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=[])

    assert "hygiene issues" not in result
    assert "last profiled" not in result
    assert "profiling run" not in result
    # select_summary should not be called for projects we can't view.
    table_group_select_summary_mock.assert_not_called()


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_never_profiled_fragment(
    mock_select, session_mock, table_group_select_summary_mock,
):
    """Never-profiled TG renders 'not profiled yet' instead of score/hygiene issue counts."""
    tg_id = uuid4()
    table_group_select_summary_mock.return_value = (
        [_profiling_summary(tg_id, profiled=False)], 1,
    )
    session_mock.execute.return_value.all.return_value = [_make_row(table_group_id=tg_id)]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "not profiled yet" in result
    assert "hygiene issues" not in result
    assert "Score" not in result


# ----------------------------------------------------------------------
# Scorecard rendering
# ----------------------------------------------------------------------


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_lists_single_tg_scorecard_under_tg(
    mock_select, session_mock, scorecards_by_project_mock,
):
    """A scorecard targeting one TG by name renders as a bullet under that TG."""
    tg_id = uuid4()
    sc_id = uuid4()
    session_mock.execute.return_value.all.return_value = [
        _make_row(table_group_id=tg_id, table_groups_name="core"),
    ]
    scorecards_by_project_mock.return_value = [(sc_id, "Core Scorecard", ["core"])]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "**Scorecards:**" in result
    assert f"- **Core Scorecard** (id: `{sc_id}`)" in result
    # No spanning section when every scorecard targets exactly one TG.
    assert "spanning multiple table groups" not in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_multi_tg_scorecard_appears_under_each_named_tg_and_spanning(
    mock_select, session_mock, scorecards_by_project_mock,
):
    """A scorecard targeting two TGs appears under each TG AND in the spanning section."""
    tg_a, tg_b = uuid4(), uuid4()
    sc_id = uuid4()
    session_mock.execute.return_value.all.return_value = [
        _make_row(table_group_id=tg_a, table_groups_name="orders", test_suite_id=uuid4()),
        _make_row(table_group_id=tg_b, table_groups_name="customers", test_suite_id=uuid4()),
    ]
    scorecards_by_project_mock.return_value = [(sc_id, "Cross", ["orders", "customers"])]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert result.count(f"- **Cross** (id: `{sc_id}`)") == 3
    assert "### Scorecards spanning multiple table groups" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_no_name_filter_scorecard_in_spanning_section_only(
    mock_select, session_mock, scorecards_by_project_mock,
):
    """A scorecard with no table_groups_name filter only appears in the spanning section."""
    tg_id = uuid4()
    sc_id = uuid4()
    session_mock.execute.return_value.all.return_value = [_make_row(table_group_id=tg_id)]
    scorecards_by_project_mock.return_value = [(sc_id, "Metadata Only", [])]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "### Scorecards spanning multiple table groups" in result
    assert f"- **Metadata Only** (id: `{sc_id}`)" in result
    # The TG block should not have a Scorecards: line.
    assert "**Scorecards:**" not in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_compact_mode_emits_scorecards_count_no_ids(
    mock_select, session_mock, scorecards_by_project_mock,
):
    """Compact mode (>50 groups) appends 'scorecards: N' to the one-liner; no IDs."""
    rows = [
        _make_row(
            table_group_id=uuid4(),
            table_groups_name=f"Group_{i}",
            test_suite=f"Suite_{i}",
            test_suite_id=uuid4(),
        )
        for i in range(55)
    ]
    session_mock.execute.return_value.all.return_value = rows
    sc_id = uuid4()
    scorecards_by_project_mock.return_value = [(sc_id, "G0 Scorecard", ["Group_0"])]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "scorecards: 1" in result
    assert str(sc_id) not in result  # no IDs in compact mode


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_catalog_only_project_hides_scorecards(
    mock_select, session_mock, scorecards_by_project_mock,
):
    """Without view permission, the ORM lookup is skipped and no scorecard text renders."""
    tg_id = uuid4()
    session_mock.execute.return_value.all.return_value = [_make_row(table_group_id=tg_id)]
    scorecards_by_project_mock.return_value = [(uuid4(), "Hidden", ["core"])]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=[])

    scorecards_by_project_mock.assert_not_called()
    assert "Scorecards" not in result
    assert "Hidden" not in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_footer_includes_get_scorecard_hint(
    mock_select, session_mock, scorecards_by_project_mock,
):
    """Footer mentions get_scorecard for discoverability."""
    session_mock.execute.return_value.all.return_value = [_make_row()]

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "get_scorecard(scorecard_id=" in result


@patch("testgen.mcp.services.inventory_service.select")
def test_get_inventory_no_scorecards_omits_scorecards_line(
    mock_select, session_mock, scorecards_by_project_mock,
):
    """When no scorecards target a TG, the Scorecards line is omitted entirely."""
    tg_id = uuid4()
    session_mock.execute.return_value.all.return_value = [_make_row(table_group_id=tg_id)]
    scorecards_by_project_mock.return_value = []

    from testgen.mcp.services.inventory_service import get_inventory
    result = get_inventory(project_codes=["demo"], view_project_codes=["demo"])

    assert "**Scorecards:**" not in result
    assert "spanning multiple table groups" not in result
