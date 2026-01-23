/**
 * @typedef FrequencyItem
 * @type {object}
 * @property {string} value
 * @property {number} count
 * 
 * @typedef Properties
 * @type {object}
 * @property {FrequencyItem[]} items
 * @property {number} total
 * @property {number} nullCount
 * @property {string} title
 * @property {string?} color
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { colorMap, formatNumber } from '../display_utils.js';

const { div, span } = van.tags;
const defaultColor = 'teal';
const otherColor = colorMap['emptyTeal'];
const nullColor = colorMap['emptyLight'];

const FrequencyBars = (/** @type Properties */ props) => {
    loadStylesheet('frequencyBars', stylesheet);

    const total = van.derive(() => getValue(props.total));
    const nullCount = van.derive(() => getValue(props.nullCount));
    const color = van.derive(() => {
        const colorValue = getValue(props.color) || defaultColor;
        return colorMap[colorValue] || colorValue;
    });
    const width = van.derive(() => {
        const maxCount = getValue(props.items).reduce((max, { count }) => Math.max(max, count), 0);
        return String(maxCount).length * 7;
    });

    return () => div(
        div(
            { class: 'mb-2 text-secondary' },
            props.title,
        ),
        getValue(props.items).map(({ value, count }) => {
            return div(
                { class: 'flex-row fx-gap-2' },
                div(
                    { class: 'tg-frequency-bars' },
                    span({
                        class: 'tg-frequency-bars--fill',
                        style: `width: 100%; background-color: ${nullColor};`,
                    }),
                    span({
                        class: 'tg-frequency-bars--fill',
                        style: () => `width: ${(total.val - nullCount.val) * 100 / total.val}%;
                            ${(total.val - nullCount.val) ? 'min-width: 1px;' : ''}
                            background-color: ${otherColor};`,
                    }),
                    span({
                        class: 'tg-frequency-bars--fill',
                        style: () => `width: ${count * 100 / total.val}%;
                            ${count ? 'min-width: 1px;' : ''}
                            background-color: ${color.val};`,
                    }),
                ),
                div(
                    {
                        class: 'text-caption tg-frequency-bars--count',
                        style: () => `width: ${width.val}px;`,
                    },
                    formatNumber(count),
                ),
                div(value),
            );
        }),
        div(
            { class: 'tg-frequency-bars--legend flex-row fx-flex-wrap text-caption mt-1' },
            span({ class: 'dot', style: `color: ${color.val};` }),
            'Value',
            span({ class: 'dot', style: `color: ${otherColor};` }),
            'Other',
            span({ class: 'dot', style: `color: ${nullColor};` }),
            'Null',
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-frequency-bars {
    width: 150px;
    height: 15px;
    flex-shrink: 0;
    position: relative;
}

.tg-frequency-bars--fill {
    position: absolute;
    border-radius: 4px;
    height: 100%;
}

.tg-frequency-bars--count {
    flex-shrink: 0;
    text-align: right;
}

.tg-frequency-bars--legend {
    font-style: italic;
}

.tg-frequency-bars--legend span {
    margin-right: 2px;
    font-size: 4px;
}

.tg-frequency-bars--legend span:not(:first-child) {
    margin-left: 8px;
}
`);

export { FrequencyBars };
