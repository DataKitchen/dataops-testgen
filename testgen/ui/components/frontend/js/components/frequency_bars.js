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
 * @property {string} title
 * @property {string?} color
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { colorMap } from '../display_utils.js';

const { div, span } = van.tags;
const defaultColor = 'teal';

const FrequencyBars = (/** @type Properties */ props) => {
    loadStylesheet('frequencyBars', stylesheet);

    const total = van.derive(() => getValue(props.total));
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
                    span({ class: 'tg-frequency-bars--empty' }),
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
                    count,
                ),
                div(value),
            );
        }),
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

.tg-frequency-bars--empty {
    position: absolute;
    width: 100%;
    height: 100%;
    border-radius: 4px;
    background-color: ${colorMap['emptyLight']}
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
`);

export { FrequencyBars };
