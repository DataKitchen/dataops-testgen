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
import { Streamlit } from '../streamlit.js';

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

const SummaryBar = (/** @type Properties */ props) => {
    const height = props.height.val || 24;
    const width = props.width.val;
    const summaryItems = props.items.val;
    const label = props.label.val;
    const total = summaryItems.reduce((sum, item) => sum + item.value, 0);

    Streamlit.setFrameHeight(height + 24 + (label ? 24 : 0));

    if (!window.testgen.loadedStylesheets.summaryBar) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets.summaryBar = true;
    }
    
    return div(
        { class: 'tg-summary-bar-wrapper' },
        () => {
            return label ? div(
                { class: 'tg-summary-bar--label' },
                label,
            ) : null;
        },
        div(
            {
                class: 'tg-summary-bar',
                style: `height: ${height}px; max-width: ${width ? width + 'px' : '100%'}`
            },
            summaryItems.map(item => span({
                class: `tg-summary-bar--item`,
                style: `width: ${item.value * 100 / total}%; background-color: ${colorMap[item.color] || item.color};`,
            })),
        ),
        () => {
            return total ? div(
                { class: `tg-summary-bar--caption` },
                summaryItems.map(item => `${item.label}: ${item.value}`).join(', '),
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
