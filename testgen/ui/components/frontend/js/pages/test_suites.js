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
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { formatTimestamp, DISABLED_ACTION_TEXT } from '../display_utils.js';
import { Input } from '../components/input.js';
import { Select } from '../components/select.js';
import { Button } from '../components/button.js';
import { Card } from '../components/card.js';
import { Link } from '../components/link.js';
import { Caption } from '../components/caption.js';
import { SummaryBar } from '../components/summary_bar.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '../components/empty_state.js';

const { div, h4, small, span, i } = van.tags;

const mat = (name, size = 16) =>
    span({ class: 'material', style: `font-size:${size}px` }, name);

const TestSuites = (/** @type Properties */ props) => {
    loadStylesheet('testsuites', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const userCanEdit = getValue(props.permissions).can_edit;
    const testSuites = van.derive(() => getValue(props.test_suites));
    const wrapperId = 'test-suites-list-wrapper';

    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return div(
        { id: wrapperId, style: 'overflow-y: auto;' },
        () => {
            const projectSummary = getValue(props.project_summary);
            return projectSummary.test_suite_count > 0
            ? div(
                { class: 'tg-test-suites'},
                () => {
                    const initialTableGroup = getValue(props.table_group_filter_options)?.find((op) => op.selected)?.value ?? null;
                    const initialTestSuiteName = getValue(props.test_suite_name) || null;
                    const selectedTableGroup = van.state(initialTableGroup);
                    const testSuiteNameFilter = van.state(initialTestSuiteName);

                    van.derive(() => {
                        if (selectedTableGroup.val !== initialTableGroup || testSuiteNameFilter.val !== initialTestSuiteName) {
                            emitEvent('FilterApplied', { payload: { table_group_id: selectedTableGroup.val, test_suite_name: testSuiteNameFilter.val } });
                        }
                    });

                    return div(
                        { class: 'flex-row fx-align-flex-end fx-justify-space-between fx-gap-4 fx-flex-wrap mb-4' },
                        div(
                            { class: 'flex-row fx-align-flex-end fx-gap-3' },
                            Select({
                                label: 'Table Group',
                                value: selectedTableGroup,
                                options: getValue(props.table_group_filter_options) ?? [],
                                allowNull: true,
                                style: 'font-size: 14px;',
                                testId: 'table-group-filter',
                                onChange: (value) => selectedTableGroup.val = value,
                            }),
                            Input({
                                testId: 'test-suite-name-filter',
                                icon: 'search',
                                label: '',
                                placeholder: 'Search test suite names',
                                width: 300,
                                clearable: true,
                                value: testSuiteNameFilter,
                                onChange: (value) => testSuiteNameFilter.val = value || null,
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
                                onclick: () => emitEvent('RunNotificationsClicked', {}),
                            }),
                            Button({
                                icon: 'today',
                                type: 'stroked',
                                label: 'Schedules',
                                tooltip: 'Manage when test suites should run',
                                tooltipPosition: 'bottom',
                                width: 'fit-content',
                                style: 'background: var(--button-generic-background-color);',
                                onclick: () => emitEvent('RunSchedulesClicked', {}),
                            }),
                            userCanEdit
                                ? Button({
                                    icon: 'add',
                                    type: 'stroked',
                                    label: 'Add Test Suite',
                                    width: 'fit-content',
                                    style: 'background: var(--button-generic-background-color);',
                                    onclick: () => emitEvent('AddTestSuiteClicked', {}),
                                })
                                : '',
                        ),
                    );
                },
                () => getValue(testSuites)?.length
                ? div(
                    { class: 'flex-column' },
                    getValue(testSuites).map((/** @type TestSuiteSummary */ testSuite) => Card({
                        border: true,
                        testId: 'test-suite-card',
                        title: () => div(
                            { class: 'flex-column tg-test-suites--card-title', 'data-testid': 'test-suite-title' },
                            div(
                                { class: 'flex-row fx-align-center', style: 'gap: 8px;' },
                                h4(testSuite.test_suite),
                                testSuite.is_contract_snapshot
                                    ? span({ class: 'contract-snapshot-badge' }, mat('lock', 13), ' Contract snapshot')
                                    : !testSuite.include_in_contract
                                    ? span({ class: 'excluded-contract-chip' }, mat('remove_circle_outline', 13), ' Excluded from contract')
                                    : '',
                            ),
                            small(`${testSuite.connection_name} > ${testSuite.table_groups_name}`),
                        ),
                        actionContent: () => div(
                            { class: 'flex-row fx-align-center', style: 'gap: 4px;' },
                            userCanEdit && !testSuite.is_contract_snapshot
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
                                        onclick: () => emitEvent('ExportActionClicked', {payload: testSuite.id}),
                                    }),
                                    Button({
                                        type: 'icon',
                                        icon: 'edit',
                                        tooltip: 'Edit test suite',
                                        onclick: () => emitEvent('EditActionClicked', {payload: testSuite.id}),
                                    }),
                                    Button({
                                        type: 'icon',
                                        icon: 'delete',
                                        tooltip: 'Delete test suite',
                                        tooltipPosition: 'left',
                                        onclick: () => emitEvent('DeleteActionClicked', {payload: testSuite.id}),
                                    }),
                                ]
                                : ''
                        ),
                        content: () => div(
                            { class: 'flex-row fx-justify-space-between fx-flex-align-content' },
                            div(
                                { class: 'flex-column' },
                                Link({
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
                                        Link({
                                            href: 'test-runs:results',
                                            params: { run_id: testSuite.latest_run_id, project_code: projectSummary.project_code },
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
                                testSuite.is_contract_snapshot
                                ? [
                                    userCanEdit ? Button({
                                        label: 'Run Tests',
                                        color: 'primary',
                                        type: 'stroked',
                                        style: 'min-width: 180px;',
                                        disabled: !parseInt(testSuite.test_ct),
                                        onclick: () => emitEvent('RunTestsClicked', {payload: testSuite.id}),
                                    }) : '',
                                    testSuite.has_contract ? Button({
                                        label: 'View Data Contract',
                                        color: 'primary',
                                        type: 'stroked',
                                        style: 'margin-top: 16px; min-width: 180px;',
                                        onclick: () => emitEvent('LinkClicked', {
                                            href: 'data-contract',
                                            params: {
                                                table_group_id: testSuite.table_groups_id,
                                                ...(testSuite.contract_version != null ? { version: testSuite.contract_version } : {}),
                                            },
                                        }),
                                    }) : '',
                                ]
                                : userCanEdit
                                ? [
                                    Button({
                                        label: 'Run Tests',
                                        color: 'primary',
                                        type: 'stroked',
                                        style: 'min-width: 180px;',
                                        disabled: !parseInt(testSuite.test_ct),
                                        onclick: () => emitEvent('RunTestsClicked', {payload: testSuite.id}),
                                    }),
                                    Button({
                                        label: parseInt(testSuite.test_ct) ? 'Regenerate Tests' : 'Generate Tests',
                                        color: 'primary',
                                        type: 'stroked',
                                        style: 'margin-top: 16px; min-width: 180px;',
                                        disabled: !testSuite.last_complete_profile_run_id,
                                        onclick: () => emitEvent('GenerateTestsClicked', {payload: testSuite.id}),
                                    }),
                                    testSuite.include_in_contract && testSuite.has_contract ? Button({
                                        label: 'View Data Contract',
                                        color: 'primary',
                                        type: 'stroked',
                                        style: 'margin-top: 16px; min-width: 180px;',
                                        onclick: () => emitEvent('LinkClicked', {
                                            href: 'data-contract',
                                            params: { table_group_id: testSuite.table_groups_id },
                                        }),
                                    }) : '',
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
            : ConditionalEmptyState(projectSummary, userCanEdit);
        },
    );
};

const ConditionalEmptyState = (
    /** @type ProjectSummary */ projectSummary,
    /** @type boolean */ userCanEdit,
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
            onclick: () => emitEvent('AddTestSuiteClicked', {}),
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

.contract-snapshot-badge {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    border-radius: 12px;
    background: #e0e7ff;
    color: #4338ca;
    font-size: 0.75rem;
    font-weight: 500;
    white-space: nowrap;
    text-transform: initial;
}

.contract-snapshot-badge .material {
    color: #4338ca;
}

.in-contract-chip {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    border-radius: 12px;
    border: 1px solid #6ee7b7;
    background: #f0fdf4;
    color: #065f46;
    font-size: 0.75rem;
    font-weight: 500;
    white-space: nowrap;
    text-transform: initial;
}

.in-contract-chip .material {
    color: #059669;
}

.excluded-contract-chip {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    border-radius: 12px;
    border: 1px solid #fca5a5;
    background: #fef2f2;
    color: #991b1b;
    font-size: 0.75rem;
    font-weight: 500;
    white-space: nowrap;
    text-transform: initial;
}

.excluded-contract-chip .material {
    color: #dc2626;
}

.snapshot-suite-info-note {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.8125rem;
    color: var(--caption-text-color);
    font-style: italic;
    margin-bottom: 16px;
}

.snapshot-suite-info-note .material {
    color: #6366f1;
    flex-shrink: 0;
}
`);

export { TestSuites };
