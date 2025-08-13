/**
 * @import { ProjectSummary } from '../types.js';
 * @import { TestSuiteSummary } from '../types.js';
 * 
 * @typedef TableGroupSummary
 * @type {object}
 * @property {string} id
 * @property {string} table_groups_name
 * @property {string?} dq_score
 * @property {string?} dq_score_profiling
 * @property {string?} dq_score_testing
 * @property {string?} latest_profile_id
 * @property {number?} latest_profile_start
 * @property {number} latest_profile_table_ct
 * @property {number} latest_profile_column_ct
 * @property {number} latest_anomalies_ct
 * @property {number} latest_anomalies_definite_ct
 * @property {number} latest_anomalies_likely_ct
 * @property {number} latest_anomalies_possible_ct
 * @property {number} latest_anomalies_dismissed_ct
 * @property {number?} latest_tests_start
 * @property {TestSuiteSummary[]} test_suites
 *
 * @typedef SortOption
 * @type {object}
 * @property {string} value
 * @property {string} label
 * @property {boolean} selected
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {TableGroupSummary[]} table_groups
 * @property {SortOption[]} table_groups_sort_options
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { Card } from '../components/card.js';
import { Select } from '../components/select.js';
import { Input } from '../components/input.js';
import { Link } from '../components/link.js';
import { SummaryBar } from '../components/summary_bar.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '../components/empty_state.js';
import { ScoreMetric } from '../components/score_metric.js';

const { div, h3, hr, span } = van.tags;

const staleProfileDays = 60;

const ProjectDashboard = (/** @type Properties */ props) => {
    loadStylesheet('project-dashboard', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

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
        () => getValue(tableGroups).length
            ? div(
                { class: 'flex-row fx-align-flex-end fx-gap-4' },
                Input({
                    width: 230,
                    height: 38,
                    style: 'font-size: 14px;',
                    icon: 'search',
                    clearable: true,
                    placeholder: 'Search table group names',
                    testId: 'table-groups-filter',
                    onChange: (value) => tableGroupsSearchTerm.val = value,
                }),
                Select({
                    label: 'Sort by',
                    value: tableGroupsSortOption,
                    options: props.table_groups_sort_options?.val ?? [],
                    height: 38,
                    style: 'font-size: 14px;',
                    testId: 'table-groups-sort',
                }),
            )
            : '',
        () => getValue(tableGroups).length
            ? getValue(filteredTableGroups).length
                ? div(
                    { class: 'flex-column mt-4' },
                    getValue(filteredTableGroups).map(tableGroup => TableGroupCard(tableGroup))   
                )
                : div(
                    { class: 'mt-7 text-secondary', style: 'text-align: center;' },
                    'No table groups found matching filters',
                )
            : ConditionalEmptyState(getValue(props.project_summary)),
    );
}

const TableGroupCard = (/** @type TableGroupSummary */ tableGroup) => {
    return Card({
        testId: 'table-group-summary-card',
        border: true,
        content: () => div(
            { class: 'flex-column' },
            div(
                { class: 'flex-row fx-align-flex-start fx-justify-space-between' },
                div(
                    { class: 'flex-column', style: 'flex: auto;' },
                    h3(
                        { class: 'tg-overview--title' },
                        tableGroup.table_groups_name,
                    ),
                    span(
                        { class: 'text-caption mt-1 mb-3 tg-overview--subtitle' },
                        `${tableGroup.latest_profile_table_ct ?? 0} tables | ${tableGroup.latest_profile_column_ct ?? 0} columns`,
                    ),
                    TableGroupTestSuiteSummary(tableGroup.test_suites),
                ),
                ScoreMetric(tableGroup.dq_score, tableGroup.dq_score_profiling, tableGroup.dq_score_testing),
            ),
            hr({ class: 'tg-overview--table-group-divider' }),
            TableGroupLatestProfile(tableGroup),
        )
    });
};

const TableGroupLatestProfile = (/** @type TableGroupSummary */ tableGroup) => {
    if (!tableGroup.latest_profile_start) {
        return div(
            { class: 'mt-1 mb-1 text-secondary' },
            'No profiling data yet',
        );
    }

    const daysAgo = Math.round((new Date() - new Date(tableGroup.latest_profile_start * 1000)) / (1000 * 60 * 60 * 24));

    return div(
        div(
            { class: 'flex-row fx-gap-1 mb-2' },
            span('Latest profile:'),
            Link({
                label: formatTimestamp(tableGroup.latest_profile_start),
                href: 'profiling-runs:results',
                params: { run_id: tableGroup.latest_profile_id },
            }),
            daysAgo > staleProfileDays
                ? span({ class: 'text-error' }, `(${daysAgo} days ago)`)
                : null,
            span('|'),
            Link({
                label: `${tableGroup.latest_anomalies_ct} hygiene issues`,
                href: 'profiling-runs:hygiene',
                params: {
                    run_id: tableGroup.latest_profile_id,
                },
                width: 150,
            }),
        ),
        tableGroup.latest_anomalies_ct
            ? SummaryBar({
                items: [
                    { label: 'Definite', value: parseInt(tableGroup.latest_anomalies_definite_ct), color: 'red' },
                    { label: 'Likely', value: parseInt(tableGroup.latest_anomalies_likely_ct), color: 'orange' },
                    { label: 'Possible', value: parseInt(tableGroup.latest_anomalies_possible_ct), color: 'yellow' },
                    { label: 'Dismissed', value: parseInt(tableGroup.latest_anomalies_dismissed_ct), color: 'grey' },
                ],
                height: 3,
                width: 350,
            })
            : '',
    );
};

const TableGroupTestSuiteSummary = (/** @type TestSuiteSummary[] */testSuites) => {
    if (!testSuites?.length) {
        return div(
            { class: 'mt-1 mb-1 text-secondary' },
            'No test suites yet',
        );
    }

    return div(
        { class: 'flex-column' },
        div(
            { class: 'flex-row mb-1 tg-overview--row' },
            span({ style: 'flex: 1 1 25%;' }, 'Test Suite'),
            span({ style: 'flex: 1 1 25%;' }, 'Latest Run'),
            span({ style: 'flex: 1 1 50%;' }, 'Latest Results'),
        ),
        testSuites.map(suite => div(
            { class: 'flex-row fx-align-flex-start mt-2 tg-overview--row' },
            div(
                { class: 'flex-column', style: 'flex: 1 1 25%; word-break: break-word;' },
                Link({
                    label: suite.test_suite,
                    href: 'test-suites:definitions',
                    params: { test_suite_id: suite.id },
                }),
                span({ class: 'text-caption' }, `${suite.test_ct ?? 0} tests`),
            ),
            suite.latest_run_id
                ? Link({
                    label: formatTimestamp(suite.latest_run_start),
                    href: 'test-runs:results',
                    params: { run_id: suite.latest_run_id },
                    style: 'flex: 1 1 25%;',
                })
                : span({ style: 'flex: 1 1 25%;' }, '--'),
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
                    width: 350,
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
            params: { project_code: project.project_code },
        },
    };
    const forTablegroups = {
        message: EMPTY_STATE_MESSAGE.tableGroup,
        link: {
            label: 'Go to Table Groups',
            href: 'table-groups',
            params: { project_code: project.project_code, connection_id: project.default_connection_id },
        },
    };

    const args = project.connection_count > 0 ? forTablegroups : forConnections;

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

.tg-overview--title {
    margin: 0;
    font-size: 18px;
    font-weight: 500;
}

.tg-overview--subtitle {
    text-transform: none;
    font-weight: 400;
}

hr.tg-overview--table-group-divider {
    height: 1px;
    margin: 12px 0;
    padding: 0px;
    color: inherit;
    background-color: transparent;
    border-top: none;
    border-right: none;
    border-left: none;
    border-image: initial;
    border-bottom: 1px solid var(--border-color);
}

.tg-overview--row > * {
    padding: 0 4px;
}
`);

export { ProjectDashboard };
