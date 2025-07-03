/**
 * @import { TableGroup } from '../components/table_group_form.js';
 * 
 * @typedef Result
 * @type {object}
 * @property {boolean} success
 * @property {string?} message
 * 
 * @typedef Properties
 * @type {object}
 * @property {TableGroup} table_group
 * @property {Result?} result
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { Alert } from '../components/alert.js';
import { ExpanderToggle } from '../components/expander_toggle.js';
import { Icon } from '../components/icon.js';
import { emitEvent, getValue, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Code } from '../components/code.js';
import { Button } from '../components/button.js';

const { div, em, span, strong } = van.tags;

/**
 * @param {Properties} props
 */
const RunProfilingDialog = (props) => {
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const wrapperId = 'runprogiling-wrapper';

    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    const tableGroup = getValue(props.table_group);
    const showCLICommand = van.state(false);

    return div(
        { id: wrapperId, class: 'flex-column fx-gap-3' },
        div(
            { class: 'flex-row fx-gap-1' },
            span({}, 'Execute profiling for the table group'),
            strong({}, tableGroup.table_groups_name),
            span({}, '?'),
        ),
        div(
            { class: 'flex-row fx-gap-1' },
            Icon({}, 'info'),
            em({}, ' Profiling will be performed in a background process.'),
        ),
        ExpanderToggle({
            collapseLabel: 'Collapse',
            expandLabel: 'Show CLI command',
            onCollapse: () => showCLICommand.val = false,
            onExpand: () => showCLICommand.val = true,
        }),
        Code({ class: () => showCLICommand.val ? '' : 'hidden' }, `testgen run-profile --table-group-id ${tableGroup.id}`),
        () => {
            const result = getValue(props.result) ?? {};
            return result.message
                ? Alert({ type: result.success ? 'success' : 'error' }, span(result.message))
                : '';
        },
        div(
            { class: 'flex-row fx-justify-content-flex-end' },
            () => {
                const result = getValue(props.result);

                if (result && result.success) {
                    return Button({
                        type: 'stroked',
                        color: 'primary',
                        label: 'Go to Profiling Runs',
                        width: 'auto',
                        icon: 'chevron_right',
                        onclick: () => emitEvent('GoToProfilingRunsClicked', { payload: tableGroup.id }),
                    });
                }

                return Button({
                    label: 'Run Profiling',
                    type: 'stroked',
                    color: 'primary',
                    width: 'auto',
                    style: 'width: auto;',
                    onclick: () => emitEvent('RunProfilingConfirmed', { payload: tableGroup.id }),
                });
            }
        )
    );
};

export { RunProfilingDialog };