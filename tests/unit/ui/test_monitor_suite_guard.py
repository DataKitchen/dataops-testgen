"""Monitor suites are a parallel surface: the regular test-definition and test-result
pages must not render for one, matching the REST and MCP resolvers."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from testgen.ui.views.test_definitions import TestDefinitionsPage
from testgen.ui.views.test_results import TestResultsPage

pytestmark = pytest.mark.unit


def _page(cls):
    """Build a page without Page.__init__, which needs a Streamlit runtime."""
    page = cls.__new__(cls)
    page.router = MagicMock()
    return page


def _clause_text(call) -> str:
    return " ".join(
        str(arg.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for arg in call.args[1:]
    )


# --- test definitions ---


def test_test_definitions_narrows_the_suite_lookup_to_regular_suites():
    page = _page(TestDefinitionsPage)
    with patch("testgen.ui.views.test_definitions.get_test_suite", return_value=None) as get_suite:
        page.render(test_suite_id="a-suite-id")

    assert _clause_text(get_suite.call_args) == "test_suites.suite_type = 'regular'"


def test_test_definitions_redirects_when_the_suite_does_not_resolve():
    page = _page(TestDefinitionsPage)
    with patch("testgen.ui.views.test_definitions.get_test_suite", return_value=None):
        page.render(test_suite_id="a-suite-id")

    page.router.navigate_with_warning.assert_called_once()
    assert page.router.navigate_with_warning.call_args.args[1] == "test-suites"


# --- test results ---


def test_test_results_narrows_the_suite_lookup_to_regular_suites():
    page = _page(TestResultsPage)
    run = MagicMock(test_suite_id="a-suite-id")
    with (
        patch("testgen.ui.views.test_results.get_test_run_minimal", return_value=run),
        patch("testgen.ui.views.test_results.get_test_suite", return_value=None) as get_suite,
    ):
        page.render(run_id="a-run-id")

    assert _clause_text(get_suite.call_args) == "test_suites.suite_type = 'regular'"


def test_test_results_redirects_when_the_run_belongs_to_a_monitor_suite():
    page = _page(TestResultsPage)
    run = MagicMock(test_suite_id="a-suite-id")
    with (
        patch("testgen.ui.views.test_results.get_test_run_minimal", return_value=run),
        patch("testgen.ui.views.test_results.get_test_suite", return_value=None),
    ):
        page.render(run_id="a-run-id")

    page.router.navigate_with_warning.assert_called_once()
    assert page.router.navigate_with_warning.call_args.args[1] == "test-runs"


def test_test_results_does_not_look_up_a_suite_when_the_run_is_missing():
    page = _page(TestResultsPage)
    with (
        patch("testgen.ui.views.test_results.get_test_run_minimal", return_value=None),
        patch("testgen.ui.views.test_results.get_test_suite") as get_suite,
    ):
        page.render(run_id="a-run-id")

    get_suite.assert_not_called()
    page.router.navigate_with_warning.assert_called_once()
