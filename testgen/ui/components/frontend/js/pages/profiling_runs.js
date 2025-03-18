/**
 * @typedef ProfilingRun
 * @type {object}
 * @property {string} profiling_run_id
 * @property {number} start_time
 * @property {string} table_groups_name
 * @property {'Running'|'Complete'|'Error'|'Cancelled'} status
 * @property {string} log_message
 * @property {string} duration
 * @property {string} process_id
 * @property {string} schema_name
 * @property {number} column_ct
 * @property {number} table_ct
 * @property {number} anomaly_ct
 * @property {number} anomalies_definite_ct
 * @property {number} anomalies_likely_ct
 * @property {number} anomalies_possible_ct
 * @property {number} anomalies_dismissed_ct
 * @property {string} dq_score_profiling
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_run
 *
 * @typedef Properties
 * @type {object}
 * @property {ProfilingRun[]} items
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

const ProfilingRuns = (/** @type Properties */ props) => {
    window.testgen.isPage = true;

    const profilingRunItems = van.derive(() => {
        let items = [];
        try {
            items = JSON.parse(props.items?.val);
        } catch { }
        Streamlit.setFrameHeight(100 * items.length);
        return items;
    });
    const columns = ['20%', '20%', '20%', '30%', '10%'];

    const userCanRun = getValue(props.permissions)?.can_run ?? false;

    const tableId = 'profiling-runs-table';
    resizeFrameHeightToElement(tableId);

    return div(
        { class: 'table', id: tableId },
        div(
            { class: 'table-header flex-row' },
            span(
                { style: `flex: ${columns[0]}` },
                'Start Time | Table Group',
            ),
            span(
                { style: `flex: ${columns[1]}` },
                'Status | Duration',
            ),
            span(
                { style: `flex: ${columns[2]}` },
                'Schema',
            ),
            span(
                { style: `flex: ${columns[3]}` },
                'Hygiene Issues',
            ),
            span(
                { style: `flex: ${columns[4]}` },
                'Profiling Score',
            ),
        ),
        () => div(
            profilingRunItems.val.map(item => ProfilingRunItem(item, columns, userCanRun)),
        ),
    );
}

const ProfilingRunItem = (
    /** @type ProfilingRun */ item,
    /** @type string[] */ columns,
    /** @type boolean */ userCanRun,
) => {
    return div(
        { class: 'table-row flex-row' },
        div(
            { style: `flex: ${columns[0]}` },
            div(formatTimestamp(item.start_time)),
            div(
                { class: 'text-caption mt-1' },
                item.table_groups_name,
            ),
        ),
        div(
            { class: 'flex-row', style: `flex: ${columns[1]}` },
            div(
                ProfilingRunStatus(item),
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
            { style: `flex: ${columns[2]}` },
            div(item.schema_name),
            div(
                {
                    class: 'text-caption mt-1 mb-1',
                    style: item.status === 'Complete' && !item.column_ct ? 'color: var(--red);' : '',
                },
                item.status === 'Complete' ? `${item.table_ct || 0} tables, ${item.column_ct || 0} columns` : null,
            ),
            item.column_ct ? Link({
                label: 'View results',
                href: 'profiling-runs:results',
                params: { 'run_id': item.profiling_run_id },
                underline: true,
                right_icon: 'chevron_right',
            }) : null,
        ),
        div(
            { class: 'pr-3', style: `flex: ${columns[3]}` },
            item.anomaly_ct ? SummaryBar({
                items: [
                    { label: 'Definite', value: item.anomalies_definite_ct, color: 'red' },
                    { label: 'Likely', value: item.anomalies_likely_ct, color: 'orange' },
                    { label: 'Possible', value: item.anomalies_possible_ct, color: 'yellow' },
                    { label: 'Dismissed', value: item.anomalies_dismissed_ct, color: 'grey' },
                ],
                height: 10,
                width: 350,
            }) : '--',
            item.anomaly_ct ? Link({
                label: `View ${item.anomaly_ct} issues`,
                href: 'profiling-runs:hygiene',
                params: { 'run_id': item.profiling_run_id },
                underline: true,
                right_icon: 'chevron_right',
                style: 'margin-top: 8px;',
            }) : null,
        ),
        div(
            { style: `flex: ${columns[4]}; font-size: 16px;` },
            item.dq_score_profiling ?? '--',
        ),
    );
}

function ProfilingRunStatus(/** @type ProfilingRun */ item) {
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
                    class: 'material-symbols-rounded text-secondary ml-1 profiling-runs--info',
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

export { ProfilingRuns };
