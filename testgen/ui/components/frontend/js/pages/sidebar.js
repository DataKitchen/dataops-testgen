import van from '/app/static/js/van.min.js';
import { isEqual } from '/app/static/js/utils.js';

export default (component) => {
    const { data, setTriggerValue, parentElement } = component;

    const Sidebar = window.testgen.components.Sidebar;

    // Dedicated proxy so the sidebar always calls its own setTriggerValue,
    // even when other v2 components overwrite the shared Streamlit singleton.
    Sidebar.StreamlitInstance = {
        setFrameHeight() {},
        sendData(data) {
            const event = data.event;
            const triggerData = Object.fromEntries(
                Object.entries(data).filter(([k]) => k !== 'event'),
            );
            setTriggerValue(event, triggerData);
        },
    };

    const callToken = {};
    parentElement.callToken = callToken;

    let componentState = parentElement.state;
    // Null when a cleanup ran after this element was mounted: rebuild it from scratch.
    if (!componentState) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        parentElement.replaceChildren();
        van.add(parentElement, Sidebar(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => {
        // Streamlit runs a superseded call's cleanup when that call resolves late; only the latest call's tears down.
        if (parentElement.callToken !== callToken) {
            return;
        }
        parentElement.state = null;
    };
};
