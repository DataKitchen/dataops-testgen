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
 * @property {string} job_execution_id
 * @property {string?} profiling_run_id
 * @property {string} status
 * @property {string} status_label
 * @property {number} created_at
 * @property {number?} started_at
 * @property {number?} completed_at
 * @property {string?} error_message
 * @property {ProgressStep[]} progress
 * @property {string} table_groups_name
 * @property {string} table_group_schema
 * @property {string?} log_message
 * @property {string?} process_id
 * @property {number?} column_ct
 * @property {number?} table_ct
 * @property {number?} record_ct
 * @property {number?} data_point_ct
 * @property {number?} anomaly_ct
 * @property {number?} anomalies_definite_ct
 * @property {number?} anomalies_likely_ct
 * @property {number?} anomalies_possible_ct
 * @property {number?} anomalies_dismissed_ct
 * @property {string?} dq_score_profiling
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {ProfilingRun[]} profiling_runs
 * @property {number} total_count
 * @property {number} page
 * @property {number} page_size
 * @property {FilterOption[]} table_group_options
 * @property {Permissions} permissions
 * @property {object?} run_profiling_dialog
 * @property {object?} schedule_dialog
 * @property {object?} notifications_dialog
 */
import van from '/app/static/js/van.min.js';
import { withTooltip } from '/app/static/js/components/tooltip.js';
import { SummaryCounts } from '/app/static/js/components/summary_counts.js';
import { Link } from '/app/static/js/components/link.js';
import { Button } from '/app/static/js/components/button.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { formatTimestamp, formatDuration, formatNumber, DISABLED_ACTION_TEXT } from '/app/static/js/display_utils.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { Select } from '/app/static/js/components/select.js';
import { Paginator } from '/app/static/js/components/paginator.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '/app/static/js/components/empty_state.js';
import { Icon } from '/app/static/js/components/icon.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { RunProfilingDialog } from '/app/static/js/components/run_profiling_dialog.js';
import { ScheduleList } from '/app/static/js/components/schedule_list.js';
import { NotificationSettings } from '/app/static/js/components/notification_settings.js';

const { b, div, i, span, strong } = van.tags;
const SCROLL_CONTAINER = window.top.document.querySelector('.stMain');

const STARTING_STATUSES = new Set(['pending', 'claimed']);
const RUNNING_STATUSES = new Set(['running', 'cancel_requested']);
const ACTIVE_STATUSES = new Set([...STARTING_STATUSES, ...RUNNING_STATUSES]);
const CANCELABLE_STATUSES = new Set(['pending', 'claimed', 'running']);

const REFRESH_STARTING = 6000;
const REFRESH_RUNNING = 30000;
const REFRESH_DEFAULT = 60000;

const progressStatusIcons = {
    Pending: { color: 'grey', icon: 'more_horiz', size: 22 },
    Running: { color: 'blue', icon: 'autoplay', size: 18 },
    Completed: { color: 'green', icon: 'check', size: 24 },
    Warning: { color: 'orange', icon: 'warning', size: 20 },
};

const ProfilingRuns = (/** @type Properties */ props) => {
    const { emit } = props;
    loadStylesheet('profilingRuns', stylesheet);

    const columns = ['5%', '20%', '15%', '20%', '30%', '10%'];
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;

    const profilingRuns = van.derive(() => getValue(props.profiling_runs));
    let refreshIntervalId = null;

    let currentRefreshRate = null;
    van.derive(() => {
        const items = profilingRuns.val;
        const hasStarting = items.some(({ status }) => STARTING_STATUSES.has(status));
        const hasRunning = items.some(({ status }) => RUNNING_STATUSES.has(status));
        const rate = hasStarting ? REFRESH_STARTING : hasRunning ? REFRESH_RUNNING : REFRESH_DEFAULT;
        if (rate !== currentRefreshRate) {
            if (refreshIntervalId) clearInterval(refreshIntervalId);
            refreshIntervalId = setInterval(() => emit('RefreshData', {}), rate);
            currentRefreshRate = rate;
        }
    });

    const selectedRuns = {};
    const initializeSelectedStates = (items) => {
        for (const profilingRun of items) {
            if (selectedRuns[profilingRun.job_execution_id] == undefined) {
                selectedRuns[profilingRun.job_execution_id] = van.state(false);
            }
        }
    };
    initializeSelectedStates(profilingRuns.val);
    van.derive(() => initializeSelectedStates(profilingRuns.val));

    const runsToDelete = van.state([]);
    const deleteConstraintChecked = van.state(false);

    const closeDeleteDialog = () => {
        runsToDelete.val = [];
        deleteConstraintChecked.val = false;
    };

    const scheduleDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.schedule_dialog)?.open) scheduleDialogOpen.val = true; });

    const notificationsDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.notifications_dialog)?.open) notificationsDialogOpen.val = true; });

    let runProfilingDialogEl = null;

    const wrapperId = 'profiling-runs-list-wrapper';

    return div(
        { id: wrapperId, 'data-testid': 'profiling-runs', class: 'tg-profiling-runs' },
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
                            const selectedItems = profilingRuns.val.filter(i => selectedRuns[i.job_execution_id]?.val ?? false);
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
                                    onclick: () => {
                                        runsToDelete.val = [...selectedItems];
                                    },
                                }),
                            );
                        },
                        div(
                            { class: 'table-header flex-row' },
                            () => {
                                const items = profilingRuns.val;
                                const selectedItems = items.filter(i => selectedRuns[i.job_execution_id]?.val ?? false);
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
                                            onChange: (checked) => items.forEach(item => selectedRuns[item.job_execution_id].val = checked),
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
                            profilingRuns.val.map(item => ProfilingRunItem(item, columns, selectedRuns[item.job_execution_id], userCanEdit, projectSummary.project_code, emit)),
                        ),
                    ),
                    () => {
                        const totalCount = getValue(props.total_count) ?? 0;
                        const pageSize = getValue(props.page_size) ?? 100;
                        const currentPage = (getValue(props.page) ?? 1) - 1;
                        return Paginator({
                            pageIndex: van.state(currentPage),
                            count: totalCount,
                            pageSize,
                            onChange: (newIndex) => {
                                if (newIndex !== currentPage) {
                                    emit('PageChanged', { payload: newIndex + 1 });
                                    SCROLL_CONTAINER.scrollTop = 0;
                                }
                            },
                        });
                    },
                )
                : div(
                    { class: 'pt-7 text-secondary', style: 'text-align: center;' },
                    'No profiling runs found matching filters',
                ),
            )
            : ConditionalEmptyState(projectSummary, userCanEdit, emit);
        },
        Dialog(
            { title: 'Delete Profiling Runs', open: van.derive(() => runsToDelete.val.length > 0), onClose: closeDeleteDialog },
            div(
                { class: 'flex-column fx-gap-4' },
                () => {
                    const runs = runsToDelete.val;
                    const hasRunning = runs.some(r => ACTIVE_STATUSES.has(r.status));
                    return div(
                        { class: 'flex-column fx-gap-3' },
                        div('Are you sure you want to delete ', b(runs.length), ` profiling run${runs.length !== 1 ? 's' : ''}?`),
                        hasRunning
                            ? div(
                                { class: 'flex-column fx-gap-2' },
                                div({ style: 'color: var(--orange);' }, 'Any running processes will be canceled.'),
                                Checkbox({
                                    label: runs.length === 1
                                        ? 'Yes, cancel and delete the profiling run'
                                        : 'Yes, cancel and delete the profiling runs',
                                    checked: deleteConstraintChecked,
                                    onChange: (checked) => { deleteConstraintChecked.val = checked; },
                                }),
                            )
                            : null,
                    );
                },
                div(
                    { class: 'flex-row fx-justify-flex-end' },
                    () => {
                        const isDisabled = runsToDelete.val.some(r => ACTIVE_STATUSES.has(r.status)) && !deleteConstraintChecked.val;
                        return Button({
                            label: 'Delete',
                            color: isDisabled ? 'basic' : 'warn',
                            type: isDisabled ? 'stroked' : 'flat',
                            width: 'auto',
                            style: 'margin-left: auto;',
                            disabled: isDisabled,
                            onclick: () => {
                                emit('RunsDeleted', { payload: runsToDelete.val.map(r => r.job_execution_id) });
                                closeDeleteDialog();
                            },
                        });
                    },
                ),
            ),
        ),
        () => {
            const info = getValue(props.run_profiling_dialog);
            if (!info) {
                runProfilingDialogEl = null;
                return div();
            }
            return (runProfilingDialogEl ??= RunProfilingDialog({ emit,
                dialog: { title: info.title ?? 'Run Profiling', open: true },
                table_groups: info.table_groups ?? [],
                allow_selection: info.allow_selection ?? false,
                selected_id: info.selected_id,
                result: van.derive(() => getValue(props.run_profiling_dialog)?.result),
                onClose: () => emit('RunProfilingDialogClosed', {}),
            }));
        },
        ScheduleList({ emit,
            dialog: van.derive(() => ({
                title: getValue(props.schedule_dialog)?.title ?? 'Schedules',
                open: scheduleDialogOpen,
            })),
            items: van.derive(() => getValue(props.schedule_dialog)?.items ?? []),
            permissions: van.derive(() => getValue(props.schedule_dialog)?.permissions ?? { can_edit: false }),
            arg_label: van.derive(() => getValue(props.schedule_dialog)?.arg_label ?? ''),
            arg_values: van.derive(() => getValue(props.schedule_dialog)?.arg_values ?? []),
            sample: van.derive(() => getValue(props.schedule_dialog)?.sample),
            results: van.derive(() => getValue(props.schedule_dialog)?.results),
            onClose: () => emit('ScheduleDialogClosed', {}),
        }),
        NotificationSettings({ emit,
            dialog: van.derive(() => ({
                title: getValue(props.notifications_dialog)?.title ?? 'Notifications',
                open: notificationsDialogOpen,
            })),
            smtp_configured: van.derive(() => getValue(props.notifications_dialog)?.smtp_configured ?? false),
            event: van.derive(() => getValue(props.notifications_dialog)?.event),
            items: van.derive(() => getValue(props.notifications_dialog)?.items ?? []),
            permissions: van.derive(() => getValue(props.notifications_dialog)?.permissions ?? { can_edit: false }),
            scope_label: van.derive(() => getValue(props.notifications_dialog)?.scope_label),
            scope_options: van.derive(() => getValue(props.notifications_dialog)?.scope_options ?? []),
            trigger_options: van.derive(() => getValue(props.notifications_dialog)?.trigger_options ?? []),
            cde_enabled: van.derive(() => getValue(props.notifications_dialog)?.cde_enabled ?? false),
            total_enabled: van.derive(() => getValue(props.notifications_dialog)?.total_enabled ?? false),
            result: van.derive(() => getValue(props.notifications_dialog)?.result),
            onClose: () => emit('NotificationsDialogClosed', {}),
        }),
    );
};

const Toolbar = (
    /** @type Properties */ props,
    /** @type boolean */ userCanEdit,
) => {
    const emit = props.emit;
    return div(
        { class: 'flex-row fx-align-flex-end fx-justify-space-between mb-4 fx-gap-4 fx-flex-wrap' },
        () => Select({
            label: 'Table Group',
            value: getValue(props.table_group_options)?.find((op) => op.selected)?.value ?? null,
            options: getValue(props.table_group_options) ?? [],
            allowNull: true,
            style: 'font-size: 14px;',
            testId: 'table-group-filter',
            onChange: (value) => emit('FilterApplied', { payload: { table_group_id: value } }),
        }),
        div(
            { class: 'flex-row fx-gap-3' },
            Button({
                icon: 'notifications',
                type: 'stroked',
                label: 'Notifications',
                tooltip: 'Configure email notifications for profiling runs',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('RunNotificationsClicked', {}),
            }),
            Button({
                icon: 'today',
                type: 'stroked',
                label: 'Schedules',
                tooltip: 'Manage when profiling should run for table groups',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('RunSchedulesClicked', {}),
            }),
            userCanEdit
                ? Button({
                    icon: 'play_arrow',
                    type: 'stroked',
                    label: 'Run Profiling',
                    width: 'fit-content',
                    style: 'background: var(--button-generic-background-color);',
                    onclick: () => emit('RunProfilingClicked', {}),
                })
                : '',
            Button({
                type: 'stroked',
                icon: 'refresh',
                tooltip: 'Refresh profiling runs list',
                tooltipPosition: 'left',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('RefreshData', {}),
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
    /** @type string */ projectCode,
    emit,
) => {
    const runningStep = item.progress?.find((step) => step.status === 'Running');
    const displayTime = item.created_at;

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
            div({ 'data-testid': 'profiling-run-item-starttime' }, formatTimestamp(displayTime)),
            div(
                { class: 'text-caption mt-1', 'data-testid': 'profiling-run-item-tablegroup' },
                item.table_groups_name || '--',
            ),
        ),
        div(
            { style: `flex: 0 0 ${columns[2]};  max-width: ${columns[2]};` },
            div(
                { class: 'flex-row' },
                ProfilingRunStatus(item),
                CANCELABLE_STATUSES.has(item.status) && userCanEdit ? Button({
                    type: 'stroked',
                    label: 'Cancel',
                    style: 'width: 64px; height: 28px; color: var(--purple); margin-left: 12px;',
                    onclick: () => {
                        emit('RunCanceled', { payload: { job_execution_id: item.job_execution_id, profiling_run_id: item.profiling_run_id } });
                    },
                }) : null,
            ),
            item.completed_at && item.started_at
                ? div(
                    { class: 'text-caption mt-1', 'data-testid': 'profiling-run-item-duration' },
                    formatDuration(item.started_at, item.completed_at),
                )
                : div(
                    { class: 'text-caption mt-1' },
                    item.status === 'running' && runningStep
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
            div({ 'data-testid': 'profiling-run-item-schema' }, item.table_group_schema || '--'),
            div(
                {
                    class: 'text-caption mt-1 mb-1',
                    style: item.status === 'completed' && !item.column_ct ? 'color: var(--red);' : '',
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
            item.status === 'completed' && item.column_ct && item.profiling_run_id ? Link({ emit,
                label: 'View results',
                href: 'profiling-runs:results',
                params: { 'run_id': item.profiling_run_id, 'project_code': projectCode },
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
            item.anomaly_ct && item.profiling_run_id ? Link({ emit,
                label: `View ${item.anomaly_ct} issues`,
                href: 'profiling-runs:hygiene',
                params: { 'run_id': item.profiling_run_id, 'project_code': projectCode },
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
    const statusColorMap = {
        pending: 'grey',
        claimed: 'grey',
        running: 'blue',
        completed: '',
        error: 'red',
        canceled: 'purple',
        cancel_requested: 'grey',
    };
    const color = statusColorMap[item.status] ?? 'grey';
    const hasProgressError = item.progress?.some(({error}) => !!error);
    const errorMessage = item.error_message || item.log_message;
    return span(
        {
            class: 'flex-row',
            style: `color: var(--${color});`,
            'data-testid': 'profiling-run-item-status'
        },
        item.status_label,
        item.status === 'completed' && hasProgressError
            ? withTooltip(
                Icon({ style: 'font-size: 18px; margin-left: 4px; vertical-align: middle; color: var(--orange);' }, 'warning' ),
                { text: ProgressTooltip(item) },
            )
            : null,
        item.status === 'error' && errorMessage
            ? withTooltip(
                Icon({ style: 'font-size: 18px; margin-left: 4px;' }, 'info'),
                { text: errorMessage, width: 250, style: 'word-break: break-word;' },
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
    emit,
) => {
    let args = {
        message: EMPTY_STATE_MESSAGE.profiling,
        button: Button({
            icon: 'play_arrow',
            type: 'stroked',
            color: 'primary',
            label: 'Run Profiling',
            width: 'fit-content',
            style: 'margin: auto; background: var(--button-generic-background-color);',
            disabled: !userCanEdit,
            tooltip: userCanEdit ? null : DISABLED_ACTION_TEXT,
            tooltipPosition: 'bottom',
            onclick: () => emit('RunProfilingClicked', {}),
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

    return EmptyState({ emit,
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

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, ProfilingRuns(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
