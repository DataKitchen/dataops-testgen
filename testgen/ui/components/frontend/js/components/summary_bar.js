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
 * @property {string} label
 * @property {number} height
 * @property {number} width
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { div, span } = van.tags;
const colorMap = {
    red: '#EF5350',
    orange: '#FF9800',
    yellow: '#FDD835',
    green: '#9CCC65',
    purple: '#AB47BC',
    blue: '#42A5F5',
    brown: '#8D6E63',
    grey: '#BDBDBD',
}
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
        () => {
            return total ? div(
                { class: `tg-summary-bar--caption` },
                summaryItems.map(item => `${item.label}: ${item.value || 0}`).join(', '),
            ) : null;
        },
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
    margin-top: 4px;
    color: var(--caption-text-color);
    font-style: italic;
}
`);

export { SummaryBar };
