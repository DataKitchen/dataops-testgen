/**
 * @typedef ProjectSummary
 * @type {object}
 * @property {number} test_suites_ct
 * @property {number} connections_ct
 * @property {number} table_groups_ct
 * @property {string} default_connection_id
 *
 * @typedef TableGroupOption
 * @type {object}
 * @property {string} id
 * @property {string} name
 * @property {boolean} selected
 *
 * @typedef TestSuite
 * @type {object}
 * @property {string} id
 * @property {string} connection_name
 * @property {string} table_groups_name
 * @property {string} test_suite
 * @property {string} test_suite_description
 * @property {number} test_ct
 * @property {string} latest_run_start
 * @property {string} latest_run_id
 * @property {number} last_run_test_ct
 * @property {number} last_run_passed_ct
 * @property {number} last_run_warning_ct
 * @property {number} last_run_failed_ct
 * @property {number} last_run_error_ct
 * @property {number} last_run_dismissed_ct
 * @property {string} last_complete_profile_run_id
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {TestSuite} test_suites
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
        () =>
            getValue(props.project_summary).test_suites_ct > 0
            ? div(
                { class: 'tg-test-suites'},
                () => div(
                    { class: 'tg-test-suites--toolbar flex-row fx-align-flex-end mb-4' },
                    Select({
                        label: 'Table Group',
                        value: getValue(props.table_group_filter_options)?.find((op) => op.selected)?.value ?? null,
                        options: getValue(props.table_group_filter_options) ?? [],
                        allowNull: true,
                        height: 38,
                        style: 'font-size: 14px;',
                        onChange: (value) => emitEvent('FilterApplied', {payload: value}),
                    }),
                    userCanEdit
                        ? Button({
                            icon: 'add',
                            type: 'stroked',
                            label: 'Add Test Suite',
                            width: 'fit-content',
                            style: 'margin-left: auto; background: var(--dk-card-background);',
                            onclick: () => emitEvent('AddTestSuiteClicked', {}),
                        })
                        : '',
                ),
                () => div(
                    { class: 'flex-column' },
                    getValue(testSuites).map((/** @type TestSuite */ testSuite) => Card({
                        border: true,
                        title: () => div(
                            { class: 'flex-column tg-test-suites--card-title' },
                            h4(testSuite.test_suite),
                            small(`${testSuite.connection_name} > ${testSuite.table_groups_name}`),
                        ),
                        actionContent: () => div(
                            { class: 'flex-row' },
                            userCanEdit
                                ? [
                                    Button({ type: 'icon', icon: 'output', tooltip: 'Export results to Observability', onclick: () => emitEvent('ExportActionClicked', {payload: testSuite.id}) }),
                                    Button({ type: 'icon', icon: 'edit', tooltip: 'Edit test suite', onclick: () => emitEvent('EditActionClicked', {payload: testSuite.id}) }),
                                    Button({ type: 'icon', icon: 'delete', tooltip: 'Delete test suite', tooltipPosition: 'left', onclick: () => emitEvent('DeleteActionClicked', {payload: testSuite.id}) }),
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
                                    label: `${testSuite.test_ct ?? 0} test definitions`,
                                    right_icon: 'chevron_right',
                                    right_icon_size: 20,
                                    class: 'mb-4',
                                }),
                                Caption({ content: 'Description', style: 'margin-bottom: 2px;' }),
                                span(testSuite.test_suite_description ?? '--'),
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
                                        label: 'Generate Tests',
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
                ),
            )
            : ConditionalEmptyState(getValue(props.project_summary), userCanEdit),
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
            style: 'margin: auto; background: white;',
            disabled: !userCanEdit,
            tooltip: userCanEdit ? null : DISABLED_ACTION_TEXT,
            tooltipPosition: 'bottom',
            onclick: () => emitEvent('AddTestSuiteClicked', {}),
        }),
    };

    if (projectSummary.connections_ct <= 0) {
        args = {
            message: EMPTY_STATE_MESSAGE.connection,
            link: {
                label: 'Go to Connections',
                href: 'connections',
            },
        };
    } else if (projectSummary.table_groups_ct <= 0) {
        args = {
            message: EMPTY_STATE_MESSAGE.tableGroup,
            link: {
                label: 'Go to Table Groups',
                href: 'connections:table-groups',
                params: { connection_id: projectSummary.default_connection_id },
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
