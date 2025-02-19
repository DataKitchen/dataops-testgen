/**
 * @typedef Score
 * @type {object}
 * @property {string} project_code
 * @property {string} name
 * @property {number} score
 * @property {number} profiling_score
 * @property {number} testing_score
 * @property {number} cde_score
 * @property {Array<Dimension>} categories
 */
import van from '../van.min.js';
import { Card } from './card.js';
import { dot } from './dot.js';
import { Attribute } from './attribute.js';
import { getScoreColor } from '../score_utils.js';
import { getValue, loadStylesheet } from '../utils.js';

const { div, i, span } = van.tags;
const { circle, svg, text } = van.tags("http://www.w3.org/2000/svg");

const ScoreCard = (
    /** @type {Score} */ score,
    /** @type {(Function|Array|any|undefined)}*/ actions,
) => {
    loadStylesheet('score-card', stylesheet);

    const title = van.derive(() => getValue(score)?.name ?? '');

    return Card({
        title: title,
        actionContent: actions,
        class: 'tg-score-card',
        content: () => {
            const score_ = getValue(score);
            const categories = score_.dimensions ?? score_.categories ?? [];
            const categoriesLabel = score_.categories_label ?? 'Quality Dimension';

            return div(
                { class: 'flex-row fx-justify-center fx-align-flex-start' },
                score_.score ? div(
                    { class: 'mr-4' },
                    ScoreChart("Total Score", score_.score),
                    div(
                        { class: 'flex-row fx-justify-center fx-gap-2 mt-1' },
                        Attribute({ label: 'Profiling', value: score_.profiling_score }),
                        Attribute({ label: 'Testing', value: score_.testing_score }),
                    ),
                ) : '',
                score_.cde_score ? ScoreChart("CDE Score", score_.cde_score) : '',
                (score_.cde_score && categories.length > 0) ? i({ class: 'mr-4 ml-4' }) : '',
                categories.length > 0 ? div(
                    { class: 'flex-column' },
                    span({ class: 'mb-2 text-caption' }, categoriesLabel),
                    div(
                        { class: 'tg-score-card--categories' },
                        categories.map(category => div(
                            { class: 'flex-row fx-align-flex-center fx-gap-2' },
                            dot({}, getScoreColor(category.score)),
                            span({ class: 'tg-score-card--category-score' }, category.score ?? '--'),
                            span(
                                { class: 'tg-score-card--category-label', title: category.label, style: 'position: relative;' },
                                category.label,
                            ),
                        )),
                    ),
                ) : '',
            );
        },
    });
};

/**
 * Circle chart for displaying score.
 * 
 * @param {string} label
 * @param {number} score
 */
const ScoreChart = (label, score) => {
    const variables = {
        size: '100px',
        'stroke-width': '4px',
        color: getScoreColor(score),
        'half-size': 'calc(var(--size) / 2)',
        radius: 'calc((var(--size) - var(--stroke-width)) / 2)',
        circumference: 'calc(var(--radius) * pi * 2)',
        dash: `calc((${score ?? 100} * var(--circumference)) / 100)`,
    };
    const style = Object.entries(variables).map(([key, value]) => `--${key}: ${value}`).join(';');

    return svg(
        { class: 'tg-score-chart', width: "100", height: "100", viewBox: "0 0 100 100", style },
        circle({ class: 'tg-score-chart--bg' }),
        circle({ class: 'tg-score-chart--fg' }),
        text({ x: '50%', y: '40%', 'dominant-baseline': 'middle', 'text-anchor': 'middle', fill: 'var(--primary-text-color)', 'font-size': '18px', 'font-weight': 500 }, score ?? '-'),
        text({ x: '50%', y: '40%', 'dominant-baseline': 'middle', 'text-anchor': 'middle', fill: 'var(--secondary-text-color)', 'font-size': '14px', class: 'tg-score-chart--label' }, label),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-score-card {
    width: fit-content;
    box-sizing: border-box;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin-bottom: unset !important;
}

.tg-score-card--categories {
    max-height: 100px;
    overflow-y: auto;
    display: grid;
    grid-gap: 8px;
    grid-template-columns: 160px 160px;
}

.tg-score-card--category-score {
    min-width: 30px;
    font-weight: 500; 
}

.tg-score-card--category-label {
    display: block;
    overflow-x: hidden;
    text-wrap: nowrap;
    text-overflow: ellipsis;
}

svg.tg-score-chart circle {
    cx: var(--half-size);
    cy: var(--half-size);
    r: var(--radius);
    stroke-width: var(--stroke-width);
    fill: none;
    stroke-linecap: round;
}

svg.tg-score-chart circle.tg-score-chart--bg {
    stroke: var(--empty);
}

svg.tg-score-chart circle.tg-score-chart--fg {
    transform: rotate(-90deg);
    transform-origin: var(--half-size) var(--half-size);
    stroke-dasharray: var(--dash) calc(var(--circumference) - var(--dash));
    transition: stroke-dasharray 0.3s linear 0s;
    stroke: var(--color);
}

svg.tg-score-chart text.tg-score-chart--label {
    transform: translateY(20px);
}
`);

export { ScoreCard };
