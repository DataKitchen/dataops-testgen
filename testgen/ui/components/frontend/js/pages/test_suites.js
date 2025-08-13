/**
 * @import { ProjectSummary } from '../types.js';
 * @import { TestSuiteSummary } from '../types.js';
 *
 * @typedef TableGroupOption
 * @type {object}
 * @property {string} id
 * @property {string} name
 * @property {boolean} selected
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {TestSuiteSummary} test_suites
 * @property {TableGroupOption[]} table_group_filter_options
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { formatTimestamp, DISABLED_ACTION_TEXT } from '../display_utils.js';
import { Select } from '../components/select.js';
import { Button } from '../components/button.js';
import { Card } from '../components/card.js';
import { Link } from '../components/link.js';
import { Caption } from '../components/caption.js';
import { SummaryBar } from '../components/summary_bar.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '../components/empty_state.js';

const { div, h4, small, span, i } = van.tags;

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
                () => div(
                    { class: 'flex-row fx-align-flex-end fx-justify-space-between mb-4' },
                    Select({
                        label: 'Table Group',
                        value: getValue(props.table_group_filter_options)?.find((op) => op.selected)?.value ?? null,
                        options: getValue(props.table_group_filter_options) ?? [],
                        allowNull: true,
                        height: 38,
                        style: 'font-size: 14px;',
                        testId: 'table-group-filter',
                        onChange: (value) => emitEvent('FilterApplied', {payload: value}),
                    }),
                    div(
                        { class: 'flex-row fx-gap-4' },
                        Button({
                            icon: 'today',
                            type: 'stroked',
                            label: 'Test Run Schedules',
                            tooltip: 'Manage when test suites should run',
                            tooltipPosition: 'bottom',
                            width: 'fit-content',
                            style: 'background: var(--dk-card-background);',
                            onclick: () => emitEvent('RunSchedulesClicked', {}),
                        }),
                        userCanEdit
                            ? Button({
                                icon: 'add',
                                type: 'stroked',
                                label: 'Add Test Suite',
                                width: 'fit-content',
                                style: 'background: var(--dk-card-background);',
                                onclick: () => emitEvent('AddTestSuiteClicked', {}),
                            })
                            : '',
                    ),
                ),
                () => getValue(testSuites)?.length
                ? div(
                    { class: 'flex-column' },
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
                                    params: { test_suite_id: testSuite.id },
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
                                        params: { run_id: testSuite.latest_run_id },
                                        label: formatTimestamp(testSuite.latest_run_start),
                                        class: 'mb-4',
                                    }),
                                    SummaryBar({
                                        items: [
                                            { label: 'Passed', value: parseInt(testSuite.last_run_passed_ct), color: 'green' },
                                            { label: 'Warning', value: parseInt(testSuite.last_run_warning_ct), color: 'yellow' },
                                            { label: 'Failed', value: parseInt(testSuite.last_run_failed_ct), color: 'red' },
                                            { label: 'Error', value: parseInt(testSuite.last_run_error_ct), color: 'brown' },
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
            style: 'margin: auto; background: var(--dk-card-background);',
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
    min-height: 400px;
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
`);

export { TestSuites };
