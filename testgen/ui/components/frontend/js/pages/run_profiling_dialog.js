/**
 * @import { TableGroupStats } from '../components/table_group_stats.js'
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
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { Alert } from '../components/alert.js';
import { ExpanderToggle } from '../components/expander_toggle.js';
import { Icon } from '../components/icon.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Code } from '../components/code.js';
import { Button } from '../components/button.js';
import { Select } from '../components/select.js';
import { TableGroupStats } from '../components/table_group_stats.js';

const { div, span, strong } = van.tags;

/**
 * @param {Properties} props
 */
const RunProfilingDialog = (props) => {
    loadStylesheet('run-profiling', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const wrapperId = 'run-profiling-wrapper';

    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    const tableGroups = getValue(props.table_groups);
    const allowSelection = getValue(props.allow_selection);
    const selectedId =  van.state(getValue(props.selected_id));
    const selectedTableGroup = van.derive(() => tableGroups.find(({ id }) => id === selectedId.val));
    const showCLICommand = van.state(false);

    return div(
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