/**
 * @typedef SummaryItem
 * @type {object}
 * @property {string} value
 * @property {string} color
 * @property {string} label
 * 
 * @typedef Properties
 * @type {object}
 * @property {Array.<SummaryItem>} items
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { colorMap, formatNumber } from '../display_utils.js';

const { div } = van.tags;

const SummaryCounts = (/** @type Properties */ props) => {
    loadStylesheet('summaryCounts', stylesheet);

    return div(
        { class: 'flex-row fx-gap-5' },
        getValue(props.items).map(item => div(
            { class: 'flex-row fx-align-stretch fx-gap-2' },
            div({ class: 'tg-summary-counts--bar', style: `background-color: ${colorMap[item.color] || item.color};` }),
            div(
                div({ class: 'text-caption' }, item.label),
                div({ class: 'tg-summary-counts--count' }, formatNumber(item.value)),
            )
        )),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-summary-counts--bar {
    width: 4px;
}

.tg-summary-counts--count {
    font-size: 16px;
}
`);

export { SummaryCounts };
