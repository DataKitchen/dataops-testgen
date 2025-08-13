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
import { emitEvent, getValue, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { formatTimestamp, formatDuration } from '../display_utils.js';
import { Checkbox } from '../components/checkbox.js';

const { div, i, span, strong } = van.tags;

const ProfilingRuns = (/** @type Properties */ props) => {
    window.testgen.isPage = true;

    const profilingRunItems = van.derive(() => {
        let items = [];
        try {
            items = JSON.parse(props.items?.val);
        } catch { }
        Streamlit.setFrameHeight(100 * items.length || 150);
        return items;
    });
    const columns = ['5%', '15%', '20%', '20%', '30%', '10%'];

    const userCanRun = getValue(props.permissions)?.can_run ?? false;
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;
    const selectedRuns = {};

    const tableId = 'profiling-runs-table';
    resizeFrameHeightToElement(tableId);
    resizeFrameHeightOnDOMChange(tableId);

    const initializeSelectedStates = (items) => {
        for (const profilingRun of items) {
            if (selectedRuns[profilingRun.profiling_run_id] == undefined) {
                selectedRuns[profilingRun.profiling_run_id] = van.state(false);
            }
        }
    };

    initializeSelectedStates(profilingRunItems.val);

    van.derive(() => {
        initializeSelectedStates(profilingRunItems.val);
    });

    return () => getValue(profilingRunItems).length
    ? div(
        { class: 'table', id: tableId },
        () => {
            const items = profilingRunItems.val;
            const selectedItems = items.filter(i => selectedRuns[i.profiling_run_id]?.val ?? false);
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
                    onclick: () => emitEvent('RunsDeleted', { payload: selectedItems.map(i => i.profiling_run_id) }),
                }),
            );
        },
        div(
            { class: 'table-header flex-row' },
            () => {
                const items = profilingRunItems.val;
                const selectedItems = items.filter(i => selectedRuns[i.profiling_run_id]?.val ?? false);
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
                            onChange: (checked) => items.forEach(item => selectedRuns[item.profiling_run_id].val = checked),
                            testId: 'select-all-profiling-run',
                        })
                        : '',
                );
            },
            span(
                { style: `flex: ${columns[1]}` },
                'Start Time | Table Group',
            ),
            span(
                { style: `flex: ${columns[2]}` },
                'Status | Duration',
            ),
            span(
                { style: `flex: ${columns[3]}` },
                'Schema',
            ),
            span(
                { style: `flex: ${columns[4]}` },
                'Hygiene Issues',
            ),
            span(
                { style: `flex: ${columns[5]}` },
                'Profiling Score',
            ),
        ),
        div(
            profilingRunItems.val.map(item => ProfilingRunItem(item, columns, selectedRuns[item.profiling_run_id], userCanRun, userCanEdit)),
        ),
    )
    : div(
        { class: 'pt-7 text-secondary', style: 'text-align: center;' },
        'No profiling runs found matching filters',
    );
}

const ProfilingRunItem = (
    /** @type ProfilingRun */ item,
    /** @type string[] */ columns,
    /** @type boolean */ selected,
    /** @type boolean */ userCanRun,
    /** @type boolean */ userCanEdit,
) => {
    return div(
        { class: 'table-row flex-row', 'data-testid': 'profiling-run-item' },
        userCanEdit
            ? div(
                { style: `flex: ${columns[0]}; font-size: 16px;` },
                Checkbox({
                    checked: selected,
                    onChange: (checked) => selected.val = checked,
                    testId: 'select-profiling-run',
                }),
            )
            : '',
        div(
            { style: `flex: ${columns[1]}` },
            div({'data-testid': 'profiling-run-item-starttime'}, formatTimestamp(item.start_time)),
            div(
                { class: 'text-caption mt-1', 'data-testid': 'profiling-run-item-tablegroup' },
                item.table_groups_name,
            ),
        ),
        div(
            { class: 'flex-row', style: `flex: ${columns[2]}` },
            div(
                ProfilingRunStatus(item),
                div(
                    { class: 'text-caption mt-1', 'data-testid': 'profiling-run-item-duration' },
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
            { style: `flex: ${columns[3]}` },
            div({'data-testid': 'profiling-run-item-schema'}, item.schema_name),
            div(
                {
                    class: 'text-caption mt-1 mb-1',
                    style: item.status === 'Complete' && !item.column_ct ? 'color: var(--red);' : '',
                    'data-testid': 'profiling-run-item-counts',
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
            { class: 'pr-3', style: `flex: ${columns[4]}` },
            item.anomaly_ct ? SummaryBar({
                items: [
                    { label: 'Definite', value: item.anomalies_definite_ct, color: 'red' },
                    { label: 'Likely', value: item.anomalies_likely_ct, color: 'orange' },
                    { label: 'Possible', value: item.anomalies_possible_ct, color: 'yellow' },
                    { label: 'Dismissed', value: item.anomalies_dismissed_ct, color: 'grey' },
                ],
                height: 3,
                width: 350,
            }) : '--',
            item.anomaly_ct ? Link({
                label: `View ${item.anomaly_ct} issues`,
                href: 'profiling-runs:hygiene',
                params: { 'run_id': item.profiling_run_id },
                underline: true,
                right_icon: 'chevron_right',
                style: 'margin-top: 8px;',
                'data-testid': 'profiling-run-item-viewissues'
            }) : null,
        ),
        div(
            { style: `flex: ${columns[5]}; font-size: 16px;` },
            item.column_ct && item.dq_score_profiling
                ? item.dq_score_profiling
                : '--',
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
            'data-testid': 'profiling-run-item-status'
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
