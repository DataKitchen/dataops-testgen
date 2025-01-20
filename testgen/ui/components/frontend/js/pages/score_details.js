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
import { ScoreCard } from '../components/score_card.js';
import { ScoreLegend } from '../components/score_legend.js';
import { ScoreBreakdown } from '../components/score_breakdown.js';
import { IssuesTable } from '../components/score_issues.js';

const { div } = van.tags;

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
            return (
                (getValue(props.issues) && getValue(props.drilldown))
                ? IssuesTable(
                    props.score,
                    props.issues,
                    props.category,
                    props.score_type,
                    props.drilldown,
                    (project_code, name, score_type, category) => emitEvent('LinkClicked', { href: 'quality-dashboard:score-details', params: { project_code, name, score_type, category } }),
                )
                : ScoreBreakdown(
                    props.score,
                    props.breakdown,
                    props.category,
                    props.score_type,
                    (project_code, name, score_type, category, drilldown) => emitEvent(
                        'LinkClicked',
                        { href: 'quality-dashboard:score-details', params: { project_code, name, score_type, category, drilldown }
                    }),
                )
            );
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-score-details {
    min-height: 400px;
}
`);

export { ScoreDetails };