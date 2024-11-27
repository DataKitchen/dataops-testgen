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
 * @property {string?} label
 * @property {number?} height
 * @property {number?} width
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { colorMap } from '../display_utils.js';

const { div, span } = van.tags;
const defaultHeight = 24;

const SummaryBar = (/** @type Properties */ props) => {
    loadStylesheet('summaryBar', stylesheet);
    const total = van.derive(() => getValue(props.items).reduce((sum, item) => sum + item.value, 0));

    return div(
        { style: () => `max-width: ${props.width ? getValue(props.width) + 'px' : '100%'};` },
        () => props.label ? div(
            { class: 'tg-summary-bar--label' },
            props.label,
        ) : '',
        () => div(
            {
                class: 'tg-summary-bar',
                style: () => `height: ${getValue(props.height) || defaultHeight}px;`
            },
            getValue(props.items).map(item => span({
                class: 'tg-summary-bar--item',
                style: () => `width: ${item.value * 100 / total.val}%;
                    ${item.value ? 'min-width: 1px;' : ''}
                    background-color: ${colorMap[item.color] || item.color};`,
            })),
        ),
        () => total.val ? div(
            { class: 'tg-summary-bar--caption flex-row fx-flex-wrap text-caption mt-1' },
            getValue(props.items).map(item => div(
                { class: 'tg-summary-bar--legend flex-row' },
                span({
                    class: 'dot',
                    style: `color: ${colorMap[item.color] || item.color};`,
                }),
                `${item.label}: ${item.value || 0}`,
            )),
        ) : '',
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-summary-bar--label {
    margin-bottom: 4px;
}

.tg-summary-bar {
    height: 100%;
    display: flex;
    flex-flow: row nowrap;
    align-items: flex-start;
    justify-content: flex-start;
    border-radius: 4px;
    overflow: hidden;
}

.tg-summary-bar--item {
    height: 100%;
}

.tg-summary-bar--caption {
    font-style: italic;
}

.tg-summary-bar--legend {
    width: auto;
}

.tg-summary-bar--legend:not(:last-child) {
    margin-right: 8px;
}

.tg-summary-bar--legend span {
    margin-right: 2px;
    font-size: 4px;
}
`);

export { SummaryBar };
