import van from '/app/static/js/van.min.js';
import { createEmitter, isEqual } from '/app/static/js/utils.js';
import { HelpMenu } from '/app/static/js/components/help_menu.js';

export default (component) => {
    const { data, setTriggerValue, parentElement } = component;

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
        componentState.emit = createEmitter(setTriggerValue);
        parentElement.replaceChildren();
        van.add(parentElement, HelpMenu(componentState));
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
