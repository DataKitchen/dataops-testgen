/**
 * @typedef Dimension
 * @type {object}
 * @property {string} label
 * @property {number} score
 * 
 * @typedef Score
 * @type {object}
 * @property {string} project_code
 * @property {string} name
 * @property {number} score
 * @property {number?} cde_score
 * @property {Array<Dimension>} dimensions
 * 
 * @typedef ResultSet
 * @type {object}
 * @property {Array<string>} columns
 * @property {Array<object>} items
 * 
 * @typedef Properties
 * @type {object}
 * @property {('table_name' | 'column_name' | 'semantic_data_type' | 'dq_dimension')} category
 * @property {('score' | 'cde_score')} score_type
 * @property {any} drilldown
 * @property {Score} score
 * @property {ResultSet?} breakdown
 * @property {ResultSet?} issues
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { Select } from '../components/select.js';
import { ScoreCard } from '../components/score_card.js';
import { getScoreColor } from '../score_utils.js';
import { dot } from '../components/dot.js';
import { Link } from '../components/link.js';
import { Caption } from '../components/caption.js';

const { div, i, span } = van.tags;
const CATEGORY_LABEL = {
    table_name: 'Tables',
    column_name: 'Columns',
    semantic_data_type: 'Semantic Data Types',
    dq_dimension: 'Quality Dimensions',
};
const SCORE_TYPE_LABEL = {
    score: 'Total Score',
    cde_score: 'CDE Score',
};
const BREAKDOWN_COLUMN_LABEL = {
    table_name: 'Table',
    column_name: 'Column',
    semantic_data_type: 'Semantic Data Type',
    dq_dimension: 'Quality Dimension',
    impact: '',
    score: 'Individual Score',
    issue_ct: 'Issue Count',
};
const ISSUES_COLUMN_LABEL = {
    type: 'Issue',
    status: 'Likelihood / Status',
    detail: 'Detail',
    time: 'Test Suite | Start Time',
};
const ISSUES_COLUMNS_SIZES = {
    type: '30%',
    status: '15%',
    detail: '40%',
    time: '15%',
};

const ScoreDetails = (/** @type {Properties} */ props) => {
    window.testgen.isPage = true;

    loadStylesheet('score-details', stylesheet);
    Streamlit.setFrameHeight(1);

    const domId = 'score-details-page';

    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId, class: 'tg-score-details flex-column' },
        div(
            { class: 'flex-row mb-4'},
            () => ScoreCard(getValue(props.score)),
        ),
        () => {
            const drilldown = getValue(props.drilldown);
            const score = getValue(props.score);
            const issues = getValue(props.issues);
            const category = getValue(props.category);
            const scoreType = getValue(props.score_type);

            return (
                (issues && drilldown)
                ? IssuesTable(score, issues, category, scoreType, drilldown)
                : BreakdownTable(score, getValue(props.breakdown), category, scoreType)
            );
        },
        div(
            { class: 'flex-row fx-gap-2 mt-4' },
            span({ class: 'fx-flex' }),
            LegendItem('N/A', NaN),
            LegendItem('0-85', 0),
            LegendItem('86-90', 86),
            LegendItem('91-95', 91),
            LegendItem('96-100', 96),
        ),
    );
};

const BreakdownTable = (score, breakdown, category, scoreType) => {
    return div(
        { class: 'table' },
        div(
            { class: 'tg-score-details--controls table-header flex-row fx-align-flex-center fx-gap-2' },
            span('Score breakdown by'),
            () => Select({
                label: '',
                options:  ['table_name', 'column_name', 'semantic_data_type', 'dq_dimension'].map((c) => ({ label: CATEGORY_LABEL[c], value: c, selected: c === category })),
                onChange: (value) => emitEvent('CategoryChanged', { payload: value }),
            }),
            // span('on'),
            // () => Select({
            //     label: '',
            //     options: ['score', 'cde_score'].map((s) => ({ label: SCORE_TYPE_LABEL[s], value: s, selected: s === scoreType })),
            //     onChange: (value) => emitEvent('ScoreTypeChanged', { payload: value }),
            // }),
        ),
        () => div(
            { class: 'table-header table-header--columns flex-row' },
            getReadableColumns(breakdown.columns, scoreType).map((columnName) => span(
                { style: 'flex: 1;' },
                columnName,
            )),
        ),
        () => {
            const columns = breakdown.columns;
            return div(
                getValue(breakdown.items).map((row) => div(
                    { class: 'table-row flex-row' },
                    columns.map((columnName) => TableCell(row, columnName, score, category, scoreType)),
                )),
            );
        },
    );
};

/**
 * Translate the column names for the table.
 * 
 * @param {Array<string>} columns
 * @param {('table_name' | 'column_name' | 'semantic_data_type' | 'dq_dimension')} category
 * @param {('score' | 'cde_score')} scoreType
 * @returns {<string>}
 */
function getReadableColumns(columns, scoreType) {
    const translatedColumns = [];
    for (const column of columns) {
        translatedColumns.push(column === 'impact' ? `Impact on ${SCORE_TYPE_LABEL[scoreType]}` : BREAKDOWN_COLUMN_LABEL[column]);
    }
    return translatedColumns;
}

const IssuesTable = (score, issues, category, scoreType, drilldown) => {
    return div(
        { class: 'table' },
        div(
            { class: 'tg-score-details--issues-nav table-header' },
            Link({
                label: 'Back to score breakdown',
                left_icon: 'chevron_left',
                href: 'score-dashboard:details',
                params: { project_code: score.project_code, name: score.name, score_type: scoreType, category },
            }),
        ),
        () => div(
            { class: 'tg-score-details--issues-header table-header flex-row fx-align-flex-center fx-gap-1' },
            span(`Hygiene / Test Issues (${issues.items.length}) for`),
            span({ class: 'text-primary' }, `${BREAKDOWN_COLUMN_LABEL[category]}: ${drilldown.replace('.', ' > ')}`),
        ),
        () => div(
            { class: 'table-header table-header--columns flex-row' },
            issues.columns.map(c => span({ style: `flex: ${ISSUES_COLUMNS_SIZES[c]};` }, ISSUES_COLUMN_LABEL[c]))
        ),
        () => {
            const columns = issues.columns;
            return div(
                issues.items.map((row) => div(
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
const TableCell = (row, column, score=undefined, category=undefined, scoreType=undefined) => {
    const componentByColumn = {
        impact: ImpactCell,
        score: ScoreCell,
        issue_ct: IssueCountCell,
        type: IssueCell,
        status: StatusCell,
        detail: DetailCell,
        time: TimeCell,
    };

    if (componentByColumn[column]) {
        return componentByColumn[column](row[column], row, score, category, scoreType);
    }

    return div(
        { style: 'flex: 1' },
        span(row[column]),
    );
};

const ImpactCell = (value) => {
    return div(
        { class: 'flex-row', style: 'flex: 1' },
        Number(value) > 0
        ? i(
            {class: 'material-symbols-rounded', style: 'font-size: 20px; color: #E57373;'},
            'arrow_downward_alt',
        )
        : '',
        span(value ?? '-'),
    );
};

const ScoreCell = (value) => {
    return div(
        { class: 'flex-row', style: 'flex: 1' },
        dot({ class: 'mr-2' }, getScoreColor(value)),
        span(value),
    );
};

const IssueCountCell = (value, row, score, category, scoreType) => {
    let drilldown = row[category];
    if (category === 'column_name') {
        drilldown = `${row.table_name}.${row.column_name}`;
    }

    return div(
        { class: 'flex-row', style: 'flex: 1' },
        span({ class: 'mr-4' }, value ?? '-'),
        Link({
            label: 'View',
            right_icon: 'chevron_right',
            href: 'score-dashboard:details',
            params: { project_code: score.project_code, name: score.name, score_type: scoreType, category, drilldown },
        }),
    );
};

const IssueCell = (value, row) => {
    return div(
        { class: 'flex-column', style: `flex: ${ISSUES_COLUMNS_SIZES.type}` },
        Caption({ content: row.category, style: 'font-size: 12px;' }),
        span(value),
    );
};

const StatusCell = (value, row) => {
    const colorMap = {
        'Potential PII': '#EF5350',
        Likely: '#FF9800',
        Possible: '#FDD835',
        Definite: '#EF5350',
        Warning: '#FDD835',
        Failed: '#EF5350',
        Passed: '#9CCC65',
    };

    return div(
        { class: 'flex-row fx-align-flex-center', style: `flex: ${ISSUES_COLUMNS_SIZES.status}` },
        dot({ class: 'mr-2' }, colorMap[value]),
        span({}, value),
    );
};

const DetailCell = (value, row) => {
    return div(
        { style: `flex: ${ISSUES_COLUMNS_SIZES.detail}` },
        span(value),
    );
};

const TimeCell = (value, row) => {
    return div(
        { class: 'flex-column', style: `flex: ${ISSUES_COLUMNS_SIZES.time}` },
        row.issue_type === 'test'
            ? Caption({ content: row.name, style: 'font-size: 12px;' })
            : '',
        Link({
            label: formatTimestamp(value),
            href: row.issue_type === 'test' ? 'test-runs:results' : 'profiling-runs:hygiene',
            params: { run_id: row.run_id },
        }),
    );
};

const LegendItem = (label, value) => {
    return div(
        { class: 'flex-row fx-align-flex-center' },
        dot({ class: 'mr-2' }, getScoreColor(value)),
        span({}, label),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-score-details {
    min-height: 400px;
}

.tg-score-details--controls,
.tg-score-details--issues-header {
    border-bottom: unset;
    text-transform: unset;
    font-size: 16px;
    font-weight: 500;
    line-height: 25px;
    margin-bottom: 8px;
}

.table-header--columns {
    text-transform: capitalize;
}

.tg-score-details--issues-nav {
    border-bottom: unset;
    text-transform: unset;
    font-size: 14px;
    padding: unset;
    margin-left: -4px;
    margin-bottom: 8px;
}
`);

export { ScoreDetails };