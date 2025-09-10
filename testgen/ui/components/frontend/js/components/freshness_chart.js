/**
 * @typedef Point
 * @type {object}
 * @property {number} x
 * @property {number} y
 * 
 * @typedef Options
 * @type {object}
 * @property {number} width
 * @property {number} height
 * @property {number} paddingLeft
 * @property {number} paddingRight
 * @property {Point?} nestedPosition
 * @property {number} lineWidth
 * @property {string} freshLineColor
 * @property {string} staleLineColor
 * @property {number} staleMarkerSize
 * @property {number} freshMarkerSize
 * 
 * @typedef FreshnessEvent
 * @type {object}
 * @property {boolean} changed
 * @property {boolean} expected
 * @property {string} time
 */
import van from '../van.min.js';
import { colorMap } from '../display_utils.js';
import { scale } from '../axis_utils.js';

const { circle, g, line, rect, svg } = van.tags("http://www.w3.org/2000/svg");

/**
 * 
 * @param {Options} options
 * @param {Array<FreshnessEvent>} events
 */
const FreshnessChart = (options, ...events) => {
    const _options = {
        ...defaultOptions,
        ...(options ?? {}),
    };
    const origin = {x: 0, y: 0};
    const end = {x: _options.width, y: _options.height};

    const timeline = events.map(e => Date.parse(e.time));
    const freshnessEvents = events.map(e => {
        const position = scale(Date.parse(e.time), {
            old: {min: Math.min(...timeline), max: Math.max(...timeline)},
            new: {min: origin.x + _options.paddingLeft, max: end.x - _options.paddingRight},
        }, origin.x);
        const lineProps = { x1: position, y1: origin.y, x2: position, y2: end.y };

        if (e.expected === false) {
            return line({
                ...lineProps,
                style: `stroke: ${colorMap.lightGrey}; stroke-width: ${_options.lineWidth};`,
            });
        }

        if (e.changed) {
            return g(
                {},
                line({
                    ...lineProps,
                    style: `stroke: ${_options.freshLineColor}; stroke-width: ${_options.lineWidth};`,
                }),
                circle({
                    cx: lineProps.x1,
                    cy: end.y / 2,
                    r: _options.freshMarkerSize,
                    fill: _options.freshLineColor,
                }),
            );
        }

        return g(
            {},
            line({
                ...lineProps,
                style: `stroke: ${_options.staleLineColor}; stroke-width: ${_options.lineWidth};`,
            }),
            rect({
                width: _options.staleMarkerSize,
                height: _options.staleMarkerSize,
                x: lineProps.x1 - (_options.staleMarkerSize / 2),
                y: end.y / 2 - _options.staleMarkerSize / 2,
                fill: _options.staleLineColor,
                style: `transform-box: fill-box; transform-origin: center;`,
                transform: 'rotate(45)',
            }),
        );
    });

    return svg(
        {
            width: '100%',
            height: '100%',
            style: `overflow: visible;`,
            ...(_options.nestedPosition ? {..._options.nestedPosition} : {viewBox: `0 0 ${_options.width} ${_options.height}`}),
        },
        ...freshnessEvents,
    );
};

const /** @type Options */ defaultOptions = {
    width: 600,
    height: 200,
    paddingLeft: 16,
    paddingRight: 16,
    freshLineColor: colorMap.green,
    staleLineColor: colorMap.red,
    lineWidth: 3,
    staleMarkerSize: 8,
    freshMarkerSize: 4,
    nestedPosition: {x: 0, y: 0},
};

export { FreshnessChart };
