/**
 * @typedef Properties
 * @type {object}
 * @property {number} minimum
 * @property {number} maximum
 * @property {number} median
 * @property {number} lowerQuartile
 * @property {number} upperQuartile
 * @property {number} average
 * @property {number} standardDeviation
 * @property {number?} width
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { colorMap, formatNumber } from '../display_utils.js';
import { niceBounds } from '../axis_utils.js';

const { div } = van.tags;
const boxColor = colorMap.teal;
const lineColor = colorMap.limeGreen;

const BoxPlot = (/** @type Properties */ props) => {
    loadStylesheet('boxPlot', stylesheet);

    const { minimum, maximum, median, lowerQuartile, upperQuartile, average, standardDeviation, width } = props;
    const axisTicks = van.derive(() => niceBounds(getValue(minimum), getValue(maximum)));

    return div(
        {
            class: 'flex-row fx-flex-wrap fx-gap-6',
            style: () => `max-width: ${width ? getValue(width) + 'px' : '100%'};`,
        },
        div(
            { class: 'pl-7 pr-7', style: 'flex: 300px' },
            div(
                {
                    class: 'tg-box-plot--line',
                    style: () => {
                        const { min, range } = axisTicks.val;
                        return `left: ${(getValue(average) - getValue(standardDeviation) - min) * 100 / range}%;
                            width: ${getValue(standardDeviation) * 2 * 100 / range}%;`;
                    },
                },
                div({ class: 'tg-box-plot--dot' }),
            ),
            div(
                {
                    class: 'tg-box-plot--grid',
                    style: () => {
                        const { min, max, range } = axisTicks.val;

                        return `grid-template-columns:
                            ${(getValue(minimum) - min) * 100 / range}%
                            ${(getValue(lowerQuartile) - getValue(minimum)) * 100 / range}%
                            ${(getValue(median) - getValue(lowerQuartile)) * 100 / range}%
                            ${(getValue(upperQuartile) - getValue(median)) * 100 / range}%
                            ${(getValue(maximum) - getValue(upperQuartile)) * 100 / range}%
                            ${(max - getValue(maximum)) * 100 / range}%;`;
                    },
                },
                div({ class: 'tg-box-plot--space-left' }),
                div({ class: 'tg-box-plot--top-left' }),
                div({ class: 'tg-box-plot--bottom-left' }),
                div({ class: 'tg-box-plot--mid-left' }),
                div({ class: 'tg-box-plot--mid-right' }),
                div({ class: 'tg-box-plot--top-right' }),
                div({ class: 'tg-box-plot--bottom-right' }),
                div({ class: 'tg-box-plot--space-right' }),
            ),
            () => {
                const { min, max, step, range } = axisTicks.val;
                const ticks = [];
                let currentTick = min;
                while (currentTick <= max) {
                    ticks.push(currentTick);
                    currentTick += step;
                }

                return div(
                    { class: 'tg-box-plot--axis' },
                    ticks.map(position => div(
                        {
                            class: 'tg-box-plot--axis-tick',
                            style: `left: ${(position - min) * 100 / range}%;`
                        },
                        formatNumber(position),
                    )),
                );
            },
        ),
        div(
            { class: 'flex-column fx-gap-2 text-caption', style: 'flex: 150px;' },
            div(
                { class: 'flex-row fx-gap-2' },
                div({ class: 'tg-blox-plot--legend-line' }),
                'Average---Standard Deviation',
            ),
            div(
                { class: 'flex-row fx-gap-2' },
                div({ class: 'tg-blox-plot--legend-whisker' }),
                'Minimum---Maximum',
            ),
            div(
                { class: 'flex-row fx-gap-2' },
                div({ class: 'tg-blox-plot--legend-box' }),
                '25th---Median---75th',
            ),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-box-plot--line {
    position: relative;
    margin: 8px 0 24px 0;
    border-top: 2px dotted ${lineColor};
}

.tg-box-plot--dot {
    position: absolute;
    top: -1px;
    left: 50%;
    transform: translateX(-50%) translateY(-50%);
    width: 10px;
    height: 10px;
    border-radius: 5px;
    background-color: ${lineColor};
}

.tg-box-plot--grid {
    height: 24px;
    display: grid;
    grid-template-rows: 50% 50%;
}

.tg-box-plot--grid div {
    border-color: var(--caption-text-color);
    border-style: solid;
}

.tg-box-plot--space-left {
    grid-column-start: 1;
    grid-column-end: 2;
    grid-row-start: 1;
    grid-row-end: 3;
    border: 0;
}

.tg-box-plot--top-left {
    grid-column-start: 2;
    grid-column-end: 3;
    grid-row-start: 1;
    grid-row-end: 2;
    border-width: 0 0 1px 2px;
}

.tg-box-plot--bottom-left {
    grid-column-start: 2;
    grid-column-end: 3;
    grid-row-start: 2;
    grid-row-end: 3;
    border-width: 1px 0 0 2px;
}

.tg-box-plot--mid-left {
    grid-column-start: 3;
    grid-column-end: 4;
    grid-row-start: 1;
    grid-row-end: 3;
    border-width: 1px 2px 1px 1px;
    border-radius: 4px 0 0 4px;
    background-color: ${boxColor};
}

.tg-box-plot--mid-right {
    grid-column-start: 4;
    grid-column-end: 5;
    grid-row-start: 1;
    grid-row-end: 3;
    border-width: 1px 1px 1px 2px;
    border-radius: 0 4px 4px 0;
    background-color: ${boxColor};
}

.tg-box-plot--top-right {
    grid-column-start: 5;
    grid-column-end: 6;
    grid-row-start: 1;
    grid-row-end: 2;
    border-width: 0 2px 1px 0;
}

.tg-box-plot--bottom-right {
    grid-column-start: 5;
    grid-column-end: 6;
    grid-row-start: 2;
    grid-row-end: 3;
    border-width: 1px 2px 0 0;
}

.tg-box-plot--space-right {
    grid-column-start: 6;
    grid-column-end: 7;
    grid-row-start: 1;
    grid-row-end: 3;
    border: 0;
}

.tg-box-plot--axis {
    position: relative;
    margin: 24px 0;
    width: 100%;
    height: 2px;
    background-color: var(--disabled-text-color);
    color: var(--caption-text-color);
}

.tg-box-plot--axis-tick {
    position: absolute;
    top: 8px;
    transform: translateX(-50%);
}

.tg-box-plot--axis-tick::before {
    position: absolute;
    top: -9px;
    left: 50%;
    transform: translateX(-50%);
    width: 4px;
    height: 4px;
    border-radius: 2px;
    background-color: var(--disabled-text-color);
    content: '';
}

.tg-blox-plot--legend-line {
    width: 26px;
    border: 1px dotted ${lineColor};
    position: relative;
}

.tg-blox-plot--legend-line::after {
    position: absolute;
    left: 50%;
    transform: translateX(-50%) translateY(-50%);
    width: 6px;
    height: 6px;
    border-radius: 6px;
    background-color: ${lineColor};
    content: '';
}

.tg-blox-plot--legend-whisker {
    width: 24px;
    height: 12px;
    border: solid var(--caption-text-color);
    border-width: 0 2px 0 2px;
    position: relative;
}

.tg-blox-plot--legend-whisker::after {
    position: absolute;
    top: 5px;
    width: 24px;
    height: 2px;
    background-color: var(--caption-text-color);
    content: '';
}

.tg-blox-plot--legend-box {
    width: 26px;
    height: 12px;
    border: 1px solid var(--caption-text-color);
    border-radius: 4px;
    background-color: ${boxColor};
    position: relative;
}

.tg-blox-plot--legend-box::after {
    position: absolute;
    left: 12px;
    width: 2px;
    height: 12px;
    background-color: var(--caption-text-color);
    content: '';
}
`);

export { BoxPlot };
