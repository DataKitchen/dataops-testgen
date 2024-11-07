import typing

from testgen.ui.components.utils.component import component
from testgen.ui.navigation.router import Router
from testgen.ui.session import session


def testgen_component(
    component_id: typing.Literal["profiling_runs", "test_runs", "database_flavor_selector"],
    props: dict,
    event_handlers: dict | None,
) -> dict | None:
    
    event_data = component(
        id_=component_id,
        key=f"testgen:{component_id}",
        props=props,
    )
    if event_data and (event := event_data.get("event")):
        if event == "LinkClicked":
            Router().navigate(to=event_data["href"], with_args=event_data.get("params"))

        elif event_handlers and (handler := event_handlers.get(event)):
            # Prevent handling the same event multiple times
            event_id = f"{component_id}:{event_data.get('_id', '')}"
            if event_id != session.testgen_event_id:
                session.testgen_event_id = event_id
                # These events are not handled through the component's on_change callback
                # because they may call st.rerun(), causing the "Calling st.rerun() within a callback is a noop" error
                handler(event_data.get("payload"))

    return event_data
