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
        { class: 'table', 'data-testid': 'score-breakdown' },
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
                        options:  Object.entries(CATEGORIES)
                            .sort((A, B) => A[1].localeCompare(B[1]))
                            .map(([value, label]) => ({ value, label })),
                        onChange: (value) => emitEvent('CategoryChanged', { payload: value }),
                        testId: 'groupby-selector',
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
                        testId: 'score-type-selector',
                    });
                },
            ),
            () => ['table_name', 'column_name'].includes(getValue(category)) ? span('* Top 100 values by impact') : '',
        ),
        () => div(
            { class: 'table-header breakdown-columns flex-row' },
            getValue(breakdown)?.columns?.map(column => span({
                style: `flex: ${BREAKDOWN_COLUMNS_SIZES[column] ?? COLUMN_DEFAULT_SIZE};` },
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
                    { class: 'table-row flex-row', 'data-testid': 'score-breakdown-row' },
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

    const size = BREAKDOWN_COLUMNS_SIZES[column] ?? COLUMN_DEFAULT_SIZE;
    return div(
        { style: `flex: ${size}; max-width: ${size}; word-wrap: break-word;`, 'data-testid': 'score-breakdown-cell' },
        span(row[column] ?? '-'),
    );
};

const BreakdownColumnCell = (value, row) => {
    const size = COLUMN_DEFAULT_SIZE;
    return div(
        { class: 'flex-column', style: `flex: ${size}; max-width: ${size}; word-wrap: break-word;`, 'data-testid': 'score-breakdown-cell' },
        Caption({ content: row.table_name, style: 'font-size: 12px;' }),
        span(value),
    );
};

const ImpactCell = (value) => {
    return div(
        { class: 'flex-row', style: `flex: ${BREAKDOWN_COLUMNS_SIZES.impact}`, 'data-testid': 'score-breakdown-cell' },
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
        { class: 'flex-row', style: `flex: ${BREAKDOWN_COLUMNS_SIZES.score}`, 'data-testid': 'score-breakdown-cell' },
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
        { class: 'flex-row', style: `flex: ${BREAKDOWN_COLUMNS_SIZES.issue_ct}`, 'data-testid': 'score-breakdown-cell' },
        span({ class: 'mr-2', style: 'min-width: 40px;' }, value || '-'),
        (value && onViewDetails)
        ? div(
            {
                class: 'flex-row clickable',
                style: 'color: var(--link-color);',
                'data-testid': 'view-issues',
                onclick: () => onViewDetails(score.project_code, score.name, scoreType, category, drilldown),
            },
            span('View'),
            i({class: 'material-symbols-rounded', style: 'font-size: 20px;'}, 'chevron_right'),
        )
        : '',
    );
};

const CATEGORIES = {
    table_name: 'Tables',
    column_name: 'Columns',
    semantic_data_type: 'Semantic Data Types',
    dq_dimension: 'Quality Dimensions',
    table_groups_name: 'Table Group',
    data_location: 'Data Location',
    data_source: 'Data Source',
    source_system: 'Source System',
    source_process: 'Source Process',
    business_domain: 'Business Domain',
    stakeholder_group: 'Stakeholder Group',
    transform_level: 'Transform Level',
    data_product: 'Data Product',
};

const BREAKDOWN_COLUMN_LABEL = {
    ...CATEGORIES,
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

const COLUMN_DEFAULT_SIZE = '40%';
const BREAKDOWN_COLUMNS_SIZES = {
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
