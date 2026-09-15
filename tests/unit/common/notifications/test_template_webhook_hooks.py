"""Regression tests for the ``webhook_project_name`` / ``webhook_summary_url`` hooks.

The webhook envelope's ``project.name`` and ``url`` fields come from four
different context shapes (one per event handler). Each subclass extracts them
from the shape its handler assembles. If a handler renames a key or a subclass
drops the override, the envelope silently ships with empty top-level fields --
Slack messages lose their click-through link, Teams cards read as no-op, and
generic subscribers see empty values the schema documents as populated.
"""

from types import SimpleNamespace

import pytest

from testgen.common.notifications.monitor_run import MonitorEmailTemplate
from testgen.common.notifications.profiling_run import ProfilingRunEmailTemplate
from testgen.common.notifications.score_drop import ScoreDropEmailTemplate
from testgen.common.notifications.test_run import TestRunEmailTemplate

pytestmark = pytest.mark.unit


def test_test_run_template_extracts_project_name_and_url():
    template = TestRunEmailTemplate()
    context = {
        "test_run": SimpleNamespace(project_name="Project One"),
        "test_run_url": "https://tg.example/tests/1",
    }
    assert template.webhook_project_name(context) == "Project One"
    assert template.webhook_summary_url(context) == "https://tg.example/tests/1"


def test_test_run_template_tolerates_missing_context():
    template = TestRunEmailTemplate()
    assert template.webhook_project_name(None) is None
    assert template.webhook_summary_url({}) is None
    # ``test_run`` key present but without ``project_name`` attribute.
    assert template.webhook_project_name({"test_run": SimpleNamespace()}) is None


def test_profiling_run_template_extracts_project_name_and_url():
    template = ProfilingRunEmailTemplate()
    context = {
        "project_name": "Project Two",
        "profiling_run": {
            "issues_url": "https://tg.example/profiling/2#issues",
            "results_url": "https://tg.example/profiling/2",
        },
    }
    assert template.webhook_project_name(context) == "Project Two"
    # Issues URL is the primary click-through the email template uses.
    assert template.webhook_summary_url(context) == "https://tg.example/profiling/2#issues"


def test_profiling_run_template_falls_back_to_results_url():
    template = ProfilingRunEmailTemplate()
    context = {"profiling_run": {"results_url": "https://tg.example/profiling/2"}}
    assert template.webhook_summary_url(context) == "https://tg.example/profiling/2"


def test_monitor_run_template_extracts_project_name_and_url():
    template = MonitorEmailTemplate()
    context = {
        "summary": {"project_name": "Project Three"},
        "view_in_testgen_url": "https://tg.example/monitors?...",
    }
    assert template.webhook_project_name(context) == "Project Three"
    assert template.webhook_summary_url(context) == "https://tg.example/monitors?..."


def test_score_drop_template_extracts_project_name_and_url():
    template = ScoreDropEmailTemplate()
    context = {
        "project_name": "Project Four",
        "scorecard_url": "https://tg.example/scores/4",
    }
    assert template.webhook_project_name(context) == "Project Four"
    assert template.webhook_summary_url(context) == "https://tg.example/scores/4"


def test_all_templates_return_none_on_none_context():
    for template in (
        TestRunEmailTemplate(),
        ProfilingRunEmailTemplate(),
        MonitorEmailTemplate(),
        ScoreDropEmailTemplate(),
    ):
        assert template.webhook_project_name(None) is None
        assert template.webhook_summary_url(None) is None
