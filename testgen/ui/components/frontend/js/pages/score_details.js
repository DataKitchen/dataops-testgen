/**
 * @import { Score } from '../components/score_card.js';
 *
 * @typedef Dimension
 * @type {object}
 * @property {string} label
 * @property {number} score
 *
 * @typedef ResultSet
 * @type {object}
 * @property {Array<string>} columns
 * @property {Array<object>} items
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {('table_name' | 'column_name' | 'semantic_data_type' | 'dq_dimension')} category
 * @property {('score' | 'cde_score')} score_type
 * @property {any} drilldown
 * @property {Score} score
 * @property {ResultSet?} breakdown
 * @property {ResultSet?} issues
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { ScoreCard } from '../components/score_card.js';
import { ScoreHistory } from '../components/score_history.js';
import { ScoreLegend } from '../components/score_legend.js';
import { ScoreBreakdown } from '../components/score_breakdown.js';
import { IssuesTable } from '../components/score_issues.js';
import { Button } from '../components/button.js';

const { div, i } = van.tags;

const ScoreDetails = (/** @type {Properties} */ props) => {
    window.testgen.isPage = true;

    loadStylesheet('score-details', stylesheet);
    Streamlit.setFrameHeight(1);

    const domId = 'score-details-page';
    const scoreId = getValue(props.score).id;
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;

    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId, class: 'tg-score-details flex-column' },
        ScoreLegend(),
        div(
            { class: 'flex-row fx-flex-wrap fx-gap-4 mb-4 mt-4'},
            ScoreCard(
                props.score,
                () => {
                    const score = getValue(props.score);
                    return userCanEdit ? div(
                        { class: 'flex-row tg-test-suites--card-actions' },
                        Button({ type: 'icon', icon: 'edit', tooltip: 'Edit Scorecard', onclick: () => emitEvent('LinkClicked', { href: 'quality-dashboard:explorer', params: { definition_id: score.id } }) }),
                        Button({ type: 'icon', icon: 'delete', tooltip: 'Delete Scorecard', onclick: () => emitEvent('DeleteScoreRequested', { payload: score.id }) }),
                    ) : '';
                },
            ),
            () => {
                const score = getValue(props.score);
                const history = getValue(props.score).history;
                return history?.length > 0
                    ? ScoreHistory({style: 'min-height: 216px; flex: 610px 0 1;', showRefresh: userCanEdit, score}, ...history)
                    : null;
            },
        ),
        () => {
            const issuesValue = getValue(props.issues);
            return (
                (issuesValue && getValue(props.drilldown))
                ? IssuesTable(
                    issuesValue?.items,
                    issuesValue?.columns,
                    getValue(props.score),
                    getValue(props.score_type),
                    getValue(props.category),
                    getValue(props.drilldown),
                    (project_code, name, score_type, category) => emitEvent('LinkClicked', { href: 'quality-dashboard:score-details', params: { definition_id: scoreId, score_type, category } }),
                )
                : ScoreBreakdown(
                    props.score,
                    props.breakdown,
                    props.category,
                    props.score_type,
                    (project_code, name, score_type, category, drilldown) => emitEvent(
                        'LinkClicked',
                        { href: 'quality-dashboard:score-details', params: { definition_id: scoreId, score_type, category, drilldown }
                    }),
                )
            );
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-score-details {
    min-height: 900px;
}
`);

export { ScoreDetails };
