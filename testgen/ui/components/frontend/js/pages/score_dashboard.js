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
 * @property {number} cde_score
 * @property {Array<Dimension>} dimensions
 * 
 * @typedef Properties
 * @type {object}
 * @property {Array<Score>} scores
 * @property {string} filter_term
 * @property {string} sorted_by
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { getScoreColor } from '../score_utils.js';
import { Input } from '../components/input.js';
import { Select } from '../components/select.js';
import { Link } from '../components/link.js';
import { dot } from '../components/dot.js';
import { ScoreCard } from '../components/score_card.js';

const { div, span } = van.tags;

const ScoreDashboard = (/** @type {Properties} */ props) => {
    window.testgen.isPage = true;

    loadStylesheet('score-dashboard', stylesheet);
    Streamlit.setFrameHeight(1);

    const domId = 'score-dashboard-page';
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId },
        () => Toolbar(getValue(props.filter_term), getValue(props.sorted_by)),
        () =>  div(
            { class: 'flex-row fx-flex-wrap fx-gap-4' },
            getValue(props.scores).map(score => ScoreCard(
                score,
                    Link({
                    label: 'View details',
                    right_icon: 'chevron_right',
                    href: 'score-dashboard:details',
                    params: { project_code: score.project_code, name: score.name },
                })
            ))
        ),
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

const Toolbar = (/** @type {string} */ filterBy, /** @type {string} */ sortedBy) => {
    const sortOptions = [
        { label: "Score Name", value: "name" },
        { label: "Lowest Score", value: "score" },
    ];

    return div(
        { class: 'flex-row fx-align-flex-end mb-4' },
        Input({
            width: 230,
            height: 38,
            style: 'font-size: 14px; margin-right: 16px;',
            icon: 'search',
            clearable: true,
            placeholder: 'Search scores',
            value: filterBy,
            onChange: (value) => emitEvent('ScoresFiltered', { payload: value }),
        }),
        Select({
            id: 'score-dashboard-sort',
            label: 'Sort by',
            height: 38,
            style: 'font-size: 14px;',
            options: sortOptions.map(option => ({...option, selected: option.value === sortedBy})),
            onChange: (value) => emitEvent('ScoresSorted', { payload: value }),
        })
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
stylesheet.replace('');

export { ScoreDashboard };