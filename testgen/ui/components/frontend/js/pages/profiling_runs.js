/**
 * @import { FilterOption, ProjectSummary } from '../types.js'; *
 *
 * @typedef ProgressStep
 * @type {object}
 * @property {'data_chars'|'col_profiling'|'freq_analysis'|'hygiene_issues'} key
 * @property {'Pending'|'Running'|'Completed'|'Warning'} status
 * @property {string} label
 * @property {string} detail
 *
 * @typedef ProfilingRun
 * @type {object}
 * @property {string} id
 * @property {number} profiling_starttime
 * @property {number} profiling_endtime
 * @property {string} table_groups_name
 * @property {'Running'|'Complete'|'Error'|'Cancelled'} status
 * @property {ProgressStep[]} progress
 * @property {string} log_message
 * @property {string} process_id
 * @property {string} table_group_schema
 * @property {number} column_ct
 * @property {number} table_ct
 * @property {number} record_ct
 * @property {number} data_point_ct
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
 * @property {FilterOption[]} table_group_options
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { withTooltip } from '../components/tooltip.js';
import { SummaryCounts } from '../components/summary_counts.js';
import { Link } from '../components/link.js';
import { Button } from '../components/button.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { formatTimestamp, formatDuration, formatNumber } from '../display_utils.js';
import { Checkbox } from '../components/checkbox.js';
import { Select } from '../components/select.js';
import { Paginator } from '../components/paginator.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '../components/empty_state.js';
import { Icon } from '../components/icon.js';

const { div, i, span, strong } = van.tags;
const PAGE_SIZE = 100;
const SCROLL_CONTAINER = window.top.document.querySelector('.stMain');
const REFRESH_INTERVAL = 15000 // 15 seconds

const progressStatusIcons = {
    Pending: { color: 'grey', icon: 'more_horiz', size: 22 },
    Running: { color: 'blue', icon: 'autoplay', size: 18 },
    Completed: { color: 'green', icon: 'check', size: 24 },
    Warning: { color: 'orange', icon: 'warning', size: 20 },
};

const ProfilingRuns = (/** @type Properties */ props) => {
    loadStylesheet('profilingRuns', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const columns = ['5%', '20%', '15%', '20%', '30%', '10%'];
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;

    const pageIndex = van.state(0);
    const profilingRuns = van.derive(() => {
        pageIndex.val = 0;
        return getValue(props.profiling_runs);
    });
    let refreshIntervalId = null;

    const paginatedRuns = van.derive(() => {
        const paginated = profilingRuns.val.slice(PAGE_SIZE * pageIndex.val, PAGE_SIZE * (pageIndex.val + 1));
        const hasActiveRuns = paginated.some(({ status }) => status === 'Running');
        if (!refreshIntervalId && hasActiveRuns) {
            refreshIntervalId = setInterval(() => emitEvent('RefreshData', {}), REFRESH_INTERVAL);
        } else if (refreshIntervalId && !hasActiveRuns) {
            clearInterval(refreshIntervalId);
        }
        return paginated;
    });

    const selectedRuns = {};
    const initializeSelectedStates = (items) => {
        for (const profilingRun of items) {
            if (selectedRuns[profilingRun.id] == undefined) {
                selectedRuns[profilingRun.id] = van.state(false);
            }
        }
    };
    initializeSelectedStates(profilingRuns.val);
    van.derive(() => initializeSelectedStates(profilingRuns.val));

    const wrapperId = 'profiling-runs-list-wrapper';
    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return div(
        { id: wrapperId, class: 'tg-profiling-runs' },
        () => {
            const projectSummary = getValue(props.project_summary);
            return projectSummary.profiling_run_count > 0
            ? div(
                Toolbar(props, userCanEdit),
                () => profilingRuns.val.length
                ? div(
                    div(
                        { class: 'table pb-0', style: 'overflow-y: auto;' },
                        () => {
                            const selectedItems = profilingRuns.val.filter(i => selectedRuns[i.id]?.val ?? false);
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
                                    onclick: () => emitEvent('RunsDeleted', { payload: selectedItems.map(i => i.id) }),
                                }),
                            );
                        },
                        div(
                            { class: 'table-header flex-row' },
                            () => {
                                const items = profilingRuns.val;
                                const selectedItems = items.filter(i => selectedRuns[i.id]?.val ?? false);
                                const allSelected = selectedItems.length === items.length;
                                const partiallySelected = selectedItems.length > 0 && selectedItems.length < items.length;

                                if (!userCanEdit) {
                                    return '';
                                }

                                return span(
                                    { style: `flex: 0 0 ${columns[0]}` },
                                    userCanEdit
                                        ? Checkbox({
                                            checked: allSelected,
                                            indeterminate: partiallySelected,
                                            onChange: (checked) => items.forEach(item => selectedRuns[item.id].val = checked),
                                            testId: 'select-all-profiling-run',
                                        })
                                        : '',
                                );
                            },
                            span(
                                { style: `flex: 0 0 ${columns[1]}` },
                                'Start Time | Table Group',
                            ),
                            span(
                                { style: `flex: 0 0 ${columns[2]}` },
                                'Status | Duration',
                            ),
                            span(
                                { style: `flex: 0 0 ${columns[3]}` },
                                'Schema',
                            ),
                            span(
                                { style: `flex: 0 0 ${columns[4]}`, class: 'tg-profiling-runs--issues' },
                                'Hygiene Issues',
                            ),
                            span(
                                { style: `flex: 0 0 ${columns[5]}` },
                                'Profiling Score',
                            ),
                        ),
                        div(
                            paginatedRuns.val.map(item => ProfilingRunItem(item, columns, selectedRuns[item.id], userCanEdit)),
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
        { class: 'flex-row fx-align-flex-end fx-justify-space-between mb-4 fx-gap-4 fx-flex-wrap' },
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
                icon: 'notifications',
                type: 'stroked',
                label: 'Notifications',
                tooltip: 'Configure email notifications for profiling runs',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--dk-card-background);',
                onclick: () => emitEvent('RunNotificationsClicked', {}),
            }),
            Button({
                icon: 'today',
                type: 'stroked',
                label: 'Schedules',
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
    const runningStep = item.progress?.find((item) => item.status === 'Running');

    return div(
        { class: 'table-row flex-row', 'data-testid': 'profiling-run-item' },
        userCanEdit
            ? div(
                { style: `flex: 0 0 ${columns[0]}; font-size: 16px;` },
                Checkbox({
                    checked: selected,
                    onChange: (checked) => selected.val = checked,
                    testId: 'select-profiling-run',
                }),
            )
            : '',
        div(
            { style: `flex: 0 0 ${columns[1]}; max-width: ${columns[1]}; word-wrap: break-word;` },
            div({ 'data-testid': 'profiling-run-item-starttime' }, formatTimestamp(item.profiling_starttime)),
            div(
                { class: 'text-caption mt-1', 'data-testid': 'profiling-run-item-tablegroup' },
                item.table_groups_name,
            ),
        ),
        div(
            { style: `flex: 0 0 ${columns[2]};  max-width: ${columns[2]};` },
            div(
                { class: 'flex-row' },
                ProfilingRunStatus(item),
                item.status === 'Running' && item.process_id && userCanEdit ? Button({
                    type: 'stroked',
                    label: 'Cancel',
                    style: 'width: 64px; height: 28px; color: var(--purple); margin-left: 12px;',
                    onclick: () => emitEvent('RunCanceled', { payload: item }),
                }) : null,
            ),
            item.profiling_endtime
                ? div(
                    { class: 'text-caption mt-1', 'data-testid': 'profiling-run-item-duration' },
                    formatDuration(item.profiling_starttime, item.profiling_endtime),
                )
                : div(
                    { class: 'text-caption mt-1' },
                    item.status === 'Running' && runningStep
                        ? [
                            div(
                                runningStep.label,
                                withTooltip(
                                    Icon({ style: 'font-size: 18px; margin-left: 4px; vertical-align: middle;' }, 'info'),
                                    { text: ProgressTooltip(item) },
                                ),
                            ),
                            div(runningStep.detail),
                        ]
                        : '--',
                ),
        ),
        div(
            { style: `flex: 0 0 ${columns[3]}; max-width: ${columns[3]};` },
            div({ 'data-testid': 'profiling-run-item-schema' }, item.table_group_schema),
            div(
                {
                    class: 'text-caption mt-1 mb-1',
                    style: item.status === 'Complete' && !item.column_ct ? 'color: var(--red);' : '',
                    'data-testid': 'profiling-run-item-counts',
                },
                item.column_ct !== null
                    ? div(
                        `${formatNumber(item.table_ct || 0)} tables, ${formatNumber(item.column_ct || 0)} columns`,
                        item.record_ct !== null ?
                            withTooltip(
                                Icon({ style: 'font-size: 16px; margin-left: 4px; vertical-align: middle;' }, 'more' ),
                                { text: [
                                    div(`${formatNumber(item.record_ct || 0)} records`),
                                    div(`${formatNumber(item.data_point_ct || 0)} data points`),
                                ] },
                            )
                            : null,
                    )
                    : null,
            ),
            item.status === 'Complete' && item.column_ct ? Link({
                label: 'View results',
                href: 'profiling-runs:results',
                params: { 'run_id': item.id },
                underline: true,
                right_icon: 'chevron_right',
            }) : null,
        ),
        div(
            { class: 'pr-3 tg-profiling-runs--issues', style: `flex: 0 0 ${columns[4]};  max-width: ${columns[4]};` },
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
                params: { 'run_id': item.id },
                underline: true,
                right_icon: 'chevron_right',
                style: 'margin-top: 4px;',
                'data-testid': 'profiling-run-item-viewissues'
            }) : null,
        ),
        div(
            { style: `flex: 0 0 ${columns[5]};  max-width: ${columns[5]}; font-size: 16px;` },
            item.column_ct && item.dq_score_profiling
                ? item.dq_score_profiling
                : '--',
        ),
    );
}

const ProfilingRunStatus = (/** @type ProfilingRun */ item) => {
    const attributeMap = {
        Running: { label: 'Running', color: 'blue' },
        Complete: { label: 'Completed', color: '' },
        Error: { label: 'Error', color: 'red' },
        Cancelled: { label: 'Canceled', color: 'purple' },
    };
    const attributes = attributeMap[item.status] || { label: 'Unknown', color: 'grey' };
    const hasProgressError = item.progress?.some(({error}) => !!error);
    return span(
        {
            class: 'flex-row',
            style: `color: var(--${attributes.color});`,
            'data-testid': 'profiling-run-item-status'
        },
        attributes.label,
        item.status === 'Complete' && hasProgressError
            ? withTooltip(
                Icon({ style: 'font-size: 18px; margin-left: 4px; vertical-align: middle; color: var(--orange);' }, 'warning' ),
                { text: ProgressTooltip(item) },
            )
            : null,
        item.status === 'Error' && item.log_message
            ? withTooltip(
                Icon({ style: 'font-size: 18px; margin-left: 4px;' }, 'info'),
                { text: item.log_message, width: 250, style: 'word-break: break-word;' },
            )
            : null,
    );
};

const ProgressTooltip = (/** @type ProfilingRun */ item) => {
    return div(
        { class: 'flex-column fx-gap-1' },
        item.progress?.map(step => {
            const stepIcon = progressStatusIcons[step.status];
            return div(
                { class: 'flex-row fx-gap-1' },
                Icon(
                    { style: `font-size: ${stepIcon.size}px; color: var(--${stepIcon.color}); min-width: 24px;` },
                    stepIcon.icon,
                ),
                div(
                    { class: 'flex-column fx-align-flex-start text-left' },
                    span(`${step.label}${step.detail ? (': ' + step.detail) : ''}`),
                    span({ style: 'font-size: 12px; opacity: 0.6; margin-top: 2px;' }, step.error),
                ),
            );
        }),
    );
};

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
    min-height: 550px;
}

.tg-profiling-runs--issues {
    min-width: 310px;
}
`);

export { ProfilingRuns };
