import typing

import streamlit as st

from testgen.common.models import with_database_session
from testgen.ui.components.utils.component import component
from testgen.ui.navigation.router import Router
from testgen.ui.session import session

AvailablePages = typing.Literal[
    "data_catalog",
    "column_profiling_results",
    "project_dashboard",
    "profiling_runs",
    "test_runs",
    "test_suites",
    "quality_dashboard",
    "score_details",
    "schedule_list",
    "column_selector",
    "connections",
    "table_group_wizard",
    "help_menu",
]


def testgen_component(
    component_id: AvailablePages,
    props: dict,
    on_change_handlers: dict[str, typing.Callable] | None = None,
    event_handlers: dict[str, typing.Callable] | None = None,
) -> dict | None:
    """
    Testgen component to display a VanJS page.

    # Parameters
    :param component_id: name of page
    :param props: properties expected by the page
    :param on_change_handlers: event handlers to be called during on_change callback (recommended, but does not support calling st.rerun())
    :param event_handlers: event handlers to be called on next run (supports calling st.rerun())

    For both on_change_handlers and event_handlers, the "payload" data from the event is passed as the only argument to the callback function
    """

    key = f"testgen:{component_id}"

    @with_database_session
    def on_change():
        event_data = st.session_state[key]
        if event_data and (event := event_data.get("event")):
            if event == "LinkClicked":
                Router().queue_navigation(to=event_data["href"], with_args=event_data.get("params"))
            elif on_change_handlers and (handler := on_change_handlers.get(event)):
                # Prevent handling the same event multiple times
                event_id = event_data.get("_id", "")
                if event_id != session.testgen_event_id.get(component_id):
                    session.testgen_event_id[component_id] = event_id
                    handler(event_data.get("payload"))

    event_data = component(
        id_=component_id,
        key=key,
        props=props,
        on_change=on_change,
    )
    if event_handlers and event_data and (event := event_data.get("event")) and (handler := event_handlers.get(event)):
        # Prevent handling the same event multiple times
        event_id = event_data.get("_id", "")
        if event_id != session.testgen_event_id.get(component_id):
            session.testgen_event_id[component_id] = event_id
            # These events are not handled through the component's on_change callback
            # because they may call st.rerun(), causing the "Calling st.rerun() within a callback is a noop" error
            handler(event_data.get("payload"))

    return event_data
