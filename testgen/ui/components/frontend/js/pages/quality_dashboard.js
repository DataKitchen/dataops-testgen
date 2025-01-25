/**
 * @typedef ProjectSummary
 * @type {object}
 * @property {number} connections_count
 * @property {string} default_connection_id
 * @property {number} table_groups_count
 * @property {number} profiling_runs_count
 * 
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
 * @property {number} profiling_score
 * @property {number} testing_score
 * @property {number} cde_score
 * @property {Array<Dimension>} dimensions
 * 
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {Array<Score>} scores
 * @property {string} filter_term
 * @property {string} sorted_by
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Input } from '../components/input.js';
import { Select } from '../components/select.js';
import { Link } from '../components/link.js';
import { ScoreCard } from '../components/score_card.js';
import { ScoreLegend } from '../components/score_legend.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '../components/empty_state.js';

const { div } = van.tags;

const QualityDashboard = (/** @type {Properties} */ props) => {
    window.testgen.isPage = true;

    loadStylesheet('quality-dashboard', stylesheet);
    Streamlit.setFrameHeight(1);

    const domId = 'score-dashboard-page';
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId, style: 'overflow-y: auto;' },
        () => (getValue(props.scores).length || getValue(props.filter_term))
            ? div(
                ScoreLegend('margin-bottom: -16px;'),
                () => Toolbar(getValue(props.filter_term), getValue(props.sorted_by)),
                () =>  div(
                    { class: 'flex-row fx-flex-wrap fx-gap-4' },
                    getValue(props.scores).map(score => ScoreCard(
                        score,
                        Link({
                            label: 'View details',
                            right_icon: 'chevron_right',
                            href: 'quality-dashboard:score-details',
                            params: { project_code: score.project_code, name: score.name },
                        })
                    ))
                ),
            ) : ConditionalEmptyState(getValue(props.project_summary)),
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

const ConditionalEmptyState = (/** @type ProjectSummary */ projectSummary) => {
    let args = {
        message: EMPTY_STATE_MESSAGE.score,
        // link: {
        //     label: 'Score Explorer',
        //     href: '',
        // },
    };

    if (projectSummary.connections_count <= 0) {
        args = {
            message: EMPTY_STATE_MESSAGE.connection,
            link: {
                label: 'Go to Connections',
                href: 'connections',
            },
        };
    } else if (projectSummary.profiling_runs_count <= 0) {
        args = {
            message: projectSummary.table_groups_count ? EMPTY_STATE_MESSAGE.profiling : EMPTY_STATE_MESSAGE.tableGroup,
            link: {
                label: 'Go to Table Groups',
                href: 'connections:table-groups',
                params: { connection_id: projectSummary.default_connection_id },
            },
        };
    }

    return EmptyState({
        icon: 'readiness_score',
        label: 'No scores yet',
        ...args,
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace('');

export { QualityDashboard };