/**
 * @typedef ProjectSummary
 * @type {object}
 * @property {number} table_groups_count
 * @property {number} test_suites_count
 * @property {number} test_definitions_count
 * @property {number} test_runs_count
 * @property {number} profiling_runs_count
 * @property {number} connections_count
 * @property {string} default_connection_id
 * 
 * @typedef TestSuiteSummary
 * @type {object}
 * @property {string} id
 * @property {string} test_suite
 * @property {number} test_ct
 * @property {string} latest_auto_gen_date
 * @property {string} latest_run_start
 * @property {string} latest_run_id
 * @property {number} last_run_test_ct
 * @property {number} last_run_passed_ct
 * @property {number} last_run_warning_ct
 * @property {number} last_run_failed_ct
 * @property {number} last_run_error_ct
 * @property {number} last_run_dismissed_ct
 * 
 * @typedef TableGroupSummary
 * @type {object}
 * @property {string} id
 * @property {string} table_groups_name
 * @property {string} table_groups_name
 * @property {number?} dq_score
 * @property {number?} dq_score_profiling
 * @property {number?} dq_score_testing
 * @property {string} latest_profile_id
 * @property {string} latest_profile_start
 * @property {number} latest_profile_table_ct
 * @property {number} latest_profile_column_ct
 * @property {number} latest_anomalies_ct
 * @property {number} latest_anomalies_definite_ct
 * @property {number} latest_anomalies_likely_ct
 * @property {number} latest_anomalies_possible_ct
 * @property {number} latest_anomalies_dismissed_ct
 * @property {string} latest_tests_start
 * @property {number} latest_tests_suite_ct
 * @property {number} latest_tests_ct
 * @property {number} latest_tests_passed_ct
 * @property {number} latest_tests_warning_ct
 * @property {number} latest_tests_failed_ct
 * @property {number} latest_tests_error_ct
 * @property {number} latest_tests_dismissed_ct
 * @property {TestSuiteSummary[]} test_suites
 * @property {boolean} expanded
 * 
 * @typedef SortOption
 * @type {object}
 * @property {string} value
 * @property {string} label
 * @property {boolean} selected
 * 
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project
 * @property {TableGroupSummary[]} table_groups
 * @property {SortOption[]} table_groups_sort_options
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, truncateFloat } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { Card } from '../components/card.js';
import { Caption } from '../components/caption.js';
import { ExpanderToggle } from '../components/expander_toggle.js';
import { Select } from '../components/select.js';
import { Input } from '../components/input.js';
import { Link } from '../components/link.js';
import { SummaryBar } from '../components/summary_bar.js';
import { EmptyState } from '../components/empty_state.js';
import { Metric } from '../components/metric.js';

const { div, h3, hr, span, strong } = van.tags;

const Overview = (/** @type Properties */ props) => {
    loadStylesheet('overview', stylesheet);
    Streamlit.setFrameHeight(1);
    window.frameElement.style.setProperty('height', 'calc(100vh - 200px)');
    window.testgen.isPage = true;

    const isEmpty = van.derive(() => {
        const projectSummary = getValue(props.project)
        return projectSummary.test_runs_count <= 0 && projectSummary.profiling_runs_count <= 0;
    });
    const tableGroups = van.derive(() => getValue(props.table_groups));
    const filteredTableGroups = van.state(getValue(tableGroups));
    const tableGroupsSearchTerm = van.state('');
    const tableGroupsSortOption = van.state(getValue(props.table_groups_sort_options).find(o => o.selected)[0]?.value);
    const sortFunctions = {
        table_groups_name: (a, b) => a.table_groups_name.toLowerCase().localeCompare(b.toLowerCase()),
        latest_activity_date: (a, b) => Math.max(b.latest_profile_start, b.latest_tests_start) - Math.max(a.latest_profile_start, a.latest_tests_start),
    };

    van.derive(() => {
        const searchTerm = getValue(tableGroupsSearchTerm);
        filteredTableGroups.val = getValue(tableGroups).filter(group => group.table_groups_name.toLowerCase().includes(searchTerm.toLowerCase() ?? ''));
    });

    van.derive(() => {
        const sortByField = getValue(tableGroupsSortOption);
        const sortFn = sortFunctions[sortByField] ?? sortFunctions.latest_activity_date
        filteredTableGroups.val = getValue(filteredTableGroups).sort(sortFn);
    });

    return div(
        { class: 'flex-column tg-overview' },
        () => !getValue(isEmpty)
            ? div(
                { class: 'flex-row fx-align-stretch', style: 'gap: 1rem;' },
                Card({
                    id: 'overview-project-summary',
                    class: 'tg-overview--project',
                    content: [
                        () => div(
                            { class: 'flex-row fx-align-flex-start' },
                            // div(
                            //     { class: 'flex-column tg-overview--project--score' },
                            //     Caption({ content: 'Project HIT score', style: 'margin-bottom: 16px;' }),
                            //     Metric({value: 100, delta: 10}),
                            // ),
                            () => {
                                return div(
                                    { class: 'flex-column tg-overview--project--summary' },
                                    Caption({content: 'Project Summary', style: 'margin-bottom: 16px;' }),
                                    div(
                                        { style: 'margin-bottom: 8px;' },
                                        strong({ style: 'margin-right: 4px;' }, props.project.val.table_groups_count),
                                        span('table groups'),
                                    ),
                                    div(
                                        { style: 'margin-bottom: 8px;' },
                                        strong({ style: 'margin-right: 4px;' }, props.project.val.test_suites_count),
                                        span('test suites'),
                                    ),
                                    div(
                                        { style: 'margin-bottom: 8px;' },
                                        strong({ style: 'margin-right: 4px;' }, props.project.val.test_definitions_count),
                                        span('test definitions'),
                                    ),
                                );
                            }
                        ),
                    ],
                }),
            )
            : ConditionalEmptyState(getValue(props.project)),
        () => !getValue(isEmpty)
            ? div(
                { class: 'flex-row' },
                h3(() => `Table Groups (${tableGroups?.val?.length ?? 0})`),
                span({ style: 'margin-right: auto;' }),
                Input({
                    label: 'Search by table group name',
                    width: 230,
                    height: 38,
                    style: 'font-size: 14px;',
                    onChange: (value) => tableGroupsSearchTerm.val = value,
                }),
                span({ style: 'margin-right: 1rem;' }),
                Select({
                    label: 'Sort by',
                    options: props.table_groups_sort_options?.val ?? [],
                    height: 38,
                    style: 'font-size: 14px;',
                    onChange: (value) => tableGroupsSortOption.val = value,
                }),
            )
            : undefined,
        () => !getValue(isEmpty)
            ? div(
                { class: 'flex-column mt-2' },
                getValue(filteredTableGroups).map(tableGroup => TableGroupCard(tableGroup)),
            )
            : undefined,
    );
}

const TableGroupCard = (/** @type TableGroupSummary */ tableGroup) => {
    return Card({
        title: () => div(
            { class: 'flex-row' },
            span({ style: 'display: block; margin-right: auto;' }, tableGroup.table_groups_name),
            ExpanderToggle({
                default: tableGroup.expanded,
                style: 'font-size: 14px !important; font-weight: 400;',
                onExpand: () => {
                    emitEvent('TableGroupExpanded', {payload: tableGroup.id});
                },
                onCollapse: () => {
                    emitEvent('TableGroupCollapsed', {payload: tableGroup.id});
                },
            }),
        ),
        class: 'tg-overview--table-group-card',
        content: () => div(
            { class: 'flex-column' },
            div(
                { class: 'flex-row flex-align-flex-start' },
                div(
                    { class: 'flex-column fx-flex' },
                    TableGroupLatestProfile(tableGroup),
                ),
                div(
                    { class: 'flex-column fx-flex' },
                    TableGroupLatestTestResults(tableGroup),
                ),
                div(
                    { class: 'flex-column fx-align-flex-center', style: 'flex: 0 1 10%;' },
                    Metric({ value: tableGroup.dq_score ?? '--' }),
                    Caption({ content: 'Score' }),
                ),
            ),
            tableGroup.expanded
                ? hr({ class: 'tg-overview--table-group-divider' })
                : undefined,
            tableGroup.expanded
                ? TableGroupTestSuiteSummary(tableGroup.test_suites)
                : undefined,
        )
    });
};

const TableGroupLatestProfile = (/** @type TableGroupSummary */ tableGroup) => {
    return [
        Caption({ content: 'Latest profile' }),
        div(
            { class: 'flex-row mb-3' },
            Link({
                label: formatTimestamp(tableGroup.latest_profile_start),
                href: 'profiling-runs:results',
                params: { run_id: tableGroup.latest_profile_id },
            }),
            span({ class: 'mr-1 ml-1' }, '|'),
            span(`Profiling score: ${tableGroup.dq_score_profiling}`),
        ),
        div(
            { class: 'flex-row mb-3' },
            strong({ class: 'mr-1' }, tableGroup.latest_profile_table_ct),
            span('tables'),
            span({ class: 'mr-1 ml-1' }, '|'),
            strong({ class: 'mr-1' }, tableGroup.latest_profile_column_ct),
            span('columns'),
            span({ class: 'mr-1 ml-1' }, '|'),
            Link({
                label: `${tableGroup.latest_anomalies_ct} hygiene issues`,
                href: 'profiling-runs:hygiene',
                params: {
                    run_id: tableGroup.latest_profile_id,
                },
                width: 150,
            })
        ),
        () => tableGroup.latest_anomalies_ct
            ? SummaryBar({
                items: [
                    { label: 'Definite', value: parseInt(tableGroup.latest_anomalies_definite_ct), color: 'red' },
                    { label: 'Likely', value: parseInt(tableGroup.latest_anomalies_likely_ct), color: 'orange' },
                    { label: 'Possible', value: parseInt(tableGroup.latest_anomalies_possible_ct), color: 'yellow' },
                    { label: 'Dismissed', value: parseInt(tableGroup.latest_anomalies_dismissed_ct), color: 'grey' },
                ],
                height: 12,
                width: 280,
            })
            : '',
    ];
};

const TableGroupLatestTestResults = (/** @type TableGroupSummary */ tableGroup) => {
    return [
        Caption({ content: 'Latest test results' }),
        () => tableGroup.latest_tests_ct
            ? div(
                { class: 'flex-column' },
                span(
                    { class: 'mb-3' },
                    `${truncateFloat(tableGroup.latest_tests_passed_ct * 100 / tableGroup.latest_tests_ct)}% passed | Test score: ${tableGroup.dq_score_testing}`,
                ),
                div(
                    { class: 'flex-row mb-3' },
                    strong({ class: 'mr-1' }, tableGroup.latest_tests_ct),
                    span({ class: 'mr-1' }, 'tests in'),
                    strong({ class: 'mr-1' }, tableGroup.latest_tests_suite_ct),
                    span('test suites'),
                ),
                SummaryBar({
                    items: [
                        { label: 'Passed', value: parseInt(tableGroup.latest_tests_passed_ct), color: 'green' },
                        { label: 'Warning', value: parseInt(tableGroup.latest_tests_warning_ct), color: 'yellow' },
                        { label: 'Failed', value: parseInt(tableGroup.latest_tests_failed_ct), color: 'red' },
                        { label: 'Error', value: parseInt(tableGroup.latest_tests_error_ct), color: 'brown' },
                        { label: 'Dismissed', value: parseInt(tableGroup.latest_tests_dismissed_ct), color: 'grey' },
                    ],
                    height: 12,
                    width: 350,
                })
            )
            : span('--'),
    ];
};

const TableGroupTestSuiteSummary = (/** @type TestSuiteSummary[] */testSuites) => {
    return div(
        { class: 'flex-column' },
        div(
            { class: 'flex-row mb-4' },
            Caption({ content: 'Test Suite', style: 'flex: 1 1 20%;' }),
            Caption({ content: 'Latest Generation', style: 'flex: 1 1 15%;' }),
            Caption({ content: 'Latest Run', style: 'flex: 1 1 15%;' }),
            Caption({ content: 'Latest Results', style: 'flex: 1 1 50%;' }),
        ),
        testSuites.map(suite => div(
            { class: 'flex-row' },
            div(
                { class: 'flex-column', style: 'flex: 1 1 20%;' },
                Link({
                    label: suite.test_suite,
                    href: 'test-suites:definitions',
                    params: { test_suite_id: suite.id },
                }),
                Caption({ content: `${suite.test_ct} tests`}),
            ),
            suite.latest_auto_gen_date
                ? span(
                    { style: 'flex: 1 1 15%;' },
                    formatTimestamp(suite.latest_auto_gen_date),
                )
                : '--',
            suite.latest_run_id
                ? Link({
                    label: formatTimestamp(suite.latest_auto_gen_date),
                    href: 'test-runs:results',
                    params: { run_id: suite.latest_run_id },
                    style: 'flex: 1 1 15%;',
                })
                : '--',
            suite.last_run_test_ct
                ? div(
                    { style: 'flex: 1 1 50%;' },
                    SummaryBar({
                        items: [
                            { label: 'Passed', 'value': parseInt(suite.last_run_passed_ct), color: 'green' },
                            { label: 'Warning', 'value': parseInt(suite.last_run_warning_ct), color: 'yellow' },
                            { label: 'Failed', 'value': parseInt(suite.last_run_failed_ct), color: 'red' },
                            { label: 'Error', 'value': parseInt(suite.last_run_error_ct), color: 'brown' },
                            { label: 'Dismissed', 'value': parseInt(suite.last_run_dismissed_ct), color: 'grey' },
                        ],
                        width: 200,
                        height: 8,
                    })
                )
                : '--',
        ))
    );
};

const ConditionalEmptyState = (/** @type ProjectSummary */ project) => {
    const forConnections = {
        message: {
            line1: 'Begin by connecting your database.',
            line2: 'TestGen delivers data quality through data profiling, hygiene review, test generation, and test execution.',
        },
        link: {
            label: 'Go to Connections',
            href: 'connections',
        },
    };
    const forTablegroups = {
        message: {
            line1: 'Profile your tables to detect hygiene issues',
            line2: 'Create table groups for your connected databases to run data profiling and hygiene review.',
        },
        link: {
            label: 'Go to Table Groups',
            href: 'connections:table-groups',
            params: { connection_id: project.default_connection_id },
        },
    };

    const args = project.connections_count > 0 ? forTablegroups : forConnections;

    return EmptyState({
        icon: 'home',
        label: 'Your project is empty',
        ...args,
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-overview {
    width: 100%;
}

.tg-overview--project {
    border: 1px solid var(--border-color);
    width: 50%;
}

.tg-overview--project--score {
    margin-right: auto;
}

.tg-overview--project--summary {
    margin-right: auto;
}

.tg-overview--table-group-card {
    border: 1px solid var(--border-color);
}

hr.tg-overview--table-group-divider {
    height: 1px;
    margin: 8px 0 12px;
    padding: 0px;
    color: inherit;
    background-color: transparent;
    border-top: none;
    border-right: none;
    border-left: none;
    border-image: initial;
    border-bottom: 1px solid rgba(49, 51, 63, 0.2);
}
`);

export { Overview };
