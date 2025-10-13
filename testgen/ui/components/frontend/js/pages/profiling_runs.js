/**
 * @import { ProjectSummary } from '../types.js';
 * @import { SelectOption } from '../components/select.js';
 * 
 * @typedef ProfilingRun
 * @type {object}
 * @property {string} profiling_run_id
 * @property {number} start_time
 * @property {number} end_time
 * @property {string} table_groups_name
 * @property {'Running'|'Complete'|'Error'|'Cancelled'} status
 * @property {string} log_message
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
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {ProfilingRun[]} profiling_runs
 * @property {SelectOption[]} table_group_options
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { Tooltip } from '../components/tooltip.js';
import { SummaryCounts } from '../components/summary_counts.js';
import { Link } from '../components/link.js';
import { Button } from '../components/button.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { formatTimestamp, formatDuration } from '../display_utils.js';
import { Checkbox } from '../components/checkbox.js';
import { Select } from '../components/select.js';
import { Paginator } from '../components/paginator.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '../components/empty_state.js';

const { div, i, span, strong } = van.tags;
const PAGE_SIZE = 100;
const SCROLL_CONTAINER = window.top.document.querySelector('.stMain');

const ProfilingRuns = (/** @type Properties */ props) => {
    loadStylesheet('profilingRuns', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const columns = ['5%', '15%', '15%', '20%', '35%', '10%'];
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;

    const pageIndex = van.state(0);
    const profilingRuns = van.derive(() => {
        pageIndex.val = 0;
        return getValue(props.profiling_runs);
    });
    const paginatedRuns = van.derive(() => profilingRuns.val.slice(PAGE_SIZE * pageIndex.val, PAGE_SIZE * (pageIndex.val + 1)));

    const selectedRuns = {};
    const initializeSelectedStates = (items) => {
        for (const profilingRun of items) {
            if (selectedRuns[profilingRun.profiling_run_id] == undefined) {
                selectedRuns[profilingRun.profiling_run_id] = van.state(false);
            }
        }
    };
    initializeSelectedStates(profilingRuns.val);
    van.derive(() => initializeSelectedStates(profilingRuns.val));

    const wrapperId = 'profiling-runs-list-wrapper';
    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return div(
        { id: wrapperId },
        () => {
            const projectSummary = getValue(props.project_summary);
            return projectSummary.profiling_run_count > 0
            ? div(
                { class: 'tg-profiling-runs' },
                Toolbar(props, userCanEdit),
                () => profilingRuns.val.length
                ? div(
                    div(
                        { class: 'table' },
                        () => {
                            const selectedItems = profilingRuns.val.filter(i => selectedRuns[i.profiling_run_id]?.val ?? false);
                            const someRunSelected = selectedItems.length > 0;
                            const tooltipText = !someRunSelected ? 'No runs selected' : undefined;

                            if (!userCanEdit) {
                                return '';
                            }

                            return div(
                                { class: 'flex-row fx-justify-content-flex-end pb-2' },
                                someRunSelected ? strong({ class: 'mr-1' }, selectedItems.length) : '',
                                someRunSelected ? span({ class: 'mr-4' }, 'runs selected') : '',
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
                                const items = profilingRuns.val;
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
                            paginatedRuns.val.map(item => ProfilingRunItem(item, columns, selectedRuns[item.profiling_run_id], userCanEdit)),
                        ),
                    ),
                    Paginator({
                        pageIndex,
                        count: profilingRuns.val.length,
                        pageSize: PAGE_SIZE,
                        onChange: (newIndex) => {
                            if (newIndex !== pageIndex.val) {
                                pageIndex.val = newIndex;
                                SCROLL_CONTAINER.scrollTop = 0;
                            }
                        },
                    }),
                )
                : div(
                    { class: 'pt-7 text-secondary', style: 'text-align: center;' },
                    'No profiling runs found matching filters',
                ),
            )
            : ConditionalEmptyState(projectSummary, userCanEdit);
        }
    );
};

const Toolbar = (
    /** @type Properties */ props,
    /** @type boolean */ userCanEdit,
) => {
    return div(
        { class: 'flex-row fx-align-flex-end fx-justify-space-between mb-4 fx-gap-4' },
        () => Select({
            label: 'Table Group',
            value: getValue(props.table_group_options)?.find((op) => op.selected)?.value ?? null,
            options: getValue(props.table_group_options) ?? [],
            allowNull: true,
            style: 'font-size: 14px;',
            testId: 'table-group-filter',
            onChange: (value) => emitEvent('FilterApplied', { payload: { table_group_id: value } }),
        }),
        div(
            { class: 'flex-row fx-gap-4' },
            Button({
                icon: 'today',
                type: 'stroked',
                label: 'Profiling Schedules',
                tooltip: 'Manage when profiling should run for table groups',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--dk-card-background);',
                onclick: () => emitEvent('RunSchedulesClicked', {}),
            }),
            userCanEdit
                ? Button({
                    icon: 'play_arrow',
                    type: 'stroked',
                    label: 'Run Profiling',
                    width: 'fit-content',
                    style: 'background: var(--dk-card-background);',
                    onclick: () => emitEvent('RunProfilingClicked', {}),
                })
                : '',
            Button({
                type: 'icon',
                icon: 'refresh',
                tooltip: 'Refresh profiling runs list',
                tooltipPosition: 'left',
                style: 'border: var(--button-stroked-border); border-radius: 4px;',
                onclick: () => emitEvent('RefreshData', {}),
                testId: 'profiling-runs-refresh',
            }),
        ),
    );
};

const ProfilingRunItem = (
    /** @type ProfilingRun */ item,
    /** @type string[] */ columns,
    /** @type boolean */ selected,
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
            div({ 'data-testid': 'profiling-run-item-starttime' }, formatTimestamp(item.start_time)),
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
                    formatDuration(item.start_time, item.end_time),
                ),
            ),
            item.status === 'Running' && item.process_id && userCanEdit ? Button({
                type: 'stroked',
                label: 'Cancel Run',
                style: 'width: auto; height: 32px; color: var(--purple); margin-left: 16px;',
                onclick: () => emitEvent('RunCanceled', { payload: item }),
            }) : null,
        ),
        div(
            { style: `flex: ${columns[3]}` },
            div({ 'data-testid': 'profiling-run-item-schema' }, item.schema_name),
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
            item.anomaly_ct ? SummaryCounts({
                items: [
                    { label: 'Definite', value: item.anomalies_definite_ct, color: 'red' },
                    { label: 'Likely', value: item.anomalies_likely_ct, color: 'orange' },
                    { label: 'Possible', value: item.anomalies_possible_ct, color: 'yellow' },
                    { label: 'Dismissed', value: item.anomalies_dismissed_ct, color: 'grey' },
                ],
            }) : '--',
            item.anomaly_ct ? Link({
                label: `View ${item.anomaly_ct} issues`,
                href: 'profiling-runs:hygiene',
                params: { 'run_id': item.profiling_run_id },
                underline: true,
                right_icon: 'chevron_right',
                style: 'margin-top: 4px;',
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

const ConditionalEmptyState = (
    /** @type ProjectSummary */ projectSummary,
    /** @type boolean */ userCanEdit,
) => {
    let args = {
        message: EMPTY_STATE_MESSAGE.profiling,
        button: Button({
            icon: 'play_arrow',
            type: 'stroked',
            color: 'primary',
            label: 'Run Profiling',
            width: 'fit-content',
            style: 'margin: auto; background: var(--dk-card-background);',
            disabled: !userCanEdit,
            tooltip: userCanEdit ? null : DISABLED_ACTION_TEXT,
            tooltipPosition: 'bottom',
            onclick: () => emitEvent('RunProfilingClicked', {}),
        }),
    };

    if (projectSummary.connection_count <= 0) {
        args = {
            message: EMPTY_STATE_MESSAGE.connection,
            link: {
                label: 'Go to Connections',
                href: 'connections',
                params: { project_code: projectSummary.project_code },
            },
        };
    } else if (projectSummary.table_group_count <= 0) {
        args = {
            message: EMPTY_STATE_MESSAGE.tableGroup,
            link: {
                label: 'Go to Table Groups',
                href: 'table-groups',
                params: { project_code: projectSummary.project_code, connection_id: projectSummary.default_connection_id },
            },
        };
    }

    return EmptyState({
        icon: 'data_thresholding',
        label: 'No profiling runs yet',
        ...args,
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-profiling-runs {
    min-height: 500px;
}
`);

export { ProfilingRuns };
