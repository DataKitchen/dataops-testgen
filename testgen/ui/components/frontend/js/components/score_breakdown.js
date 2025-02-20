import van from '../van.min.js';
import { dot } from '../components/dot.js';
import { Caption } from '../components/caption.js';
import { Select } from '../components/select.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { getScoreColor } from '../score_utils.js';

const { div, i, span } = van.tags;

const ScoreBreakdown = (score, breakdown, category, scoreType, onViewDetails) => {
    loadStylesheet('score-breakdown', stylesheet);

    return div(
        { class: 'table' },
        div(
            { class: 'flex-row fx-justify-space-between fx-align-flex-start text-caption' },
            div(
                { class: 'breakdown-controls table-header flex-row fx-align-flex-center fx-gap-2' },
                span('Score grouped by'),
                () => {
                    const selectedCategory = getValue(category);
                    return Select({
                        label: '',
                        value: selectedCategory,
                        options:  ['table_name', 'column_name', 'semantic_data_type', 'dq_dimension'].map((c) => ({ label: CATEGORY_LABEL[c], value: c })),
                        onChange: (value) => emitEvent('CategoryChanged', { payload: value }),
                    });
                },
                span('for'),
                () => {
                    const scoreValue = getValue(score);
                    const selectedScoreType = getValue(scoreType);
                    const scoreTypeOptions = ['score', 'cde_score'].filter((s) => scoreValue[s])
                    if (!scoreTypeOptions.length) {
                        scoreTypeOptions.push('score');
                    }
                    return Select({
                        label: '',
                        value: selectedScoreType,
                        options: scoreTypeOptions.map((s) => ({ label: SCORE_TYPE_LABEL[s], value: s, selected: s === scoreType })),
                        onChange: (value) => emitEvent('ScoreTypeChanged', { payload: value }),
                    });
                },
            ),
            () => ['table_name', 'column_name'].includes(getValue(category)) ? span('* Top 100 values by impact') : '',
        ),
        () => div(
            { class: 'table-header breakdown-columns flex-row' },
            getValue(breakdown)?.columns?.map(column => span({
                style: `flex: ${BREAKDOWN_COLUMNS_SIZES[column]};` },
                getReadableColumn(column, getValue(scoreType)),
            )),
        ),
        () => {
            const scoreValue = getValue(score);
            const categoryValue = getValue(category);
            const scoreTypeValue = getValue(scoreType);
            const breakdownValue = getValue(breakdown);
            const columns = breakdownValue?.columns;
            return div(
                breakdownValue?.items?.map((row) => div(
                    { class: 'table-row flex-row' },
                    columns.map((columnName) => TableCell(row, columnName, scoreValue, categoryValue, scoreTypeValue, onViewDetails)),
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

/**
 *
 * @param {object} row
 * @param {string} column
 * @returns {<string>}
 */
const TableCell = (row, column, score=undefined, category=undefined, scoreType=undefined, onViewDetails=undefined) => {
    const componentByColumn = {
        column_name: BreakdownColumnCell,
        impact: ImpactCell,
        score: ScoreCell,
        issue_ct: IssueCountCell,
    };

    if (componentByColumn[column]) {
        return componentByColumn[column](row[column], row, score, category, scoreType, onViewDetails);
    }

    const size = BREAKDOWN_COLUMNS_SIZES[column];
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
        span(value ?? '--'),
    );
};

const IssueCountCell = (value, row, score, category, scoreType, onViewDetails) => {
    let drilldown = row[category];
    if (category === 'table_name') {
        drilldown = `${row.table_groups_id}.${row.table_name}`;
    } else if (category === 'column_name') {
        drilldown = `${row.table_groups_id}.${row.table_name}.${row.column_name}`;
    }

    return div(
        { class: 'flex-row', style: `flex: ${BREAKDOWN_COLUMNS_SIZES.issue_ct}` },
        span({ class: 'mr-2', style: 'min-width: 40px;' }, value || '-'),
        (value && onViewDetails)
        ? div(
            { class: 'flex-row clickable', style: 'color: var(--link-color);', onclick: () => onViewDetails(score.project_code, score.name, scoreType, category, drilldown) },
            span('View'),
            i({class: 'material-symbols-rounded', style: 'font-size: 20px;'}, 'chevron_right'),
        )
        : '',
    );
};

const CATEGORY_LABEL = {
    table_name: 'Tables',
    column_name: 'Columns',
    semantic_data_type: 'Semantic Data Types',
    dq_dimension: 'Quality Dimensions',
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

const SCORE_TYPE_LABEL = {
    score: 'Total Score',
    cde_score: 'CDE Score',
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

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.breakdown-controls {
    border-bottom: unset;
    text-transform: unset;
    font-size: 16px;
    font-weight: 500;
    line-height: 25px;
    margin-bottom: 8px;
}

.breakdown-columns {
    text-transform: capitalize;
}
`);

export { ScoreBreakdown };
