/**
 * @typedef Properties
 * @type {object}
 * @property {Array} columns
 */
import van from '/app/static/js/van.min.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { ColumnSelector } from '/app/static/js/components/explorer_column_selector.js';
import { createEmitter, getValue, isEqual } from '/app/static/js/utils.js';

const { div } = van.tags;

const ColumnSelectorDialog = (/** @type Properties */ props) => {
    const { emit } = props;
    const dialogProp = getValue(props.dialog);
    const dialogOpen = van.state(dialogProp?.open === true);

    const content = div({ style: 'height: 400px;' }, ColumnSelector(props));

    if (dialogProp) {
        const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Select Columns');
        return Dialog(
            {
                title: dialogTitle,
                open: dialogOpen,
                onClose: () => { dialogOpen.val = false; emit('CloseClicked', {}); },
                width: '55rem',
            },
            content,
        );
    }
    return content;
};

export { ColumnSelectorDialog };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

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
        van.add(parentElement, ColumnSelectorDialog(componentState));
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
