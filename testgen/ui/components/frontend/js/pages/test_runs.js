/**
 * @typedef TestRun
 * @type {object}
 * @property {string} test_run_id
 * @property {number} test_starttime
 * @property {string} table_groups_name
 * @property {string} test_suite
 * @property {'Running'|'Complete'|'Error'|'Cancelled'} status
 * @property {string} log_message
 * @property {string} duration
 * @property {string} process_id
 * @property {number} test_ct
 * @property {number} passed_ct
 * @property {number} warning_ct
 * @property {number} failed_ct
 * @property {number} error_ct
 * @property {number} dismissed_ct
 * @property {string} dq_score_testing
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_run
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {TestRun[]} items
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { Tooltip } from '../components/tooltip.js';
import { SummaryBar } from '../components/summary_bar.js';
import { Link } from '../components/link.js';
import { Button } from '../components/button.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { formatTimestamp, formatDuration } from '../display_utils.js';
import { Checkbox } from '../components/checkbox.js';

const { div, i, span, strong } = van.tags;

const TestRuns = (/** @type Properties */ props) => {
    window.testgen.isPage = true;

    const testRunItems = van.derive(() => {
        let items = [];
        try {
            items = JSON.parse(props.items?.val);
        } catch { }
        Streamlit.setFrameHeight(100 * items.length || 150);
        return items;
    });
    const columns = ['5%', '28%', '17%', '40%', '10%'];

    const userCanRun = getValue(props.permissions)?.can_run ?? false;
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;
    const selectedRuns = {};

    const tableId = 'test-runs-table';
    resizeFrameHeightToElement(tableId);
    resizeFrameHeightOnDOMChange(tableId);

    const initializeSelectedStates = (items) => {
        for (const testRun of items) {
            if (selectedRuns[testRun.test_run_id] == undefined) {
                selectedRuns[testRun.test_run_id] = van.state(false);
            }
        }
    };

    initializeSelectedStates(testRunItems.val);

    van.derive(() => {
        initializeSelectedStates(testRunItems.val);
    });

    return () => getValue(testRunItems).length
    ? div(
        { class: 'table', id: tableId },
        () => {
            const items = testRunItems.val;
            const selectedItems = items.filter(i => selectedRuns[i.test_run_id]?.val ?? false);
            const someRunSelected = selectedItems.length > 0;
            const tooltipText = !someRunSelected ? 'No runs selected' : undefined;

            if (!userCanEdit) {
                return '';
            }

            return div(
                { class: 'flex-row fx-justify-content-flex-end pb-2' },
                someRunSelected ? strong({class: 'mr-1'}, selectedItems.length) : '',
                someRunSelected ? span({class: 'mr-4'}, 'runs selected') : '',
                Button({
                    type: 'stroked',
                    icon: 'delete',
                    label: 'Delete Runs',
                    tooltip: tooltipText,
                    tooltipPosition: 'bottom-left',
                    disabled: !someRunSelected,
                    width: 'auto',
                    onclick: () => emitEvent('RunsDeleted', { payload: selectedItems.map(i => i.test_run_id) }),
                }),
            );
        },
        div(
            { class: 'table-header flex-row' },
            () => {
                const items = testRunItems.val;
                const selectedItems = items.filter(i => selectedRuns[i.test_run_id]?.val ?? false);
                const allSelected = selectedItems.length === items.length;
                const partiallySelected = selectedItems.length > 0 && selectedItems.length < items.length;

                if (!userCanEdit) {
                    return '';
                }

                return span(
                    { style: `flex: ${columns[0]}` }, 
                    userCanEdit
                        ? Checkbox({
                            checked: allSelected,
                            indeterminate: partiallySelected,
                            onChange: (checked) => items.forEach(item => selectedRuns[item.test_run_id].val = checked),
                            testId: 'select-all-test-run',
                        })
                        : '',
                );
            },
            span(
                { style: `flex: ${columns[1]}` },
                'Start Time | Table Group | Test Suite',
            ),
            span(
                { style: `flex: ${columns[2]}` },
                'Status | Duration',
            ),
            span(
                { style: `flex: ${columns[3]}` },
                'Results Summary',
            ),
            span(
                { style: `flex: ${columns[4]}` },
                'Testing Score',
            ),
        ),
        div(
            testRunItems.val.map(item => TestRunItem(item, columns, selectedRuns[item.test_run_id], userCanRun, userCanEdit)),
        ),
    )
    : div(
        { class: 'pt-7 text-secondary', style: 'text-align: center;' },
        'No test runs found matching filters',
    );
}

const TestRunItem = (
    /** @type TestRun */ item,
    /** @type string[] */ columns,
    /** @type boolean */ selected,
    /** @type boolean */ userCanRun,
    /** @type boolean */ userCanEdit,
) => {
    return div(
        { class: 'table-row flex-row' },
        userCanEdit
            ? div(
                { style: `flex: ${columns[0]}; font-size: 16px;` },
                Checkbox({
                    checked: selected,
                    onChange: (checked) => selected.val = checked,
                    testId: 'select-test-run',
                }),
            )
            : '',
        div(
            { style: `flex: ${columns[1]}` },
            Link({
                label: formatTimestamp(item.test_starttime),
                href: 'test-runs:results',
                params: { 'run_id': item.test_run_id },
                underline: true,
            }),
            div(
                { class: 'text-caption mt-1' },
                `${item.table_groups_name} > ${item.test_suite}`,
            ),
        ),
        div(
            { class: 'flex-row', style: `flex: ${columns[2]}` },
            div(
                TestRunStatus(item),
                div(
                    { class: 'text-caption mt-1' },
                    formatDuration(item.duration),
                ),
            ),
            item.status === 'Running' && item.process_id && userCanRun ? Button({
                type: 'stroked',
                label: 'Cancel Run',
                style: 'width: auto; height: 32px; color: var(--purple); margin-left: 16px;',
                onclick: () => emitEvent('RunCanceled', { payload: item }),
            }) : null,
        ),
        div(
            { class: 'pr-3', style: `flex: ${columns[3]}` },
            item.test_ct ? SummaryBar({
                items: [
                    { label: 'Passed', value: item.passed_ct, color: 'green' },
                    { label: 'Warning', value: item.warning_ct, color: 'yellow' },
                    { label: 'Failed', value: item.failed_ct, color: 'red' },
                    { label: 'Error', value: item.error_ct, color: 'brown' },
                    { label: 'Dismissed', value: item.dismissed_ct, color: 'grey' },
                ],
                height: 8,
                width: 350,
            }) : '--',
        ),
        div(
            { style: `flex: ${columns[4]}; font-size: 16px;` },
            item.test_ct && item.dq_score_testing
                ? item.dq_score_testing
                : '--',
        ),
    );
}

function TestRunStatus(/** @type TestRun */ item) {
    const attributeMap = {
        Running: { label: 'Running', color: 'blue' },
        Complete: { label: 'Completed', color: '' },
        Error: { label: 'Error', color: 'red' },
        Cancelled: { label: 'Canceled', color: 'purple' },
    };
    const attributes = attributeMap[item.status] || { label: 'Unknown', color: 'grey' };
    return span(
        {
            class: 'flex-row',
            style: `color: var(--${attributes.color});`,
        },
        attributes.label,
        () => {
            const tooltipError = van.state(false);
            return item.status === 'Error' && item.log_message ? i(
                {
                    class: 'material-symbols-rounded text-secondary ml-1',
                    style: 'position: relative; font-size: 16px;',
                    onmouseenter: () => tooltipError.val = true,
                    onmouseleave: () => tooltipError.val = false,
                },
                'info',
                Tooltip({ text: item.log_message, show: tooltipError }),
            ) : null;
        },
    );
}

export { TestRuns };
