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
import { emitEvent, getValue, loadStylesheet, friendlyPercent, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { Card } from '../components/card.js';
import { Caption } from '../components/caption.js';
import { ExpanderToggle } from '../components/expander_toggle.js';
import { Select } from '../components/select.js';
import { Input } from '../components/input.js';
import { Link } from '../components/link.js';
import { SummaryBar } from '../components/summary_bar.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '../components/empty_state.js';
import { ScoreMetric } from '../components/score_metric.js';

const { div, h3, hr, span, strong } = van.tags;

const ProjectDashboard = (/** @type Properties */ props) => {
    loadStylesheet('project-dashboard', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const isEmpty = van.derive(() => {
        const projectSummary = getValue(props.project)
        return projectSummary.test_runs_count <= 0 && projectSummary.profiling_runs_count <= 0;
    });
    const tableGroups = van.derive(() => getValue(props.table_groups));
    const tableGroupsSearchTerm = van.state('');
    const tableGroupsSortOption = van.state(getValue(props.table_groups_sort_options).find(o => o.selected)?.value);
    const filteredTableGroups = van.state(getValue(tableGroups));

    const sortFunctions = {
        table_groups_name: (a, b) => a.table_groups_name.toLowerCase().localeCompare(b.table_groups_name.toLowerCase()),
        latest_activity_date: (a, b) => Math.max(b.latest_profile_start, b.latest_tests_start) - Math.max(a.latest_profile_start, a.latest_tests_start),
        lowest_score: (a, b) => {
            const scoreA = a.dq_score ? (a.dq_score.startsWith('>') ? 99.99 : Number(a.dq_score)) : 101;
            const scoreB = b.dq_score ? (b.dq_score.startsWith('>') ? 99.99 : Number(b.dq_score)) : 101;
            return scoreA - scoreB;
        },
    };
    const onFiltersChange = function() {
        const searchTerm = getValue(tableGroupsSearchTerm);
        const sortByField = getValue(tableGroupsSortOption);
        const sortFn = sortFunctions[sortByField] ?? sortFunctions.latest_activity_date;

        filteredTableGroups.val = getValue(tableGroups).filter(group => group.table_groups_name.toLowerCase().includes(searchTerm.toLowerCase() ?? '')).sort(sortFn);
    }

    onFiltersChange();

    van.derive(onFiltersChange);

    const wrapperId = 'overview-wrapper';
    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return div(
        { id: wrapperId, class: 'flex-column tg-overview' },
        () => !getValue(isEmpty)
            ? div(
                { class: 'flex-row fx-align-stretch fx-gap-4' },
                Card({
                    id: 'overview-project-summary',
                    class: 'tg-overview--project',
                    border: true,
                    content: [
                        () => div(
                            { class: 'flex-row fx-align-flex-start' },
                            () => {
                                return div(
                                    { class: 'flex-column fx-gap-2 tg-overview--project--summary' },
                                    Caption({content: 'Project Summary', style: 'margin-bottom: 8px;' }),
                                    div(
                                        strong({ style: 'margin-right: 4px;' }, props.project.val.table_groups_count),
                                        span('table groups'),
                                    ),
                                    div(
                                        strong({ style: 'margin-right: 4px;' }, props.project.val.test_suites_count),
                                        span('test suites'),
                                    ),
                                    div(
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
                { class: 'flex-row fx-align-flex-end' },
                h3(() => `Table Groups (${tableGroups?.val?.length ?? 0})`),
                span({ style: 'margin-right: auto;' }),
                Input({
                    width: 230,
                    height: 38,
                    style: 'font-size: 14px;',
                    icon: 'search',
                    clearable: true,
                    placeholder: 'Search table group names',
                    onChange: (value) => tableGroupsSearchTerm.val = value,
                }),
                span({ style: 'margin-right: 1rem;' }),
                Select({
                    label: 'Sort by',
                    value: tableGroupsSortOption,
                    options: props.table_groups_sort_options?.val ?? [],
                    height: 38,
                    style: 'font-size: 14px;',
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
        border: true,
        title: tableGroup.table_groups_name,
        actionContent: () => ExpanderToggle({
            default: tableGroup.expanded,
            style: 'font-size: 14px !important; font-weight: 400;',
            onExpand: () => {
                emitEvent('TableGroupExpanded', {payload: tableGroup.id});
            },
            onCollapse: () => {
                emitEvent('TableGroupCollapsed', {payload: tableGroup.id});
            },
        }),
        content: () => div(
            { class: 'flex-column' },
            div(
                { class: 'flex-row fx-align-flex-start' },
                div(
                    { class: 'flex-column fx-flex' },
                    TableGroupLatestProfile(tableGroup),
                ),
                div(
                    { class: 'flex-column fx-flex' },
                    TableGroupLatestTestResults(tableGroup),
                ),
                ScoreMetric(tableGroup.dq_score, tableGroup.dq_score_profiling, tableGroup.dq_score_testing),
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
        () => tableGroup.latest_profile_start ? div(
            div(
                { class: 'flex-row mb-3' },
                Link({
                    label: formatTimestamp(tableGroup.latest_profile_start),
                    href: 'profiling-runs:results',
                    params: { run_id: tableGroup.latest_profile_id },
                }),
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
        )
        : span('--'),
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
                    `${friendlyPercent(tableGroup.latest_tests_passed_ct * 100 / tableGroup.latest_tests_ct)}% passed`,
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
            { class: 'flex-row mb-2' },
            div(
                { class: 'flex-column', style: 'flex: 1 1 20%;' },
                Link({
                    label: suite.test_suite,
                    href: 'test-suites:definitions',
                    params: { test_suite_id: suite.id },
                }),
                Caption({ content: `${suite.test_ct ?? 0} tests`}),
            ),
            span(
                { style: 'flex: 1 1 15%;' },
                suite.latest_auto_gen_date ? formatTimestamp(suite.latest_auto_gen_date) : '--',
            ),
            suite.latest_run_id
                ? Link({
                    label: formatTimestamp(suite.latest_run_start),
                    href: 'test-runs:results',
                    params: { run_id: suite.latest_run_id },
                    style: 'flex: 1 1 15%;',
                })
                : span({ style: 'flex: 1 1 15%;' }, '--'),
            div(
                { style: 'flex: 1 1 50%;' },
                suite.last_run_test_ct ? SummaryBar({
                    items: [
                        { label: 'Passed', 'value': parseInt(suite.last_run_passed_ct), color: 'green' },
                        { label: 'Warning', 'value': parseInt(suite.last_run_warning_ct), color: 'yellow' },
                        { label: 'Failed', 'value': parseInt(suite.last_run_failed_ct), color: 'red' },
                        { label: 'Error', 'value': parseInt(suite.last_run_error_ct), color: 'brown' },
                        { label: 'Dismissed', 'value': parseInt(suite.last_run_dismissed_ct), color: 'grey' },
                    ],
                    width: 200,
                    height: 8,
                }) : '--',
            ),
        ))
    );
};

const ConditionalEmptyState = (/** @type ProjectSummary */ project) => {
    const forConnections = {
        message: EMPTY_STATE_MESSAGE.connection,
        link: {
            label: 'Go to Connections',
            href: 'connections',
        },
    };
    const forTablegroups = {
        message: EMPTY_STATE_MESSAGE.tableGroup,
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
    margin: 8px 0;
    width: 50%;
}

.tg-overview--project--score {
    margin-right: auto;
}

.tg-overview--project--summary {
    margin-right: auto;
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

export { ProjectDashboard };
