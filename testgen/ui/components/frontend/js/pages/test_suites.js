/**
 * @import { FilterOption, ProjectSummary } from '../types.js';
 * @import { TestSuiteSummary } from '../types.js';
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {TestSuiteSummary} test_suites
 * @property {FilterOption[]} table_group_filter_options
 * @property {string?} test_suite_name
 * @property {Permissions} permissions
 * @property {object?} run_tests_dialog
 * @property {object?} generate_tests_dialog
 * @property {object?} schedule_dialog
 * @property {object?} notifications_dialog
 */
import van from '/app/static/js/van.min.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { formatTimestamp, DISABLED_ACTION_TEXT } from '/app/static/js/display_utils.js';
import { Select } from '/app/static/js/components/select.js';
import { Button } from '/app/static/js/components/button.js';
import { Card } from '/app/static/js/components/card.js';
import { Link } from '/app/static/js/components/link.js';
import { Caption } from '/app/static/js/components/caption.js';
import { SummaryBar } from '/app/static/js/components/summary_bar.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '/app/static/js/components/empty_state.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { RunTestsDialog } from '/app/static/js/components/run_tests_dialog.js';
import { GenerateTestsDialog } from '/app/static/js/components/generate_tests_dialog.js';
import { ScheduleList } from '/app/static/js/components/schedule_list.js';
import { NotificationSettings } from '/app/static/js/components/notification_settings.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Toggle } from '/app/static/js/components/toggle.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { Input } from '/app/static/js/components/input.js';
import { ExpanderToggle } from '/app/static/js/components/expander_toggle.js';
import { required } from '/app/static/js/form_validators.js';

const { b, div, h4, pre, small, span, i } = van.tags;

const TestSuites = (/** @type Properties */ props) => {
    const { emit } = props;
    loadStylesheet('testsuites', stylesheet);

    const userCanEdit = getValue(props.permissions).can_edit;
    const testSuites = van.derive(() => getValue(props.test_suites));
    const wrapperId = 'test-suites-list-wrapper';

    // Delete dialog state (driven by Python prop)
    const deleteDialogInfo = van.derive(() => getValue(props.delete_dialog) ?? null);
    const deleteDialogOpen = van.state(false);
    const confirmCascadeDelete = van.state(false);
    van.derive(() => { if (deleteDialogInfo.val?.open) deleteDialogOpen.val = true; });
    const closeDeleteDialog = () => {
        deleteDialogOpen.val = false;
        confirmCascadeDelete.val = false;
        emit('DeleteDialogDismissed', {});
    };

    // Observability export dialog state (pure JS, no Python round-trip needed)
    const exportDialogOpen = van.state(false);
    const exportTestSuite = van.state(null);
    let runTestsNode = null;
    const runTestsResult = van.state(null);

    // Add/Edit test suite form dialog state (driven by Python prop)
    const formDialogInfo = van.derive(() => getValue(props.form_dialog) ?? null);
    const formDialogOpen = van.state(false);
    van.derive(() => { if (formDialogInfo.val?.open) formDialogOpen.val = true; });

    const formState = {
        testSuiteName: van.state(''),
        tableGroupId: van.state(null),
        description: van.state(''),
        severity: van.state(null),
        exportToObservability: van.state(false),
        dqScoreExclude: van.state(false),
        componentKey: van.state(''),
        componentType: van.state('dataset'),
        componentName: van.state(''),
    };

    const formValidity = {
        testSuiteName: van.state(false),
        tableGroupId: van.state(false),
    };
    const saveDisabled = van.derive(() => !formValidity.testSuiteName.val || !formValidity.tableGroupId.val);

    van.derive(() => {
        const info = formDialogInfo.val;
        if (!info?.open) return;
        const v = info.initial_values ?? {};
        formState.testSuiteName.val = v.test_suite ?? '';
        formState.tableGroupId.val = v.table_groups_id ?? null;
        formState.description.val = v.test_suite_description ?? '';
        formState.severity.val = v.severity ?? null;
        formState.exportToObservability.val = v.export_to_observability ?? false;
        formState.dqScoreExclude.val = v.dq_score_exclude ?? false;
        formState.componentKey.val = v.component_key ?? '';
        formState.componentType.val = v.component_type ?? 'dataset';
        formState.componentName.val = v.component_name ?? '';
        formValidity.testSuiteName.val = !!v.test_suite;
        formValidity.tableGroupId.val = !!v.table_groups_id;
    });

    const closeFormDialog = () => {
        formDialogOpen.val = false;
        emit('FormDialogClosed', {});
    };

    const scheduleDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.schedule_dialog)?.open === true) scheduleDialogOpen.val = true; });

    const notificationsDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.notifications_dialog)?.open === true) notificationsDialogOpen.val = true; });

    return div(
        { id: wrapperId, 'data-testid': 'test-suites', style: 'overflow-y: auto;' },
        () => {
            const projectSummary = getValue(props.project_summary);
            return projectSummary.test_suite_count > 0
            ? div(
                { class: 'tg-test-suites'},
                div(
                    { class: 'flex-row fx-align-flex-end fx-justify-space-between fx-gap-4 fx-flex-wrap mb-4' },
                    div(
                        { class: 'flex-row fx-align-flex-end fx-gap-3' },
                        () => Select({
                            label: 'Table Group',
                            value: getValue(props.table_group_filter_options)?.find((op) => op.selected)?.value ?? null,
                            options: getValue(props.table_group_filter_options) ?? [],
                            allowNull: true,
                            style: 'font-size: 14px;',
                            testId: 'table-group-filter',
                            onChange: (value) => {
                                console.log(value)
                                emit('FilterApplied', { payload: { table_group_id: value } })
                            },
                        }),
                        () => Input({
                            testId: 'test-suite-name-filter',
                            icon: 'search',
                            label: '',
                            placeholder: 'Search test suite names',
                            width: 300,
                            clearable: true,
                            value: getValue(props.test_suite_name) || null,
                            onChange: (value) => emit('FilterApplied', { payload: { test_suite_name: value || null } }),
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
                                icon: 'add',
                                type: 'stroked',
                                label: 'Add Test Suite',
                                width: 'fit-content',
                                style: 'background: var(--button-generic-background-color);',
                                onclick: () => emit('AddTestSuiteClicked', {}),
                            })
                            : '',
                    ),
                ),
                () => getValue(testSuites)?.length
                ? div(
                    { class: 'flex-column fx-gap-4' },
                    getValue(testSuites).map((/** @type TestSuiteSummary */ testSuite) => Card({
                        border: true,
                        testId: 'test-suite-card',
                        title: () => div(
                            { class: 'flex-column tg-test-suites--card-title', 'data-testid': 'test-suite-title' },
                            h4(testSuite.test_suite),
                            small(`${testSuite.connection_name} > ${testSuite.table_groups_name}`),
                        ),
                        actionContent: () => div(
                            { class: 'flex-row' },
                            userCanEdit
                                ? [
                                    Button({
                                        type: 'icon',
                                        icon: 'output',
                                        tooltip: !projectSummary.can_export_to_observability
                                            ? 'Observability export not configured in Project Settings'
                                            : !testSuite.export_to_observability
                                            ? 'Observability export not configured for test suite'
                                            : 'Export results to Observability',
                                        tooltipPosition: 'left',
                                        disabled: !projectSummary.can_export_to_observability || !testSuite.export_to_observability,
                                        onclick: () => {
                                            exportTestSuite.val = { ...testSuite, project_code: projectSummary.project_code };
                                            exportDialogOpen.val = true;
                                        },
                                    }),
                                    Button({
                                        type: 'icon',
                                        icon: 'edit',
                                        tooltip: 'Edit test suite',
                                        onclick: () => emit('EditActionClicked', {payload: testSuite.id}),
                                    }),
                                    Button({
                                        type: 'icon',
                                        icon: 'delete',
                                        tooltip: 'Delete test suite',
                                        tooltipPosition: 'left',
                                        onclick: () => emit('DeleteActionClicked', {payload: testSuite.id}),
                                    }),
                                ]
                                : ''
                        ),
                        content: () => div(
                            { class: 'flex-row fx-justify-space-between fx-flex-align-content' },
                            div(
                                { class: 'flex-column' },
                                Link({ emit, 
                                    href: 'test-suites:definitions',
                                    params: { test_suite_id: testSuite.id, project_code: projectSummary.project_code },
                                    label: `View ${testSuite.test_ct ?? 0} test definitions`,
                                    right_icon: 'chevron_right',
                                    right_icon_size: 20,
                                    class: 'mb-4',
                                }),
                                Caption({ content: 'Description', style: 'margin-bottom: 2px;' }),
                                span({'data-testid': 'test-suite-description'}, testSuite.test_suite_description ?? '--'),
                            ),
                            div(
                                { class: 'flex-column' },
                                Caption({ content: 'Latest Run', style: 'margin-bottom: 2px;' }),
                                testSuite.latest_run_start
                                    ? [
                                        Link({ emit,
                                            href: 'test-runs:results',
                                            params: { run_id: testSuite.latest_run_job_execution_id, project_code: projectSummary.project_code },
                                            label: formatTimestamp(testSuite.latest_run_start),
                                            class: 'mb-4',
                                        }),
                                        SummaryBar({
                                            items: [
                                                { label: 'Passed', value: parseInt(testSuite.last_run_passed_ct), color: 'green' },
                                                { label: 'Warning', value: parseInt(testSuite.last_run_warning_ct), color: 'yellow' },
                                                { label: 'Failed', value: parseInt(testSuite.last_run_failed_ct), color: 'red' },
                                                { label: 'Error', value: parseInt(testSuite.last_run_error_ct), color: 'brown' },
                                                { label: 'Log', value: parseInt(testSuite.last_run_log_ct), color: 'blue' },
                                                { label: 'Dismissed', value: parseInt(testSuite.last_run_dismissed_ct), color: 'grey' },
                                            ],
                                            height: 20,
                                            width: 350,
                                        })
                                    ]
                                    : span('--'),
                            ),
                            div(
                                { class: 'flex-column' },
                                userCanEdit
                                ? [
                                    Button({
                                        label: 'Run Tests',
                                        color: 'primary',
                                        type: 'stroked',
                                        style: 'min-width: 180px;',
                                        disabled: !parseInt(testSuite.test_ct),
                                        onclick: () => emit('RunTestsClicked', {payload: testSuite.id}),
                                    }),
                                    Button({
                                        label: parseInt(testSuite.test_ct) ? 'Regenerate Tests' : 'Generate Tests',
                                        color: 'primary',
                                        type: 'stroked',
                                        style: 'margin-top: 16px; min-width: 180px;',
                                        disabled: !testSuite.last_complete_profile_run_id,
                                        onclick: () => emit('GenerateTestsClicked', {payload: testSuite.id}),
                                    }),
                                ]
                                : ''
                            ),
                        ),
                    })),
                )
                : div(
                    { class: 'mt-7 text-secondary', style: 'text-align: center;' },
                    'No test suites found matching filters',
                ),
            )
            : ConditionalEmptyState(projectSummary, userCanEdit, emit);
        },
        // Delete test suite dialog (driven by Python prop for is_in_use data)
        () => {
            const info = deleteDialogInfo.val;
            if (!info) return div();
            const isInUse = info.is_in_use;
            const deleteDisabled = van.derive(() => isInUse && !confirmCascadeDelete.val);
            return Dialog(
                { title: 'Delete Test Suite', open: deleteDialogOpen, onClose: closeDeleteDialog, width: '36rem' },
                div(
                    { class: 'flex-column fx-gap-4' },
                    div('Are you sure you want to delete the test suite ', b(info.test_suite_name), '?'),
                    isInUse
                        ? div(
                            { class: 'flex-column fx-gap-4' },
                            Alert(
                                { type: 'warn' },
                                div('This Test Suite has related data, which may include test definitions and test results.'),
                                div({ class: 'mt-2' }, 'If you proceed, all related data will be permanently deleted.'),
                            ),
                            Toggle({
                                name: 'confirm-cascade-delete',
                                label: span('Yes, delete the test suite ', b(info.test_suite_name), ' and related TestGen data.'),
                                checked: confirmCascadeDelete,
                                onChange: (value) => confirmCascadeDelete.val = value,
                            }),
                        )
                        : '',
                    div(
                        { class: 'flex-row fx-justify-content-flex-end' },
                        () => Button({
                            type: deleteDisabled.val ? 'stroked' : 'flat',
                            color: deleteDisabled.val ? 'basic' : 'warn',
                            label: 'Delete',
                            width: 'auto',
                            style: 'margin-left: auto;',
                            disabled: deleteDisabled,
                            onclick: () => {
                                emit('DeleteTestSuiteConfirmed', { payload: info.test_suite_id });
                                closeDeleteDialog();
                            },
                        }),
                    ),
                ),
            );
        },
        // Add/Edit test suite form dialog (driven by Python prop)
        () => {
            const info = formDialogInfo.val;
            if (!info) return div();
            const isEdit = info.mode === 'edit';
            const tableGroups = info.table_groups ?? [];
            const severityOptions = [
                { value: null, label: 'Inherit' },
                { value: 'Log', label: 'Log' },
                { value: 'Failed', label: 'Failed' },
                { value: 'Warning', label: 'Warning' },
            ];
            const formResult = info.result;
            const showObservabilitySection = van.state(false);
            return Dialog(
                {
                    title: info.title ?? (isEdit ? 'Edit Test Suite' : 'Add Test Suite'),
                    open: formDialogOpen,
                    onClose: closeFormDialog,
                    width: '52rem',
                },
                div(
                    { class: 'flex-column fx-gap-3' },
                    div(
                        { class: 'flex-row fx-gap-3' },
                        Input({
                            label: 'Test Suite Name',
                            value: formState.testSuiteName,
                            disabled: isEdit,
                            style: 'flex: 1;',
                            validators: [required],
                            onChange: (value, validity) => {
                                formState.testSuiteName.val = value;
                                formValidity.testSuiteName.val = validity.valid;
                            },
                        }),
                        Select({
                            label: 'Table Group',
                            value: formState.tableGroupId,
                            options: tableGroups,
                            allowNull: false,
                            required: true,
                            disabled: isEdit,
                            style: 'flex: 1;',
                            onChange: (value) => {
                                formState.tableGroupId.val = value;
                                formValidity.tableGroupId.val = !!value;
                            },
                            portalClass: 'ts-form--select',
                        }),
                    ),
                    div(
                        { class: 'flex-row fx-gap-3' },
                        Input({
                            label: 'Test Suite Description',
                            value: formState.description,
                            style: 'flex: 1;',
                            onChange: (value) => { formState.description.val = value; },
                        }),
                        Select({
                            label: 'Severity',
                            value: formState.severity,
                            options: severityOptions,
                            allowNull: false,
                            style: 'flex: 1;',
                            onChange: (value) => { formState.severity.val = value; },
                            portalClass: 'ts-form--select',
                        }),
                    ),
                    div(
                        { class: 'flex-row fx-gap-4' },
                        Checkbox({
                            name: 'export-to-observability',
                            label: 'Export to Observability',
                            checked: formState.exportToObservability,
                            onChange: (value) => { formState.exportToObservability.val = value; },
                        }),
                        Checkbox({
                            name: 'dq-score-exclude',
                            label: 'Exclude from quality scoring',
                            checked: formState.dqScoreExclude,
                            onChange: (value) => { formState.dqScoreExclude.val = value; },
                        }),
                    ),
                    ExpanderToggle({
                        expandLabel: 'Observability overrides',
                        collapseLabel: 'Observability overrides',
                        labelPosition: 'left',
                        onExpand: () => { showObservabilitySection.val = true; },
                        onCollapse: () => { showObservabilitySection.val = false; },
                    }),
                    () => showObservabilitySection.val
                        ? div(
                            { class: 'flex-row fx-gap-3' },
                            Input({
                                label: 'Component Key',
                                value: formState.componentKey,
                                placeholder: 'Optional',
                                style: 'flex: 1;',
                                onChange: (value) => { formState.componentKey.val = value; },
                            }),
                            Input({
                                label: 'Component Type',
                                value: formState.componentType,
                                disabled: true,
                                style: 'flex: 1;',
                            }),
                            Input({
                                label: 'Component Name',
                                value: formState.componentName,
                                placeholder: 'Optional',
                                style: 'flex: 1;',
                                onChange: (value) => { formState.componentName.val = value; },
                            }),
                        )
                        : '',
                    formResult
                        ? Alert({ type: formResult.success ? 'success' : 'error' }, formResult.message)
                        : '',
                    div(
                        { class: 'flex-row fx-justify-content-flex-end' },
                        Button({
                            type: 'flat',
                            color: 'primary',
                            label: isEdit ? 'Save' : 'Add',
                            width: 'auto',
                            style: 'width: auto;',
                            disabled: saveDisabled,
                            onclick: () => emit('SaveTestSuiteForm', {
                                payload: {
                                    mode: info.mode,
                                    test_suite_id: info.test_suite_id ?? null,
                                    test_suite: formState.testSuiteName.val,
                                    table_groups_id: formState.tableGroupId.val,
                                    test_suite_description: formState.description.val,
                                    severity: formState.severity.val,
                                    export_to_observability: formState.exportToObservability.val,
                                    dq_score_exclude: formState.dqScoreExclude.val,
                                    component_key: formState.componentKey.val,
                                    component_type: formState.componentType.val,
                                    component_name: formState.componentName.val,
                                },
                            }),
                        }),
                    ),
                ),
            );
        },
        // Observability export dialog (pure JS — no Python round-trip for open)
        () => {
            const ts = exportTestSuite.val;
            if (!ts) return div();
            return Dialog(
                {
                    title: 'Export to Observability',
                    open: exportDialogOpen,
                    onClose: () => { exportDialogOpen.val = false; },
                    width: '36rem',
                },
                div(
                    { class: 'flex-column fx-gap-4' },
                    div('Execute the test export for test suite ', b(ts.test_suite), '?'),
                    div(
                        { class: 'flex-column fx-gap-2' },
                        Caption({ content: 'CLI command' }),
                        pre(
                            { style: 'background: var(--secondary-background-color); padding: 8px; border-radius: 4px; font-size: 0.75rem; overflow-x: auto; white-space: pre-wrap; word-break: break-all;' },
                            `testgen export-observability --project-key ${ts.project_code} --test-suite-key '${ts.test_suite}'`,
                        ),
                    ),
                    div(
                        { class: 'flex-row fx-justify-content-flex-end' },
                        Button({
                            type: 'flat',
                            color: 'primary',
                            label: 'Start',
                            style: 'width: auto;',
                            onclick: () => {
                                emit('ExportActionClicked', { payload: ts.id });
                                exportDialogOpen.val = false;
                            },
                        }),
                    ),
                ),
            );
        },
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
        // Cache the dialog element so Streamlit reruns don't recreate it
        // and reset user selections (e.g. generation set dropdown).
        (() => {
            let _dialog = null;
            let _dialogId = null;
            const _dialogProps = {
                refresh_warning: van.state(null),
                lock_result: van.state(null),
                result: van.state(null),
            };
            return () => {
                const info = getValue(props.generate_tests_dialog);
                if (!info) { _dialog = null; _dialogId = null; return div(); }

                // Rebuild only when the dialog is for a different test suite
                if (!_dialog || _dialogId !== info.test_suite_id) {
                    _dialogId = info.test_suite_id;
                    _dialogProps.refresh_warning.val = info.refresh_warning;
                    _dialogProps.lock_result.val = info.lock_result;
                    _dialogProps.result.val = info.result;
                    _dialog = GenerateTestsDialog({ emit,
                        dialog: { title: info.title ?? 'Generate Tests', open: true },
                        test_suite_id: info.test_suite_id,
                        test_suite_name: info.test_suite_name,
                        generation_sets: info.generation_sets ?? [],
                        default_generation_set: info.default_generation_set,
                        refresh_warning: _dialogProps.refresh_warning,
                        lock_result: _dialogProps.lock_result,
                        result: _dialogProps.result,
                        onClose: () => emit('GenerateTestsDialogClosed', {}),
                    });
                } else {
                    // Update dynamic props without recreating the dialog
                    _dialogProps.refresh_warning.val = info.refresh_warning;
                    _dialogProps.lock_result.val = info.lock_result;
                    _dialogProps.result.val = info.result;
                }

                return _dialog;
            };
        })(),
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

const ConditionalEmptyState = (
    /** @type ProjectSummary */ projectSummary,
    /** @type boolean */ userCanEdit,
    emit,
) => {
    let args = {
        message: EMPTY_STATE_MESSAGE.testSuite,
        button: Button({
            icon: 'add',
            type: 'stroked',
            color: 'primary',
            label: 'Add Test Suite',
            width: 'fit-content',
            style: 'margin: auto; background: var(--button-generic-background-color);',
            disabled: !userCanEdit,
            tooltip: userCanEdit ? null : DISABLED_ACTION_TEXT,
            tooltipPosition: 'bottom',
            onclick: () => emit('AddTestSuiteClicked', {}),
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
        icon: 'rule',
        label: 'No test suites yet',
        ...args,
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-test-suites {
    width: 100%;
    min-height: 500px;
}

.tg-test-suites--card-title h4 {
    margin: 0;
    color: var(--primary-text-color);
    font-size: 1.5rem;
    text-transform: initial;
}

.ts-form--select {
    max-height: 220px !important;
}

.tg-test-suites--card-title small {
    margin: 0;
    margin-top: 4px;
    line-height: 15px;
    font-style: italic;
    font-size: .875rem;
    font-weight: 400;
    color: var(--caption-text-color);
    text-transform: initial;
}
`);

export { TestSuites };

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
        van.add(parentElement, TestSuites(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
