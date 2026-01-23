import van from '../van.min.js';
import { getScoreColor } from '../score_utils.js';
import { dot } from './dot.js';

const { div, span } = van.tags;

const ScoreLegend = (/** @type string */ style) => {
    return div(
        { class: 'flex-row fx-gap-3 text-secondary', style },
        span({ class: 'fx-flex' }),
        LegendItem('N/A', NaN),
        LegendItem('0-85', 0),
        LegendItem('86-90', 86),
        LegendItem('91-95', 91),
        LegendItem('96-100', 96),
    );
}

const LegendItem = (label, value) => {
    return div(
        { class: 'flex-row fx-align-flex-center' },
        dot({ class: 'mr-2' }, getScoreColor(value)),
        span({}, label),
    );
};

export { ScoreLegend };
