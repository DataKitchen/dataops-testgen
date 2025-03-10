/**
 * @import { Score } from '../components/score_card.js';
 * 
 * @typedef ProjectSummary
 * @type {object}
 * @property {number} connections_count
 * @property {string} default_connection_id
 * @property {number} table_groups_count
 * @property {number} profiling_runs_count
 * 
 * @typedef Category
 * @type {object}
 * @property {string} label
 * @property {number} score
 * 
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {Array<Score>} scores
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Input } from '../components/input.js';
import { Select } from '../components/select.js';
import { Link } from '../components/link.js';
import { Button } from '../components/button.js';
import { ScoreCard } from '../components/score_card.js';
import { ScoreLegend } from '../components/score_legend.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '../components/empty_state.js';

const { div, span } = van.tags;

const QualityDashboard = (/** @type {Properties} */ props) => {
    window.testgen.isPage = true;

    loadStylesheet('quality-dashboard', stylesheet);
    Streamlit.setFrameHeight(1);

    const domId = 'score-dashboard-page';
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    const sortedBy = van.state('name');
    const filterTerm = van.state('');
    const scores = van.derive(() => {
        const sort = getValue(sortedBy) ?? 'name';
        const filter = getValue(filterTerm) ?? '';
        return getValue(props.scores)
            .filter(score => score.name.toLowerCase().includes(filter.toLowerCase()))
            .sort((a, b) => a[sort] > b[sort] ? 1 : (b[sort] > a[sort] ? -1 : 0));
    });

    return div(
        { id: domId, style: 'overflow-y: auto;' },
        () => getValue(props.scores).length > 0
            ? div(
                ScoreLegend(),
                Toolbar(
                    {
                        onsearch: v => filterTerm.val = v,
                        onsort: v => sortedBy.val = v,
                    },
                    filterTerm,
                    sortedBy,
                ),
                () =>  div(
                    { class: 'flex-row fx-flex-wrap fx-gap-4' },
                    getValue(scores).map(score => ScoreCard(
                        score,
                        Link({
                            label: 'View details',
                            right_icon: 'chevron_right',
                            href: 'quality-dashboard:score-details',
                            class: 'ml-4',
                            params: { definition_id: score.id },
                        }),
                        {showHistory: true},
                    ))
                ),
            ) : ConditionalEmptyState(getValue(props.project_summary)),
    );
};

const Toolbar = (options, /** @type {string} */ filterBy, /** @type {string} */ sortedBy) => {
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
            onChange: options?.onsearch,
        }),
        Select({
            id: 'score-dashboard-sort',
            label: 'Sort by',
            height: 38,
            style: 'font-size: 14px;',
            value: sortedBy,
            options: sortOptions,
            onChange: options?.onsort,
        }),
        span({ style: 'margin: 0 auto;' }),
        Button({
            type: 'stroked',
            icon: 'data_exploration',
            label: 'Score Explorer',
            color: 'primary',
            style: 'background: var(--button-generic-background-color); width: unset; margin-right: 16px;',
            onclick: () => emitEvent('LinkClicked', { href: 'quality-dashboard:explorer' }),
        }),
        Button({
            type: 'icon',
            icon: 'refresh',
            tooltip: 'Refresh page data',
            tooltipPosition: 'left',
            style: 'border: var(--button-stroked-border); border-radius: 4px;',
            onclick: () => emitEvent('RefreshData', {}),
        }),
    );
};

const ConditionalEmptyState = (/** @type ProjectSummary */ projectSummary) => {
    let args = {
        message: EMPTY_STATE_MESSAGE.score,
        link: {
            label: 'Score Explorer',
            href: 'quality-dashboard:explorer',
        },
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