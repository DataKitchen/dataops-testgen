/**
 * @import { Score } from '/app/static/js/components/score_card.js';
 * @import { ProjectSummary } from '../types.js';
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
import van from '/app/static/js/van.min.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { Input } from '/app/static/js/components/input.js';
import { Select } from '/app/static/js/components/select.js';
import { Link } from '/app/static/js/components/link.js';
import { Button } from '/app/static/js/components/button.js';
import { ScoreCard } from '/app/static/js/components/score_card.js';
import { ScoreLegend } from '/app/static/js/components/score_legend.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '/app/static/js/components/empty_state.js';
import { caseInsensitiveSort, caseInsensitiveIncludes } from '/app/static/js/display_utils.js';

const { div, span } = van.tags;

const QualityDashboard = (/** @type {Properties} */ props) => {
    const { emit } = props;
    loadStylesheet('quality-dashboard', stylesheet);

    const domId = 'score-dashboard-page';

    const sortedBy = van.state('name');
    const filterTerm = van.state('');

    const scoreToNumber = (score) => score ? (score.startsWith('>') ? 99.99 : Number(score)) : 101;
    const sortFunctions = {
        name: (a, b) => caseInsensitiveSort(a.name, b.name),
        score: (a, b) => {
            const scoreA = Math.min(scoreToNumber(a.score), scoreToNumber(a.cde_score));
            const scoreB = Math.min(scoreToNumber(b.score), scoreToNumber(b.cde_score));
            return scoreA - scoreB;
        },
    };

    const scores = van.derive(() => {
        const sort = getValue(sortedBy) ?? 'name';
        const filter = getValue(filterTerm) ?? '';
        return getValue(props.scores)
            .filter(score => caseInsensitiveIncludes(score.name, filter))
            .sort(sortFunctions[sort]);
    });

    return div(
        { id: domId, 'data-testid': 'quality-dashboard', style: 'overflow-y: auto;' },
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
                    getValue(props.project_summary),
                    emit,
                ),
                () => getValue(scores).length
                    ? div(
                        { class: 'flex-row fx-flex-wrap fx-gap-4' },
                        getValue(scores).map(score => ScoreCard(
                            score,
                            Link({ emit, 
                                label: 'View details',
                                right_icon: 'chevron_right',
                                href: 'quality-dashboard:score-details',
                                class: 'ml-4',
                                params: { definition_id: score.id, project_code: getValue(props.project_summary)?.project_code },
                            }),
                            {showHistory: true},
                        ))
                    )
                    : div(
                        { class: 'mt-7 text-secondary', style: 'text-align: center;' },
                        'No scorecards found matching filters',
                    ),
            ) : ConditionalEmptyState(getValue(props.project_summary), emit),
    );
};

const Toolbar = (
    options,
    /** @type {string} */ filterBy,
    /** @type {string} */ sortedBy,
    /** @type ProjectSummary */ projectSummary,
    emit,
) => {
    const sortOptions = [
        { label: "Scorecard Name", value: "name" },
        { label: "Lowest Score", value: "score" },
    ];

    return div(
        { class: 'flex-row fx-align-flex-end fx-gap-3 mb-4' },
        Input({
            width: 230,
            icon: 'search',
            clearable: true,
            placeholder: 'Search scorecards',
            value: filterBy,
            onChange: options?.onsearch,
            testId: 'scorecards-filter',
        }),
        Select({
            id: 'score-dashboard-sort',
            label: 'Sort by',
            style: 'font-size: 14px;',
            value: sortedBy,
            options: sortOptions,
            onChange: options?.onsort,
            testId: 'scorecards-sort',
        }),
        span({ style: 'margin: 0 auto;' }),
        Button({
            type: 'stroked',
            icon: 'data_exploration',
            label: 'Score Explorer',
            color: 'primary',
            style: 'background: var(--button-generic-background-color); width: unset;',
            onclick: () => emit('LinkClicked', {
                href: 'quality-dashboard:explorer',
                params: { project_code: projectSummary.project_code },
                testId: 'scorecards-goto-explorer',
            }),
        }),
        Button({
            type: 'stroked',
            icon: 'refresh',
            tooltip: 'Refresh page data',
            tooltipPosition: 'left',
            style: 'background: var(--button-generic-background-color);',
            onclick: () => emit('RefreshData', {}),
            testId: 'scorecards-refresh',
        }),
    );
};

const ConditionalEmptyState = (/** @type ProjectSummary */ projectSummary, emit) => {
    let args = {
        message: EMPTY_STATE_MESSAGE.score,
        link: {
            label: 'Score Explorer',
            href: 'quality-dashboard:explorer',
            params: { project_code: projectSummary.project_code },
        },
    };

    if (projectSummary.connection_count <= 0) {
        args = {
            message: EMPTY_STATE_MESSAGE.connection,
            link: {
                label: 'Go to Connections',
                href: 'connections',
                params: { project_code: projectSummary.project_code },
            },
        };
    } else if (projectSummary.profiling_run_count <= 0) {
        args = {
            message: projectSummary.table_group_count ? EMPTY_STATE_MESSAGE.profiling : EMPTY_STATE_MESSAGE.tableGroup,
            link: {
                label: 'Go to Table Groups',
                href: 'table-groups',
                params: { project_code: projectSummary.project_code, connection_id: projectSummary.default_connection_id },
            },
        };
    }

    return EmptyState({ emit, 
        icon: 'readiness_score',
        label: 'No scores yet',
        ...args,
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace('');

export { QualityDashboard };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, QualityDashboard(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
