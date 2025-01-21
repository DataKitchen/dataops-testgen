import van from '../van.min.js';
import { Link } from '../components/link.js';
import { Caption } from '../components/caption.js';
import { dot } from '../components/dot.js';
import { getValue, loadStylesheet } from '../utils.js';
import { colorMap, formatTimestamp } from '../display_utils.js';

const { div, i, span } = van.tags;

const IssuesTable = (score, issues, category, scoreType, drilldown, onBack) => {
    loadStylesheet('score-issues-table', stylesheet);

    return div(
        { class: 'table' },
        div(
            { class: 'issues-nav table-header' },
            () => {
                const scoreValue = getValue(score);
                const scoreTypeValue = getValue(scoreType);
                const categoryValue = getValue(category);

                return div(
                    {
                        class: 'flex-row clickable',
                        style: 'color: var(--link-color);',
                        onclick: () => onBack(scoreValue.project_code, scoreValue.name, scoreTypeValue, categoryValue),
                    },
                    i({class: 'material-symbols-rounded', style: 'font-size: 20px;'}, 'chevron_left'),
                    span('Back'),
                );
            }
        ),
        () => div(
            { class: 'issues-header table-header flex-row fx-align-flex-center fx-gap-1' },
            span(`Hygiene / Test Issues (${getValue(issues)?.items?.length ?? 0}) for`),
            span({ class: 'text-primary' }, `${COLUMN_LABEL[getValue(category)] ?? '-'}: ${getValue(drilldown)?.replace('.', ' > ')}`),
        ),
        () => div(
            { class: 'table-header issues-columns flex-row' },
            getValue(issues)?.columns.map(c => span({ style: `flex: ${ISSUES_COLUMNS_SIZES[c]};` }, ISSUES_COLUMN_LABEL[c]))
        ),
        () => {
            const issuesValue = getValue(issues);
            const columns = issuesValue?.columns;
            return div(
                issuesValue?.items.map((row) => div(
                    { class: 'table-row flex-row' },
                    columns.map((columnName) => TableCell(row, columnName)),
                )),
            );
        },
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
    border-bottom: unset;
    text-transform: unset;
    font-size: 14px;
    padding: unset;
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
`);

export { IssuesTable };