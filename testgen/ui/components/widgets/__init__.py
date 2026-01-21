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

edit_monitor_settings = component_v2_wrapped(components_v2.component(
    name="dataops-testgen.edit_monitor_settings",
    js="pages/edit_monitor_settings.js",
    isolate_styles=False,
))
