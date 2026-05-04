/**
* @import { FilterOption, ProjectSummary } from '../types.js';
 *
 * @typedef ProgressStep
 * @type {object}
 * @property {'data_chars'|'validation'|'QUERY'|'CAT'|'METADATA'} key
 * @property {'Pending'|'Running'|'Completed'|'Warning'} status
 * @property {string} label
 * @property {string} detail
 *
 * @typedef TestRun
 * @type {object}
 * @property {string} job_execution_id
 * @property {string?} test_run_id
 * @property {string} status
 * @property {string} status_label
 * @property {number} created_at
 * @property {number?} started_at
 * @property {number?} completed_at
 * @property {string?} error_message
 * @property {ProgressStep[]} progress
 * @property {string} table_groups_name
 * @property {string} test_suite
 * @property {string?} log_message
 * @property {string?} process_id
 * @property {number?} test_ct
 * @property {number?} passed_ct
 * @property {number?} warning_ct
 * @property {number?} failed_ct
 * @property {number?} error_ct
 * @property {number?} log_ct
 * @property {number?} dismissed_ct
 * @property {string?} dq_score_testing
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {TestRun[]} test_runs
 * @property {number} total_count
 * @property {number} page
 * @property {number} page_size
 * @property {FilterOption[]} table_group_options
 * @property {FilterOption[]} test_suite_options
 * @property {Permissions} permissions
 * @property {object?} run_tests_dialog
 * @property {object?} schedule_dialog
 * @property {object?} notifications_dialog
 */
import van from '/app/static/js/van.min.js';
import { withTooltip } from '/app/static/js/components/tooltip.js';
import { SummaryBar } from '/app/static/js/components/summary_bar.js';
import { Link } from '/app/static/js/components/link.js';
import { Button } from '/app/static/js/components/button.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { formatTimestamp, formatDuration, DISABLED_ACTION_TEXT } from '/app/static/js/display_utils.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { Select } from '/app/static/js/components/select.js';
import { Paginator } from '/app/static/js/components/paginator.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '/app/static/js/components/empty_state.js';
import { Icon } from '/app/static/js/components/icon.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { RunTestsDialog } from '/app/static/js/components/run_tests_dialog.js';
import { ScheduleList } from '/app/static/js/components/schedule_list.js';
import { NotificationSettings } from '/app/static/js/components/notification_settings.js';
import { enterPage, exitPage } from '/app/static/js/page_lifecycle.js';
import { setIntervalWithSignal } from '/app/static/js/timers.js';

const { b, div, i, span, strong } = van.tags;
const SCROLL_CONTAINER = window.top.document.querySelector('.stMain');
const PAGE_KEY = 'testRuns';

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

const TestRuns = (/** @type Properties */ props) => {
    const { emit, signal } = props;
    loadStylesheet(PAGE_KEY, stylesheet);

    const columns = ['5%', '28%', '17%', '40%', '10%'];
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;

    const testRuns = van.derive(() => getValue(props.test_runs));
    let refreshIntervalId = null;
    let runTestsNode = null;
    const runTestsResult = van.state(null);

    let currentRefreshRate = null;
    van.derive(() => {
        const items = testRuns.val;
        const hasStarting = items.some(({ status }) => STARTING_STATUSES.has(status));
        const hasRunning = items.some(({ status }) => RUNNING_STATUSES.has(status));
        const rate = hasStarting ? REFRESH_STARTING : hasRunning ? REFRESH_RUNNING : REFRESH_DEFAULT;
        if (rate !== currentRefreshRate) {
            if (refreshIntervalId) clearInterval(refreshIntervalId);
            refreshIntervalId = setIntervalWithSignal(() => emit('RefreshData', {}), rate, signal);
            currentRefreshRate = rate;
        }
    });

    const selectedRuns = {};
    const initializeSelectedStates = (items) => {
        for (const testRun of items) {
            if (selectedRuns[testRun.job_execution_id] == undefined) {
                selectedRuns[testRun.job_execution_id] = van.state(false);
            }
        }
    };
    initializeSelectedStates(testRuns.val);
    van.derive(() => initializeSelectedStates(testRuns.val));

    const runsToDelete = van.state([]);
    const deleteConstraintChecked = van.state(false);

    const closeDeleteDialog = () => {
        runsToDelete.val = [];
        deleteConstraintChecked.val = false;
    };

    const scheduleDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.schedule_dialog)?.open === true) scheduleDialogOpen.val = true; });

    const notificationsDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.notifications_dialog)?.open === true) notificationsDialogOpen.val = true; });

    const wrapperId = 'test-runs-list-wrapper';

    return div(
        { id: wrapperId, 'data-testid': 'test-runs', class: 'tg-test-runs' },
        () => {
            const projectSummary = getValue(props.project_summary);
            return projectSummary.test_run_count > 0
            ? div(
                Toolbar(props, userCanEdit),
                () => testRuns.val.length
                ? div(
                    div(
                        { class: 'table pb-0' },
                        () => {
                            const selectedItems = testRuns.val.filter(i => selectedRuns[i.job_execution_id]?.val ?? false);
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
                                const items = testRuns.val;
                                const selectedItems = items.filter(i => selectedRuns[i.job_execution_id]?.val ?? false);
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
                                            onChange: (checked) => items.forEach(item => selectedRuns[item.job_execution_id].val = checked),
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
                            testRuns.val.map(item => TestRunItem(item, columns, selectedRuns[item.job_execution_id], userCanEdit, projectSummary.project_code, emit)),
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
                    'No test runs found matching filters',
                ),
            )
            : ConditionalEmptyState(projectSummary, userCanEdit, emit);
        },
        Dialog(
            { title: 'Delete Test Runs', open: van.derive(() => runsToDelete.val.length > 0), onClose: closeDeleteDialog },
            div(
                { class: 'flex-column fx-gap-4' },
                () => {
                    const runs = runsToDelete.val;
                    const hasRunning = runs.some(r => ACTIVE_STATUSES.has(r.status));
                    return div(
                        { class: 'flex-column fx-gap-3' },
                        div('Are you sure you want to delete ', b(runs.length), ` test run${runs.length !== 1 ? 's' : ''}?`),
                        hasRunning
                            ? div(
                                { class: 'flex-column fx-gap-2' },
                                div({ style: 'color: var(--orange);' }, 'Any running processes will be canceled.'),
                                Checkbox({
                                    label: runs.length === 1
                                        ? 'Yes, cancel and delete the test run'
                                        : 'Yes, cancel and delete the test runs',
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
            const info = getValue(props.run_tests_dialog);
            if (!info) { runTestsNode = null; runTestsResult.val = null; return div(); }
            runTestsResult.val = info.result ?? null;
            return (runTestsNode ??= RunTestsDialog({ emit,
                dialog: { title: info.title ?? 'Run Tests', open: true },
                project_code: info.project_code,
                test_suites: info.test_suites ?? [],
                default_test_suite_id: info.default_test_suite_id,
                result: runTestsResult,
                onClose: () => emit('RunTestsDialogClosed', {}),
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
        div(
            { class: 'flex-row fx-gap-3' },
            () => Select({
                label: 'Table Group',
                value: getValue(props.table_group_options)?.find((op) => op.selected)?.value ?? null,
                options: getValue(props.table_group_options) ?? [],
                allowNull: true,
                style: 'font-size: 14px;',
                testId: 'table-group-filter',
                onChange: (value) => emit('FilterApplied', { payload: { table_group_id: value } }),
            }),
            () => Select({
                label: 'Test Suite',
                value: getValue(props.test_suite_options)?.find((op) => op.selected)?.value ?? null,
                options: getValue(props.test_suite_options) ?? [],
                allowNull: true,
                style: 'font-size: 14px;',
                testId: 'test-suite-filter',
                onChange: (value) => emit('FilterApplied', { payload: { test_suite_id: value } }),
            }),
        ),
        div(
            { class: 'flex-row fx-gap-3' },
            Button({
                icon: 'notifications',
                type: 'stroked',
                label: 'Notifications',
                tooltip: 'Configure email notifications for test runs',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('RunNotificationsClicked', {}),
            }),
            Button({
                icon: 'today',
                type: 'stroked',
                label: 'Schedules',
                tooltip: 'Manage when test suites should run',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('RunSchedulesClicked', {}),
            }),
            userCanEdit
                ? Button({
                    icon: 'play_arrow',
                    type: 'stroked',
                    label: 'Run Tests',
                    width: 'fit-content',
                    style: 'background: var(--button-generic-background-color);',
                    onclick: () => emit('RunTestsClicked', {}),
                })
                : '',
            Button({
                type: 'stroked',
                icon: 'refresh',
                tooltip: 'Refresh test runs list',
                tooltipPosition: 'left',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('RefreshData', {}),
                testId: 'test-runs-refresh',
            }),
        ),
    );
};

const TestRunItem = (
    /** @type TestRun */ item,
    /** @type string[] */ columns,
    /** @type boolean */ selected,
    /** @type boolean */ userCanEdit,
    /** @type string */ projectCode,
    emit,
) => {
    const hasResults = !!item.test_ct;
    const runningStep = item.progress?.find((step) => step.status === 'Running');
    const displayTime = item.created_at;

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
            hasResults
                ? Link({ emit,
                    label: formatTimestamp(displayTime),
                    href: 'test-runs:results',
                    params: { 'run_id': item.job_execution_id, 'project_code': projectCode },
                    underline: true,
                })
                : span(formatTimestamp(displayTime)),
            div(
                { class: 'text-caption mt-1' },
                item.table_groups_name && item.test_suite
                    ? `${item.table_groups_name} > ${item.test_suite}`
                    : item.test_suite || '--',
            ),
        ),
        div(
            { style: `flex: ${columns[2]}` },
            div(
                { class: 'flex-row' },
                TestRunStatus(item),
                CANCELABLE_STATUSES.has(item.status) && userCanEdit ? Button({
                    type: 'stroked',
                    label: 'Cancel',
                    style: 'width: 64px; height: 28px; color: var(--purple); margin-left: 12px;',
                    onclick: () => {
                        emit('RunCanceled', { payload: { job_execution_id: item.job_execution_id, test_run_id: item.test_run_id } });
                    },
                }) : null,
            ),
            item.completed_at && item.started_at
                ? div(
                    { class: 'text-caption mt-1' },
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
            { class: 'pr-3', style: `flex: ${columns[3]}` },
            item.test_ct ? SummaryBar({
                items: [
                    { label: 'Passed', value: item.passed_ct, color: 'green' },
                    { label: 'Warning', value: item.warning_ct, color: 'yellow' },
                    { label: 'Failed', value: item.failed_ct, color: 'red' },
                    { label: 'Error', value: item.error_ct, color: 'brown' },
                    { label: 'Log', value: item.log_ct, color: 'blue' },
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
};

const TestRunStatus = (/** @type TestRun */ item) => {
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

const ProgressTooltip = (/** @type TestRun */ item) => {
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
                    span({ style: 'font-size: 12px; opacity: 0.6; margin-top: 2px; white-space: pre-wrap;' }, step.error),
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
        message: EMPTY_STATE_MESSAGE.testExecution,
        button: Button({
            icon: 'play_arrow',
            type: 'stroked',
            color: 'primary',
            label: 'Run Tests',
            width: 'fit-content',
            style: 'margin: auto; background: var(--button-generic-background-color);',
            disabled: !userCanEdit,
            tooltip: userCanEdit ? null : DISABLED_ACTION_TEXT,
            tooltipPosition: 'bottom',
            onclick: () => emit('RunTestsClicked', {}),
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
    } else if (projectSummary.test_suite_count <= 0 || projectSummary.test_definition_count <= 0) {
        args = {
            message: EMPTY_STATE_MESSAGE.testSuite,
            link: {
                label: 'Go to Test Suites',
                href: 'test-suites',
                params: { project_code: projectSummary.project_code },
            },
        };
    }

    return EmptyState({ emit,
        icon: 'labs',
        label: 'No test runs yet',
        ...args,
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-test-runs {
    min-height: 550px;
}
`);

export { TestRuns };

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
        componentState.signal = enterPage(PAGE_KEY);
        van.add(parentElement, TestRuns(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => {
        exitPage(PAGE_KEY);
        parentElement.state = null;
    };
};
