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
import { emitEvent, getValue, resizeFrameHeightToElement } from '../utils.js';
import { formatTimestamp, formatDuration } from '../display_utils.js';

const { div, span, i } = van.tags;

const TestRuns = (/** @type Properties */ props) => {
    window.testgen.isPage = true;

    const testRunItems = van.derive(() => {
        let items = [];
        try {
            items = JSON.parse(props.items?.val);
        } catch { }
        Streamlit.setFrameHeight(100 * items.length);
        return items;
    });
    const columns = ['30%', '20%', '40%', '10%'];

    const userCanRun = getValue(props.permissions)?.can_run ?? false;

    const tableId = 'test-runs-table';
    resizeFrameHeightToElement(tableId);

    return div(
        { class: 'table', id: tableId },
        div(
            { class: 'table-header flex-row' },
            span(
                { style: `flex: ${columns[0]}` },
                'Start Time | Table Group | Test Suite',
            ),
            span(
                { style: `flex: ${columns[1]}` },
                'Status | Duration',
            ),
            span(
                { style: `flex: ${columns[2]}` },
                'Results Summary',
            ),
            span(
                { style: `flex: ${columns[3]}` },
                'Testing Score',
            ),
        ),
        () => div(
            testRunItems.val.map(item => TestRunItem(item, columns, userCanRun)),
        ),
    );
}

const TestRunItem = (
    /** @type TestRun */ item,
    /** @type string[] */ columns,
    /** @type boolean */ userCanRun,
) => {
    return div(
        { class: 'table-row flex-row' },
        div(
            { style: `flex: ${columns[0]}` },
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
            { class: 'flex-row', style: `flex: ${columns[1]}` },
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
            { class: 'pr-3', style: `flex: ${columns[2]}` },
            item.test_ct ? SummaryBar({
                items: [
                    { label: 'Passed', value: item.passed_ct, color: 'green' },
                    { label: 'Warning', value: item.warning_ct, color: 'yellow' },
                    { label: 'Failed', value: item.failed_ct, color: 'red' },
                    { label: 'Error', value: item.error_ct, color: 'brown' },
                    { label: 'Dismissed', value: item.dismissed_ct, color: 'grey' },
                ],
                height: 10,
                width: 400,
            }) : '--',
        ),
        div(
            { style: `flex: ${columns[3]}; font-size: 16px;` },
            item.dq_score_testing ?? '--',
        )
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
