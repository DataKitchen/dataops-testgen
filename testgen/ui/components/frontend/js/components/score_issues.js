/**
 * @typedef Issue
 * @type {object}
 * @property {string} id
 * @property {('hygiene' | 'test')} issue_type
 * @property {string} table_group_id
 * @property {string} table
 * @property {string} column
 * @property {string} type
 * @property {string} status
 * @property {string} detail
 * @property {number} time
 * @property {string} name
 * @property {string} run_id
 *
 * @typedef Score
 * @type {object}
 * @property {string} project_code
 * @property {string} name
 */
import van from '../van.min.js';
import { Link } from '../components/link.js';
import { Caption } from '../components/caption.js';
import { dot } from '../components/dot.js';
import { Button } from '../components/button.js';
import { Checkbox } from '../components/checkbox.js';
import { Select } from './select.js';
import { Paginator } from '../components/paginator.js';
import { emitEvent, loadStylesheet } from '../utils.js';
import { colorMap, formatTimestamp } from '../display_utils.js';

const { div, i, span } = van.tags;
const PAGE_SIZE = 100;
const SCROLL_CONTAINER = window.top.document.querySelector('.stMain');
const statusColors = {
    'Potential PII': colorMap.grey,
    Likely: colorMap.orange,
    Possible: colorMap.yellow,
    Definite: colorMap.red,
    Warning: colorMap.yellow,
    Failed: colorMap.red,
    Passed: colorMap.green,
};

const IssuesTable = (
    /** @type Issue[] */ issues,
    /** @type string[] */ columns,
    /** @type Score */ score,
    /** @type ('score' | 'cde_score') */ scoreType,
    /** @type ('table_name' | 'column_name' | 'semantic_data_type' | 'dq_dimension') */ category,
    /** @type string */ drilldown,
    /** @type function */ onBack,
) => {
    loadStylesheet('score-issues-table', stylesheet);

    const drilldownParts = drilldown.split('.');
    const pageIndex = van.state(0);
    const filters = {
        table: van.state(['table_name', 'column_name'].includes(category) ? drilldownParts[1] : null),
        column: van.state(category === 'column_name' ? drilldownParts[2] : null),
        type: van.state(null),
        status: van.state(null),
    }

    const filteredIssues = van.derive(() => {
        pageIndex.val = 0;
        return issues
            .filter(({ table, column, type, status }) => (
                [ table, null ].includes(filters.table.val)
                && [ column, null ].includes(filters.column.val)
                && [ type, null ].includes(filters.type.val)
                && [ status, null ].includes(filters.status.val)
            ));
    });
    const displayedIssues = van.derive(() => filteredIssues.val.slice(PAGE_SIZE * pageIndex.val, PAGE_SIZE * (pageIndex.val + 1)));
    const selectedIssues = van.state([]);

    return div(
        { class: 'table', 'data-testid': 'score-issues' },
        div(
            { class: 'flex-row fx-justify-space-between fx-align-flex-start'},
            div(
                div(
                    {
                        class: 'issues-nav flex-row clickable',
                        style: 'color: var(--link-color);',
                        onclick: () => onBack(score.project_code, score.name, scoreType, category),
                    },
                    i({class: 'material-symbols-rounded', style: 'font-size: 20px;'}, 'chevron_left'),
                    span('Back'),
                ),
                div(
                    { class: 'issues-header table-header flex-row fx-align-flex-center fx-gap-1' },
                    span(`Hygiene / Test Issues (${issues.length ?? 0}) for`),
                    span(
                        { class: 'text-primary' },
                        `${COLUMN_LABEL[category] ?? '-'}: ${['table_name', 'column_name'].includes(category) ? drilldownParts.slice(1).join(' > ') : drilldown}`,
                    ),
                    category === 'column_name'
                        ? ColumnProfilingButton(drilldownParts[2], drilldownParts[1], drilldownParts[0])
                        : null,
                ),
            ),
            div(
                { class: 'flex-row' },
                () => {
                    const count = selectedIssues.val.length;
                    return count
                        ? span(
                            { class: 'text-secondary mr-4' },
                            span({ style: 'font-weight: 500' }, count),
                            ` issue${count > 1 ? 's' : ''} selected`
                        )
                        : '';
                },
                Button({
                    icon: 'download',
                    type: 'stroked',
                    label: 'Issue Reports',
                    width: 'fit-content',
                    style: 'margin-left: auto; background-color: var(--dk-card-background)',
                    onclick: () => emitEvent('IssueReportsExported', { payload: selectedIssues.val }),
                    disabled: () => !selectedIssues.val.length,
                    tooltip: () => selectedIssues.val.length ? '' : 'No issues selected',
                }),
            ),
        ),
        () => Toolbar(filters, issues, category),
        () => displayedIssues.val.length
        ? div(
            div(
                { class: 'table-header issues-columns flex-row' },
                Checkbox({
                    checked: () => selectedIssues.val.length === PAGE_SIZE,
                    indeterminate: () => !!selectedIssues.val.length,
                    onChange: (checked) => {
                        if (checked) {
                            selectedIssues.val = displayedIssues.val.map(({ id, issue_type }) => ({ id, issue_type }));
                        } else {
                            selectedIssues.val = [];
                        }
                    },
                }),
                span({ class: category === 'column_name' ? null : 'ml-6' }),
                columns.map(c => span({ style: `flex: ${c === 'detail' ? '1 1' : '0 0'} ${ISSUES_COLUMNS_SIZES[c]};` }, ISSUES_COLUMN_LABEL[c]))
            ),
            displayedIssues.val.map((row) => div(
                { class: 'table-row flex-row issues-row' },
                Checkbox({
                    checked: () => selectedIssues.val.map(({ id }) => id).includes(row.id),
                    onChange: (checked) => {
                        if (checked) {
                            selectedIssues.val = [ ...selectedIssues.val, { id: row.id, issue_type: row.issue_type } ];
                        } else {
                            selectedIssues.val = selectedIssues.val.filter(({ id }) => id !== row.id);
                        }
                    },
                }),
                category === 'column_name'
                    ? span({ class: 'ml-2' })
                    : ColumnProfilingButton(row.column, row.table, row.table_group_id),
                columns.map((columnName) => TableCell(row, columnName)),
            )),
            () => Paginator({
                pageIndex,
                count: filteredIssues.val.length,
                pageSize: PAGE_SIZE,
                onChange: (newIndex) => {
                    if (newIndex !== pageIndex.val) {
                        pageIndex.val = newIndex;
                        SCROLL_CONTAINER.scrollTop = 0;
                    }
                },
            }),
        )
        : div(
            { class: 'mt-7 mb-6 text-secondary', style: 'text-align: center;' },
            'No issues found matching filters',
        ),
    );
};

const ColumnProfilingButton = (
    /** @type {string} */ column_name,
    /** @type {string} */ table_name,
    /** @type {string} */ table_group_id,
) => {
    return Button({
        type: 'icon',
        icon: 'insert_chart',
        iconSize: 22,
        style: 'color: var(--secondary-text-color);',
        tooltip: 'View profiling for column',
        tooltipPosition: 'top-right',
        onclick: () => emitEvent('ColumnProflingClicked', { payload: { column_name, table_name, table_group_id } }),
    });
};

const Toolbar = (
    /** @type {object} */ filters,
    /** @type Issue[] */ issues,
    /** @type ('table_name' | 'column_name' | 'semantic_data_type' | 'dq_dimension') */ category,
) => {
    const filterOptions = {
        table: [ ...new Set(issues.map(({ table }) => table)) ]
            .sort()
            .map(value => ({ label: value, value })),
        column: van.derive(() => (
            [ ...new Set(issues
                .filter(({ table }) => table === filters.table.val)
                .map(({ column }) => column)
            )]
            .sort()
            .map(value => ({ label: value, value }))
        )),
        type: [ ...new Set(issues.map(({ type }) => type)) ]
            .sort()
            .map(value => ({ label: value, value })),
        status: [ 'Definite', 'Failed', 'Likely', 'Possible', 'Warning', 'Potential PII' ]
            .map(value => ({ 
                label: div({ class: 'flex-row fx-gap-2' }, dot({}, statusColors[value]), span(value)),
                value,
            })),
    };

    const displayedFilters = [ 'type', 'status' ];
    if (category !== 'column_name') {
        displayedFilters.unshift('column');
    }
    if (!['table_name', 'column_name'].includes(category)) {
        displayedFilters.unshift('table');
    }

    return div(
        { class: 'flex-row fx-flex-wrap fx-gap-3 fx-align-flex-end mb-4' },
        displayedFilters.map(key => Select({
            id: `score-issues-${key}`,
            label: SCORE_LABEL[key],
            height: 32,
            style: 'font-size: 14px;',
            value: filters[key],
            options: filterOptions[key],
            allowNull: true,
            disabled: () => key === 'column' ? !filters.table.val : false,
            onChange: v => filters[key].val = v,
        })),
    );
};

/**
 *
 * @param {object} row
 * @param {string} column
 * @returns {<string>}
 */
const TableCell = (row, column) => {
    const componentByColumn = {
        column: IssueColumnCell,
        type: IssueCell,
        status: StatusCell,
        detail: DetailCell,
        time: TimeCell,
    };

    if (componentByColumn[column]) {
        return componentByColumn[column](row[column], row);
    }

    const size = { ...BREAKDOWN_COLUMNS_SIZES, ...ISSUES_COLUMNS_SIZES}[column];
    return div(
        { style: `flex: 0 0 ${size}; max-width: ${size}; word-wrap: break-word;` },
        span(row[column]),
    );
};

const IssueColumnCell = (value, row) => {
    const size = ISSUES_COLUMNS_SIZES.column;
    return div(
        { class: 'flex-column', style: `flex: 0 0 ${size}; max-width: ${size}; word-wrap: break-word;` },
        Caption({ content: row.table, style: 'font-size: 12px;' }),
        span(value),
    );
};


const IssueCell = (value, row) => {
    return div(
        { class: 'flex-column', style: `flex: 0 0 ${ISSUES_COLUMNS_SIZES.type}` },
        Caption({ content: `${row.issue_type} issue`, style: 'font-size: 12px; text-transform: capitalize;' }),
        span(value),
    );
};

const StatusCell = (value, row) => {
    return div(
        { class: 'flex-row fx-align-flex-center', style: `flex: 0 0 ${ISSUES_COLUMNS_SIZES.status}` },
        dot({ class: 'mr-2' }, statusColors[value]),
        span({}, value),
    );
};

const DetailCell = (value, row) => {
    return div(
        { style: `flex: 1 1 ${ISSUES_COLUMNS_SIZES.detail}` },
        span(value),
    );
};

const TimeCell = (value, row) => {
    return div(
        { class: 'flex-column', style: `flex: 0 0 ${ISSUES_COLUMNS_SIZES.time}` },
        row.issue_type === 'test'
            ? Caption({ content: row.name, style: 'font-size: 12px;' })
            : '',
        Link({
            label: formatTimestamp(value),
            open_new: true,
            href: row.issue_type === 'test' ? 'test-runs:results' : 'profiling-runs:hygiene',
            params: {
                run_id: row.run_id,
                table_name: row.table,
                column_name: row.column,
                selected: row.id,
            },
        }),
    );
};

const SCORE_LABEL = {
    table: 'Table',
    column: 'Column',
    type: 'Issue Type',
    status: 'Likelihood / Status',
};

const COLUMN_LABEL = {
    table_name: 'Table',
    column_name: 'Table > Column',
    semantic_data_type: 'Semantic Data Type',
    dq_dimension: 'Quality Dimension',
};

const ISSUES_COLUMN_LABEL = {
    column: 'Table | Column',
    type: 'Issue Type',
    status: 'Likelihood / Status',
    detail: 'Detail',
    time: 'Test Suite | Start Time',
};

const ISSUES_COLUMNS_SIZES = {
    column: '30%',
    type: '20%',
    status: '10%',
    detail: '30%',
    time: '10%',
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`

.issues-nav {
    margin-left: -4px;
    margin-bottom: 8px;
}

.issues-header {
    border-bottom: unset;
    text-transform: unset;
    font-size: 16px;
    font-weight: 500;
    line-height: 25px;
}

.issues-columns {
    text-transform: capitalize;
}

.issues-columns > span,
.issues-row > div {
    padding: 0 4px;
}
`);

export { IssuesTable };
