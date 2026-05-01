/**
 * @import { FilterOption, ProjectSummary } from '../types.js';
 * @import { TestSuiteSummary } from '../types.js';
 * @import { MonitorSummary } from '/app/static/js/components/monitor_anomalies_summary.js';
 * 
 * @typedef TableGroupSummary
 * @type {object}
 * @property {string} id
 * @property {string} table_groups_name
 * @property {number} table_ct
 * @property {number} column_ct
 * @property {number} approx_record_ct
 * @property {number} record_ct
 * @property {number} approx_data_point_ct
 * @property {number} data_point_ct
 * @property {string?} dq_score
 * @property {string?} dq_score_profiling
 * @property {string?} dq_score_testing
 * @property {string?} latest_profile_id
 * @property {string?} latest_profile_job_execution_id
 * @property {number?} latest_profile_start
 * @property {number} latest_hygiene_issues_ct
 * @property {number} latest_hygiene_issues_definite_ct
 * @property {number} latest_hygiene_issues_likely_ct
 * @property {number} latest_hygiene_issues_possible_ct
 * @property {number} latest_hygiene_issues_dismissed_ct
 * @property {number?} latest_tests_start
 * @property {TestSuiteSummary[]} test_suites
 * @property {MonitorSummary?} monitoring_summary
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
import van from '/app/static/js/van.min.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { formatNumber, formatTimestamp, caseInsensitiveSort, caseInsensitiveIncludes } from '/app/static/js/display_utils.js';
import { Card } from '/app/static/js/components/card.js';
import { Select } from '/app/static/js/components/select.js';
import { Input } from '/app/static/js/components/input.js';
import { Link } from '/app/static/js/components/link.js';
import { SummaryBar } from '/app/static/js/components/summary_bar.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '/app/static/js/components/empty_state.js';
import { ScoreMetric } from '/app/static/js/components/score_metric.js';
import { SummaryCounts } from '/app/static/js/components/summary_counts.js';
import { AnomaliesSummary } from '/app/static/js/components/monitor_anomalies_summary.js';

const { div, h3, hr, span } = van.tags;

const staleProfileDays = 60;

const ProjectDashboard = (/** @type Properties */ props) => {
    const { emit } = props;
    loadStylesheet('project-dashboard', stylesheet);

    const tableGroups = van.derive(() => getValue(props.table_groups));
    const tableGroupsSearchTerm = van.state('');
    const tableGroupsSortOption = van.state(getValue(props.table_groups_sort_options).find(o => o.selected)?.value);
    const filteredTableGroups = van.state(getValue(tableGroups));

    const sortFunctions = {
        table_groups_name: (a, b) => caseInsensitiveSort(a.table_groups_name, b.table_groups_name),
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

        filteredTableGroups.val = getValue(tableGroups).filter(group => caseInsensitiveIncludes(group.table_groups_name, searchTerm ?? '')).sort(sortFn);
    }

    onFiltersChange();

    van.derive(onFiltersChange);

    const wrapperId = 'overview-wrapper';

    return div(
        { id: wrapperId, 'data-testid': 'project-dashboard', class: 'flex-column tg-overview' },
        () => getValue(tableGroups).length
            ? div(
                { class: 'flex-row fx-align-flex-end fx-gap-3' },
                Input({
                    width: 230,
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
                    style: 'font-size: 14px;',
                    testId: 'table-groups-sort',
                }),
            )
            : '',
        () => getValue(tableGroups).length
            ? getValue(filteredTableGroups).length
                ? div(
                    { class: 'flex-column mt-4 fx-gap-3' },
                    getValue(filteredTableGroups).map(tableGroup =>
                        tableGroup.monitoring_summary
                            ? TableGroupCardWithMonitor(tableGroup, getValue(props.project_summary)?.project_code, emit)
                            : TableGroupCard(tableGroup, getValue(props.project_summary)?.project_code, emit)
                    )
                )
                : div(
                    { class: 'mt-7 text-secondary', style: 'text-align: center;' },
                    'No table groups found matching filters',
                )
            : ConditionalEmptyState(getValue(props.project_summary), emit),
    );
}

const TableGroupCard = (/** @type TableGroupSummary */ tableGroup, /** @type string */ projectCode, emit) => {
    const useApprox = tableGroup.record_ct === null || tableGroup.record_ct === undefined;

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
                        `${formatNumber(tableGroup.table_ct ?? 0)} tables | 
                        ${formatNumber(tableGroup.column_ct ?? 0)} columns | 
                        ${formatNumber(useApprox ? tableGroup.approx_record_ct : tableGroup.record_ct)} rows
                        ${useApprox ? '*' : ''} |
                        ${formatNumber(useApprox ? tableGroup.approx_data_point_ct : tableGroup.data_point_ct)} data points
                        ${useApprox ? '*' : ''}`,
                    ),
                    TableGroupTestSuiteSummary(tableGroup.test_suites, projectCode, emit),
                ),
                ScoreMetric(tableGroup.dq_score, tableGroup.dq_score_profiling, tableGroup.dq_score_testing),
            ),
            hr({ class: 'tg-overview--table-group-divider' }),
            TableGroupLatestProfile(tableGroup, projectCode, emit),
            useApprox
                ? span({ class: 'text-caption text-right' }, '* Approximate counts based on server statistics')
                : null,
        )
    });
};

const TableGroupCardWithMonitor = (/** @type TableGroupSummary */ tableGroup, /** @type string */ projectCode, emit) => {
    const useApprox = tableGroup.record_ct === null || tableGroup.record_ct === undefined;
    return Card({
        testId: 'table-group-summary-card',
        border: true,
        content: () => div(
            { class: 'flex-column' },

            div(
                { class: 'flex-row fx-align-flex-start fx-justify-space-between' },
                div(
                    { class: 'flex-column', style: 'flex: auto;' },
                    div(
                        { class: 'flex-column', style: 'flex: auto;' },
                        h3(
                            { class: 'tg-overview--title' },
                            tableGroup.table_groups_name,
                        ),
                        span(
                            { class: 'text-caption mt-1 mb-3 tg-overview--subtitle' },
                            `${formatNumber(tableGroup.table_ct ?? 0)} tables | 
                            ${formatNumber(tableGroup.column_ct ?? 0)} columns | 
                            ${formatNumber(useApprox ? tableGroup.approx_record_ct : tableGroup.record_ct)} rows
                            ${useApprox ? '*' : ''} |
                            ${formatNumber(useApprox ? tableGroup.approx_data_point_ct : tableGroup.data_point_ct)} data points
                            ${useApprox ? '*' : ''}`,
                        ),
                    ),
                    AnomaliesSummary(tableGroup.monitoring_summary, 'Monitor anomalies', {}, emit),
                ),
                ScoreMetric(tableGroup.dq_score, tableGroup.dq_score_profiling, tableGroup.dq_score_testing),
            ),

            hr({ class: 'tg-overview--table-group-divider' }),
            TableGroupTestSuiteSummary(tableGroup.test_suites, projectCode, emit),
            hr({ class: 'tg-overview--table-group-divider' }),
            TableGroupLatestProfile(tableGroup, projectCode, emit),
            useApprox
                ? span({ class: 'text-caption text-right' }, '* Approximate counts based on server statistics')
                : null,
        )
    });
};

const TableGroupLatestProfile = (/** @type TableGroupSummary */ tableGroup, /** @type string */ projectCode, emit) => {
    if (!tableGroup.latest_profile_start) {
        return div(
            { class: 'mt-1 mb-1 text-secondary' },
            'No profiling data yet',
        );
    }

    const daysAgo = Math.round((new Date() - new Date(tableGroup.latest_profile_start * 1000)) / (1000 * 60 * 60 * 24));

    return div(
        { class: 'flex-row tg-overview--row' },
        div(
            { class: 'flex-row fx-gap-2', style: 'flex: 1 1 50%;' },
            span('Latest profile:'),
            Link({ emit,
                label: formatTimestamp(tableGroup.latest_profile_start),
                href: 'profiling-runs:results',
                params: { run_id: tableGroup.latest_profile_job_execution_id, project_code: projectCode },
            }),
            daysAgo > staleProfileDays
                ? span({ class: 'text-error' }, `(${daysAgo} days ago)`)
                : null,
        ),
        div(
            { class: 'flex-row fx-gap-5', style: 'flex: 1 1 50%;' },
            Link({ emit,
                label: `${tableGroup.latest_hygiene_issues_ct} hygiene issues`,
                href: 'profiling-runs:hygiene',
                params: {
                    run_id: tableGroup.latest_profile_job_execution_id,
                    project_code: projectCode,
                },
                width: 150,
                style: 'flex: 0 0 auto;',
            }),
            tableGroup.latest_hygiene_issues_ct
            ? SummaryCounts({
                items: [
                    { label: 'Definite', value: parseInt(tableGroup.latest_hygiene_issues_definite_ct), color: 'red' },
                    { label: 'Likely', value: parseInt(tableGroup.latest_hygiene_issues_likely_ct), color: 'orange' },
                    { label: 'Possible', value: parseInt(tableGroup.latest_hygiene_issues_possible_ct), color: 'yellow' },
                    { label: 'Dismissed', value: parseInt(tableGroup.latest_hygiene_issues_dismissed_ct), color: 'grey' },
                ],
            })
            : '',
        ),
    );
};

const TableGroupTestSuiteSummary = (/** @type TestSuiteSummary[] */testSuites, /** @type string */ projectCode, emit) => {
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
                Link({ emit, 
                    label: suite.test_suite,
                    href: 'test-suites:definitions',
                    params: { test_suite_id: suite.id, project_code: projectCode },
                }),
                span({ class: 'text-caption' }, `${suite.test_ct ?? 0} tests`),
            ),
            suite.latest_run_id
                ? Link({ emit,
                    label: formatTimestamp(suite.latest_run_start),
                    href: 'test-runs:results',
                    params: { run_id: suite.latest_run_job_execution_id, project_code: projectCode },
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
                        { label: 'Log', 'value': parseInt(suite.last_run_log_ct), color: 'blue' },
                        { label: 'Dismissed', 'value': parseInt(suite.last_run_dismissed_ct), color: 'grey' },
                    ],
                    width: 350,
                    height: 8,
                }) : '--',
            ),
        ))
    );
};

const ConditionalEmptyState = (/** @type ProjectSummary */ project, emit) => {
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

    return EmptyState({ emit, 
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
        van.add(parentElement, ProjectDashboard(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => {
        parentElement.state = null;
    };
};
