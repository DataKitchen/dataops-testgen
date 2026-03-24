/**
 * @typedef Properties
 * @type {object}
 * @property {string} table_name
 * @property {string} script
 */
import van from '/app/static/js/van.min.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Code } from '/app/static/js/components/code.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { emitEvent, getValue, isEqual } from '/app/static/js/utils.js';

const { div, span } = van.tags;

const TableCreateScriptDialog = (/** @type Properties */ props) => {
    const dialogProp = getValue(props.dialog);
    const dialogOpen = van.state(dialogProp?.open === true);

    const content = div(
        { class: 'flex-column fx-gap-2' },
        div(
            span({ class: 'text-secondary text-caption' }, 'Table: '),
            span({ style: 'font-weight: 500;' }, () => getValue(props.table_name)),
        ),
        () => Code({}, getValue(props.script) ?? ''),
    );

    if (dialogProp) {
        const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Table CREATE Script');
        return Dialog(
            {
                title: dialogTitle,
                open: dialogOpen,
                onClose: () => { dialogOpen.val = false; emitEvent('CloseClicked', {}); },
                width: '55rem',
            },
            content,
        );
    }
    return content;
};

export { TableCreateScriptDialog };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    Streamlit.enableV2(setTriggerValue);

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, TableCreateScriptDialog(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
