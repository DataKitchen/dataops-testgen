import van from '../van.min.js';
import { Card } from './card.js';
import { dot } from './dot.js';
import { getScoreColor } from '../score_utils.js';
import { loadStylesheet } from '../utils.js';

const { div, i, span } = van.tags;
const { circle, svg, text } = van.tags("http://www.w3.org/2000/svg");

const ScoreCard = (
    /** @type {Score} */ score,
    /** @type {(Function|Array|any|undefined)}*/ actions,
) => {
    loadStylesheet('score-card', stylesheet);

    const dimensions = score.dimensions ?? [];

    return Card({
        title: score.name,
        actionContent: actions,
        class: 'tg-score-card',
        content: () => div(
            { class: 'flex-row' },
            ScoreChart("Total Score", score.score),
            i({ class: 'mr-4 ml-4' }),
            // ScoreChart("CDE Score", score.cde_score),
            div(
                { class: 'flex-column ml-4 tg-score-card--qualities-wrapper' },
                span({ class: 'mb-2 text-secondary' }, 'Quality Dimension'),
                div(
                    { class: 'flex-row fx-flex-wrap fx-gap-2 tg-score-card--qualities' },
                    dimensions.map(dimension => div(
                        { class: 'flex-row fx-align-flex-center' },
                        dot({ class: 'mr-2' }, getScoreColor(dimension.score)),
                        span({}, dimension.label),
                    )),
                ),
            ),
        ),
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
        text({ x: '50%', y: '40%', 'dominant-baseline': 'middle', 'text-anchor': 'middle', fill: '#000000DE', 'font-size': '18px', 'font-weight': 500 }, score ?? '-'),
        text({ x: '50%', y: '40%', 'dominant-baseline': 'middle', 'text-anchor': 'middle', fill: '#0000008A', 'font-size': '14px', class: 'tg-score-chart--label' }, label),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-score-card {
    width: 400px;
    box-sizing: border-box;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin-bottom: unset !important;
}

.tg-score-card--qualities-wrapper {
    width: calc(50% - 16px);
}

.tg-score-card--qualities {
    display: grid;
    grid-gap: 8px;
    grid-template-columns: 100px 100px;
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
    stroke: #f5f5f5;
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
