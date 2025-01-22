/**
 * @typedef Issue
 * @type {object}
 * @property {string} id
 * @property {('profile' | 'test')} issue_type
 * @property {string} table
 * @property {string} column
 * @property {string} category
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
import { Paginator } from '../components/paginator.js';
import { emitEvent, loadStylesheet } from '../utils.js';
import { colorMap, formatTimestamp } from '../display_utils.js';

const { div, i, span } = van.tags;
const PAGE_SIZE = 100;
const SCROLL_CONTAINER = window.top.document.querySelector('.stAppViewMain');

const IssuesTable = (
    /** @type Issue[] */ issues,
    /** @type string[] */ columns,
    /** @type Score */ score,
    /** @type string */ scoreType,
    /** @type string */ category,
    /** @type string */ drilldown,
    /** @type function */ onBack,
) => {
    loadStylesheet('score-issues-table', stylesheet);

    const pageIndex = van.state(0);
    const pageIssues = van.derive(() => issues.slice(PAGE_SIZE * pageIndex.val, PAGE_SIZE * (pageIndex.val + 1)));
    const selectedIssues = van.state([]);

    return div(
        { class: 'table' },
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
                    span({ class: 'text-primary' }, `${COLUMN_LABEL[category] ?? '-'}: ${drilldown.replace('.', ' > ')}`),
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
        div(
            { class: 'table-header issues-columns flex-row' },
            Checkbox({
                width: 30,
                checked: () => selectedIssues.val.length === PAGE_SIZE,
                indeterminate: () => !!selectedIssues.val.length,
                onChange: (checked) => {
                    if (checked) {
                        selectedIssues.val = pageIssues.val.map(({ id, issue_type }) => ({ id, issue_type }));
                    } else {
                        selectedIssues.val = [];
                    }  
                },
            }),
            columns.map(c => span({ style: `flex: ${c === 'detail' ? '1 1' : '0 0'} ${ISSUES_COLUMNS_SIZES[c]};` }, ISSUES_COLUMN_LABEL[c]))
        ),
        () => div(
            pageIssues.val.map((row) => div(
                { class: 'table-row flex-row issues-row' },
                Checkbox({
                    width: 30,
                    checked: () => selectedIssues.val.map(({ id }) => id).includes(row.id),
                    onChange: (checked) => {
                        if (checked) {
                            selectedIssues.val = [ ...selectedIssues.val, { id: row.id, issue_type: row.issue_type } ];
                        } else {
                            selectedIssues.val = selectedIssues.val.filter(({ id }) => id !== row.id);
                        }
                    },
                }),
                columns.map((columnName) => TableCell(row, columnName)),
            )),
        ),
        Paginator({
            count: issues.length,
            pageSize: PAGE_SIZE,
            onChange: (newIndex) => {
                pageIndex.val = newIndex;
                SCROLL_CONTAINER.scrollTop = 0;
            },
        }),
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
        Caption({ content: row.category, style: 'font-size: 12px;' }),
        span(value),
    );
};

const StatusCell = (value, row) => {
    const statusColors = {
        'Potential PII': colorMap.grey,
        Likely: colorMap.orange,
        Possible: colorMap.yellow,
        Definite: colorMap.red,
        Warning: colorMap.yellow,
        Failed: colorMap.red,
        Passed: colorMap.green,
    };

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
            },
        }),
    );
};

const COLUMN_LABEL = {
    table_name: 'Table',
    column_name: 'Table > Column',
    semantic_data_type: 'Semantic Data Type',
    dq_dimension: 'Quality Dimension',
};

const ISSUES_COLUMN_LABEL = {
    column: 'Table | Column',
    type: 'Issue Type | Name',
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
    margin-bottom: 8px;
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