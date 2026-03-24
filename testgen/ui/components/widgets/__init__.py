# ruff: noqa: F401

from streamlit.components import v2 as components_v2

from testgen.ui.components.utils.component import component, component_v2_wrapped
from testgen.ui.components.widgets.breadcrumbs import breadcrumbs
from testgen.ui.components.widgets.button import button
from testgen.ui.components.widgets.card import card
from testgen.ui.components.widgets.empty_state import EmptyStateMessage, empty_state
from testgen.ui.components.widgets.expander_toggle import expander_toggle
from testgen.ui.components.widgets.link import link
from testgen.ui.components.widgets.page import (
    caption,
    css_class,
    divider,
    flex_row_center,
    flex_row_end,
    flex_row_start,
    help_menu,
    no_flex_gap,
    page_header,
    text,
    whitespace,
)
from testgen.ui.components.widgets.paginator import paginator
from testgen.ui.components.widgets.select import select
from testgen.ui.components.widgets.sidebar import sidebar
from testgen.ui.components.widgets.sorting_selector import sorting_selector
from testgen.ui.components.widgets.summary import summary_bar, summary_counts
from testgen.ui.components.widgets.testgen_component import testgen_component
from testgen.ui.components.widgets.wizard import WizardStep, wizard

table_group_wizard = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.table_group_wizard",
    js="pages/table_group_wizard.js",
    isolate_styles=False,
))

project_settings = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.project_settings",
    js="index.js",
    isolate_styles=False,
))

quality_dashboard_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.quality_dashboard",
    js="pages/quality_dashboard.js",
    isolate_styles=False,
))

connections_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.connections",
    js="pages/connections.js",
    isolate_styles=False,
))

project_dashboard_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.project_dashboard",
    js="pages/project_dashboard.js",
    isolate_styles=False,
))

test_suites_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.test_suites",
    js="pages/test_suites.js",
    isolate_styles=False,
))

test_runs_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.test_runs",
    js="pages/test_runs.js",
    isolate_styles=False,
))

profiling_runs_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.profiling_runs",
    js="pages/profiling_runs.js",
    isolate_styles=False,
))

table_group_list_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.table_group_list",
    js="pages/table_group_list.js",
    isolate_styles=False,
))

data_catalog_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.data_catalog",
    js="pages/data_catalog.js",
    isolate_styles=False,
))

monitors_dashboard_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.monitors_dashboard",
    js="pages/monitors_dashboard.js",
    isolate_styles=False,
))

score_details_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.score_details",
    js="pages/score_details.js",
    isolate_styles=False,
))

score_explorer_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.score_explorer",
    js="pages/score_explorer.js",
    isolate_styles=False,
))

test_definitions_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.test_definitions",
    js="pages/test_definitions.js",
    isolate_styles=False,
))

profiling_results_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.profiling_results",
    js="pages/profiling_results.js",
    isolate_styles=False,
))

test_results_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.test_results",
    js="pages/test_results.js",
    isolate_styles=False,
))

hygiene_issues_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.hygiene_issues",
    js="pages/hygiene_issues.js",
    isolate_styles=False,
))

application_logs_widget = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.application_logs",
    js="pages/application_logs.js",
    isolate_styles=False,
))
