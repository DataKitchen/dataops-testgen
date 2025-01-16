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
import { colorMap, formatTimestamp } from '../display_utils.js';
import { Select } from '../components/select.js';
import { ScoreCard } from '../components/score_card.js';
import { getScoreColor } from '../score_utils.js';
import { dot } from '../components/dot.js';
import { Link } from '../components/link.js';
import { Caption } from '../components/caption.js';
import { ScoreLegend } from '../components/score_legend.js';

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
    column_name: 'Table | Column',
    semantic_data_type: 'Semantic Data Type',
    dq_dimension: 'Quality Dimension',
    impact: '',
    score: 'Individual Score',
    issue_ct: 'Issue Count',
};
const BREAKDOWN_COLUMNS_SIZES = {
    table_name: '40%',
    column_name: '40%',
    semantic_data_type: '40%',
    dq_dimension: '40%',
    impact: '20%',
    score: '20%',
    issue_ct: '20%',
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

const ScoreDetails = (/** @type {Properties} */ props) => {
    window.testgen.isPage = true;

    loadStylesheet('score-details', stylesheet);
    Streamlit.setFrameHeight(1);

    const domId = 'score-details-page';

    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId, class: 'tg-score-details flex-column' },
        ScoreLegend(),
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
    );
};

const BreakdownTable = (score, breakdown, category, scoreType) => {
    return div(
        { class: 'table' },
        div(
            { class: 'flex-row fx-justify-space-between fx-align-flex-start text-caption' },
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
            ['table_name', 'column_name'].includes(category) ? span('* Top 100 values by impact') : '',
        ),
        () => div(
            { class: 'table-header table-header--columns flex-row' },
            breakdown.columns.map(column => span({ 
                style: `flex: ${BREAKDOWN_COLUMNS_SIZES[column]};` },
                getReadableColumn(column),
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
function getReadableColumn(column, scoreType) {
    if (column === 'impact') {
        return `Impact on ${SCORE_TYPE_LABEL[scoreType]}`;
    }
    const label = BREAKDOWN_COLUMN_LABEL[column];
    if (['table_name', 'column_name'].includes(column)) {
        return `${label} *`;
    }
    return label;
}

const IssuesTable = (score, issues, category, scoreType, drilldown) => {
    return div(
        { class: 'table' },
        div(
            { class: 'tg-score-details--issues-nav table-header' },
            Link({
                label: 'Back to score breakdown',
                left_icon: 'chevron_left',
                href: 'quality-dashboard:score-details',
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
        column_name: BreakdownColumnCell,
        impact: ImpactCell,
        score: ScoreCell,
        issue_ct: IssueCountCell,
        column: IssueColumnCell,
        type: IssueCell,
        status: StatusCell,
        detail: DetailCell,
        time: TimeCell,
    };

    if (componentByColumn[column]) {
        return componentByColumn[column](row[column], row, score, category, scoreType);
    }

    const size = { ...BREAKDOWN_COLUMNS_SIZES, ...ISSUES_COLUMNS_SIZES}[column];
    return div(
        { style: `flex: ${size}; max-width: ${size}; word-wrap: break-word;` },
        span(row[column]),
    );
};

const BreakdownColumnCell = (value, row) => {
    const size = BREAKDOWN_COLUMNS_SIZES.column_name;
    return div(
        { class: 'flex-column', style: `flex: ${size}; max-width: ${size}; word-wrap: break-word;` },
        Caption({ content: row.table_name, style: 'font-size: 12px;' }),
        span(value),
    );
};

const ImpactCell = (value) => {
    return div(
        { class: 'flex-row', style: `flex: ${BREAKDOWN_COLUMNS_SIZES.impact}` },
        value && !String(value).startsWith('-')
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
        { class: 'flex-row', style: `flex: ${BREAKDOWN_COLUMNS_SIZES.score}` },
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
        { class: 'flex-row', style: `flex: ${BREAKDOWN_COLUMNS_SIZES.issue_ct}` },
        span({ class: 'mr-4' }, value || '-'),
        value ? Link({
            label: 'View',
            right_icon: 'chevron_right',
            href: 'quality-dashboard:score-details',
            params: { project_code: score.project_code, name: score.name, score_type: scoreType, category, drilldown },
        }) : '',
    );
};

const IssueColumnCell = (value, row) => {
    const size = ISSUES_COLUMNS_SIZES.column;
    return div(
        { class: 'flex-column', style: `flex: ${size}; max-width: ${size}; word-wrap: break-word;` },
        Caption({ content: row.table, style: 'font-size: 12px;' }),
        span(value),
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
        { class: 'flex-row fx-align-flex-center', style: `flex: ${ISSUES_COLUMNS_SIZES.status}` },
        dot({ class: 'mr-2' }, statusColors[value]),
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