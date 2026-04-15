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

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, Sidebar(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
