/**
 * @import { TableGroupStats } from '/app/static/js/components/table_group_stats.js'
 * 
 * @typedef Result
 * @type {object}
 * @property {boolean} success
 * @property {string?} message
 * @property {boolean?} show_link
 * 
 * @typedef Properties
 * @type {object}
 * @property {TableGroupStats[]} table_groups
 * @property {string} selected_id
 * @property {boolean} allow_selection
 * @property {Result?} result
 */
import van from '/app/static/js/van.min.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { ExpanderToggle } from '/app/static/js/components/expander_toggle.js';
import { Icon } from '/app/static/js/components/icon.js';
import { emitEvent, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { Code } from '/app/static/js/components/code.js';
import { Button } from '/app/static/js/components/button.js';
import { Select } from '/app/static/js/components/select.js';
import { TableGroupStats } from '/app/static/js/components/table_group_stats.js';

const { div, span, strong } = van.tags;

/**
 * @param {Properties} props
 */
const RunProfilingDialog = (props) => {
    loadStylesheet('run-profiling', stylesheet);

    const dialogProp = getValue(props.dialog);
    const dialogOpen = van.state(dialogProp?.open === true);

    const wrapperId = 'run-profiling-wrapper';

    const tableGroups = getValue(props.table_groups);
    const allowSelection = getValue(props.allow_selection);
    const selectedId =  van.state(getValue(props.selected_id));
    const selectedTableGroup = van.derive(() => tableGroups.find(({ id }) => id === selectedId.val));
    const showCLICommand = van.state(false);

    const content = div(
        { id: wrapperId },
        div(
            { class: `flex-column fx-gap-3 ${allowSelection ? 'run-profiling--allow-selection' : ''}` },
            allowSelection
                ? Select({
                    label: 'Table Group',
                    value: selectedId,
                    options: tableGroups.map(({ id, table_groups_name }) => ({ label: table_groups_name, value: id })),
                    portalClass: 'run-profiling--select',
                })
                : span(
                    'Run profiling for the table group ',
                    strong({}, selectedTableGroup.val.table_groups_name),
                    '?',
                ),
            () => selectedTableGroup.val
                ? div(
                    TableGroupStats({ class: 'mt-1 mb-3' }, selectedTableGroup.val),
                    ExpanderToggle({
                        collapseLabel: 'Collapse',
                        expandLabel: 'Show CLI command',
                        onCollapse: () => showCLICommand.val = false,
                        onExpand: () => showCLICommand.val = true,
                    }),
                    Code({ class: () => showCLICommand.val ? '' : 'hidden' }, `testgen run-profile --table-group-id ${selectedTableGroup.val.id}`),
                )
                : div({ style: 'margin: auto;' }, 'Select a table group to profile.'),
            () => {
                const result = getValue(props.result) ?? {};
                return result.message
                    ? Alert({ type: result.success ? 'success' : 'error' }, span(result.message))
                    : '';
            },
        ),
        () => !getValue(props.result)
            ? div(
                { class: 'flex-row fx-justify-space-between mt-3' },
                div(
                    { class: 'flex-row fx-gap-1' },
                    Icon({ size: 16 }, 'info'),
                    span({ class: 'text-caption' }, ' Profiling will be performed in a background process.'),
                ),
                Button({
                    label: 'Run Profiling',
                    type: 'stroked',
                    color: 'primary',
                    width: 'auto',
                    style: 'width: auto;',
                    disabled: !selectedTableGroup.val,
                    onclick: () => emitEvent('RunProfilingConfirmed', { payload: selectedTableGroup.val }),
                }),
            ) : '',
        () => getValue(props.result)?.show_link
            ? Button({
                type: 'stroked',
                color: 'primary',
                label: 'Go to Profiling Runs',
                style: 'width: auto; margin-left: auto; margin-top: 12px;',
                icon: 'chevron_right',
                onclick: () => emitEvent('GoToProfilingRunsClicked', { payload: selectedTableGroup.val.id }),
            })
            : '',
    );

    if (dialogProp) {
        const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Run Profiling');
        return Dialog(
            {
                title: dialogTitle,
                open: dialogOpen,
                onClose: () => { dialogOpen.val = false; emitEvent('CloseClicked', {}); },
                width: '32rem',
            },
            content,
        );
    }
    return content;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.run-profiling--allow-selection {
    min-height: 225px;
}

.run-profiling--select {
    max-height: 200px !important;
}
`);

export { RunProfilingDialog };

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
        van.add(parentElement, RunProfilingDialog(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
