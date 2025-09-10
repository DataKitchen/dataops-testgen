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
 * @property {string} lineColor
 * @property {number} lineWidth
 * @property {string} markerColor
 * @property {number} markerSize
 * @property {Point?} nestedPosition
 * @property {number[]?} yAxisTicks
 * 
 * @typedef MonitoringEvent
 * @type {object}
 * @property {number} value
 * @property {string} time
 */
import van from '../van.min.js';
import { colorMap } from '../display_utils.js';
import { scale } from '../axis_utils.js';

const { circle, g, line, rect, polyline, svg } = van.tags("http://www.w3.org/2000/svg");

/**
 * 
 * @param {Options} options
 * @param {Array<MonitoringEvent>} events
 */
const MonitoringSparklineChart = (options, ...events) => {
    const _options = {
        ...defaultOptions,
        ...(options ?? {}),
    };
    const origin = {x: 0, y: 0};
    const end = {x: _options.width, y: _options.height};

    const values = _options.yAxisTicks ?? events.map(e => e.value);
    const timeline = events.map(e => Date.parse(e.time));

    const linePoints = events.map(e => {
        const xPosition = scale(Date.parse(e.time), {
            old: {min: Math.min(...timeline), max: Math.max(...timeline)},
            new: {min: origin.x + _options.paddingLeft, max: end.x - _options.paddingRight},
        }, origin.x);
        const yPosition = scale(e.value, {
            old: {min: Math.min(...values), max: Math.max(...values)},
            new: {min: origin.y, max: end.y},
        }, origin.x);

        return { x: xPosition, y: end.y - yPosition };
    });

    return svg(
        {
            width: '100%',
            height: '100%',
            style: `overflow: visible;`,
            ...(_options.nestedPosition ? {..._options.nestedPosition} : {viewBox: `0 0 ${_options.width} ${_options.height}`}),
        },
        polyline({
            points: linePoints.map(point => `${point.x} ${point.y}`).join(', '),
            style: `stroke: ${_options.lineColor}; stroke-width: ${_options.lineWidth};`,
            fill: 'none',
        }),
    );
};

const /** @type Options */ defaultOptions = {
    width: 600,
    height: 200,
    paddingLeft: 16,
    paddingRight: 16,
    lineColor: colorMap.blueLight,
    lineWidth: 3,
    markerColor: colorMap.red,
    markerSize: 8,
    nestedPosition: {x: 0, y: 0},
    yAxisTicks: undefined,
};

export { MonitoringSparklineChart };
