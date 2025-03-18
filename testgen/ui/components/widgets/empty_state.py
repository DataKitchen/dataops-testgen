import typing
from enum import Enum

import streamlit as st

from testgen.ui.components.widgets.button import button
from testgen.ui.components.widgets.link import link
from testgen.ui.components.widgets.page import css_class, whitespace
from testgen.ui.services.user_session_service import DISABLED_ACTION_TEXT


class EmptyStateMessage(Enum):
    Connection = (
        "Begin by connecting your database.",
        "TestGen delivers data quality through data profiling, hygiene review, test generation, and test execution.",
    )
    TableGroup = (
        "Profile your tables to detect hygiene issues",
        "Create table groups for your connected databases to run data profiling and hygiene review.",
    )
    Profiling = (
        "Profile your tables to detect hygiene issues",
        "Run data profiling on your table groups to understand data types, column contents, and data patterns.",
    )
    TestSuite = (
        "Run data validation tests",
        "Automatically generate tests from data profiling results or write custom tests for your business rules.",
    )
    TestExecution = (
        "Run data validation tests",
        "Execute tests to assess data quality of your tables."
    )


def empty_state(
    label: str,
    icon: str,
    message: EmptyStateMessage,
    action_label: str,
    action_disabled: bool = False,
    link_href: str | None = None,
    link_params: dict | None = None,
    button_onclick: typing.Callable[..., None] | None = None,
    button_icon: str = "add",
) -> None:
    with st.container(border=True):
        css_class("bg-white")
        whitespace(5)
        st.html(f"""
                <div style="text-align: center;">
                    <p style="font-size: 24px; color: var(--secondary-text-color);">{label}</p>
                    <p><i class="material-symbols-rounded" style="font-size: 60px; color: var(--disabled-text-color);">{icon}</i></p>
                    <p><b>{message.value[0]}</b><br>{message.value[1]}</p>
                </div>
                """)
        _, center_column, _ = st.columns([.4, .3, .4])
        with center_column:
            if link_href:
                link(
                    label=action_label,
                    href=link_href,
                    params=link_params or {},
                    right_icon="chevron_right",
                    underline=False,
                    height=40,
                    style=f"""
                        margin: auto;
                        border-radius: 4px;
                        border: var(--button-stroked-border);
                        padding: 8px 8px 8px 16px;
                        color: {"var(--disabled-text-color)" if action_disabled else "var(--primary-color)"};
                    """,
                    disabled=action_disabled,
                    tooltip=DISABLED_ACTION_TEXT if action_disabled else None,
                )
            elif button_onclick:
                button(
                    type_="stroked" if action_disabled else "flat",
                    color="basic" if action_disabled else "primary",
                    label=action_label,
                    icon=button_icon,
                    on_click=button_onclick,
                    style="margin: auto; width: auto;",
                    disabled=action_disabled,
                    tooltip=DISABLED_ACTION_TEXT if action_disabled else None,
                )
        whitespace(5)
