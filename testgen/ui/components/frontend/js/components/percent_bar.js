/**
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {number} value
 * @property {number} total
 * @property {string?} color
 * @property {number?} height
 * @property {number?} width
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { colorMap, formatNumber } from '../display_utils.js';

const { div, span } = van.tags;
const defaultHeight = 10;
const defaultColor = 'purpleLight';

const PercentBar = (/** @type Properties */ props) => {
    loadStylesheet('percentBar', stylesheet);
    const value = van.derive(() => getValue(props.value));
    const total = van.derive(() => getValue(props.total));

    return div(
        { style: () => `max-width: ${props.width ? getValue(props.width) + 'px' : '100%'};` },
        div(
            { class: () => `tg-percent-bar--label ${value.val ? '' : 'text-secondary'}` },
            () => `${getValue(props.label)}: ${formatNumber(value.val)}`,
        ),
        div(
            {
                class: 'tg-percent-bar',
                style: () => `height: ${getValue(props.height) || defaultHeight}px;`,
            },
            span({
                class: 'tg-percent-bar--fill',
                style: () => {
                    const color = getValue(props.color) || defaultColor;
                    return `width: ${value.val * 100 / total.val}%;
                        ${value.val ? 'min-width: 1px;' : ''}
                        background-color: ${colorMap[color] || color};`
                },
            }),
            span({
                class: 'tg-percent-bar--empty',
                style: () => `width: ${(total.val - value.val) * 100 / total.val}%;
                    ${(total.val - value.val) ? 'min-width: 1px;' : ''};`,
            }),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-percent-bar--label {
    margin-bottom: 4px;
}

.tg-percent-bar {
    height: 100%;
    display: flex;
    flex-flow: row nowrap;
    align-items: flex-start;
    justify-content: flex-start;
    border-radius: 4px;
    overflow: hidden;
}

.tg-percent-bar--fill {
    height: 100%;
}

.tg-percent-bar--empty {
    height: 100%;
    background-color: ${colorMap['empty']}
}
`);

export { PercentBar };
