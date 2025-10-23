/**
 * @import {ChartViewBox, Point} from './chart_canvas.js';
 * 
 * @typedef Options
 * @type {object}
 * @property {number} width
 * @property {number} height
 * @property {number} lineWidth
 * @property {number} lineHeight
 * @property {string} freshLineColor
 * @property {string} staleLineColor
 * @property {number} staleMarkerSize
 * @property {number} freshMarkerSize
 * @property {Point?} nestedPosition
 * @property {ChartViewBox?} viewBox
 * @property {Function?} showTooltip
 * @property {Function?} hideTooltip
 * 
 * @typedef FreshnessEvent
 * @type {object}
 * @property {Point} point
 * @property {number} time
 * @property {boolean} changed
 * @property {boolean?} expected
 * @property {string?} status
 */
import van from '../van.min.js';
import { colorMap, formatTimestamp } from '../display_utils.js';
import { getValue } from '../utils.js';

const { div, span } = van.tags;
const { circle, g, line, rect, svg } = van.tags("http://www.w3.org/2000/svg");
const freshnessColorByStatus = {
    Passed: colorMap.limeGreen,
    Log: colorMap.blueLight,
};
const staleColorByStatus = {
    Failed: colorMap.red,
    Warning: colorMap.orange,
    Log: colorMap.lightGrey,
};

/**
 * @param {Options} options
 * @param {Array<FreshnessEvent>} events
 */
const FreshnessChart = (options, ...events) => {
    const _options = {
        ...defaultOptions,
        ...(options ?? {}),
    };

    const minX = van.state(0);
    const minY = van.state(0);
    const width = van.state(0);
    const height = van.state(0);

    van.derive(() => {
        const viewBox = getValue(_options.viewBox);
        width.val = viewBox?.width;
        height.val = viewBox?.height;
        minX.val = viewBox?.minX;
        minY.val = viewBox?.minY;
    });

    const freshnessEvents = events.map(event => {
        const point = event.point;
        const minY = point.y - (_options.lineHeight / 2);
        const maxY = point.y + (_options.lineHeight / 2);
        const lineProps = { x1: point.x, y1: minY, x2: point.x, y2: maxY };
        const lineColor = getFreshnessEventColor(event);
        const markerProps = _options.showTooltip ? {
            onmouseenter: () => _options.showTooltip?.(FreshnessChartTooltip(event), point),
            onmouseleave: () => _options.hideTooltip?.(),
        } : {};

        if (event.expected === false) {
            return line({
                ...lineProps,
                ...markerProps,
                style: `stroke: ${lineColor}; stroke-width: ${_options.lineWidth};`,
            });
        }

        if (event.changed) {
            return g(
                {...markerProps},
                line({
                    ...lineProps,
                    style: `stroke: ${lineColor}; stroke-width: ${_options.lineWidth};`,
                }),
                circle({
                    cx: lineProps.x1,
                    cy: point.y,
                    r: _options.freshMarkerSize,
                    fill: lineColor,
                }),
            );
        }

        return g(
            {...markerProps},
            line({
                ...lineProps,
                style: `stroke: ${lineColor}; stroke-width: ${_options.lineWidth};`,
            }),
            rect({
                width: _options.staleMarkerSize,
                height: _options.staleMarkerSize,
                x: lineProps.x1 - (_options.staleMarkerSize / 2),
                y: point.y - _options.staleMarkerSize / 2,
                fill: lineColor,
                style: `transform-box: fill-box; transform-origin: center;`,
                transform: 'rotate(45)',
            }),
        );
    });

    const extraAttributes = {};
    if (_options.nestedPosition) {
        extraAttributes.x = () => (_options.nestedPosition?.rawVal || _options.nestedPosition).x;
        extraAttributes.y = () => (_options.nestedPosition?.rawVal || _options.nestedPosition).y;
    } else {
        extraAttributes.viewBox = () => `${minX.val} ${minY.val} ${width.val} ${height.val}`;
    }

    return svg(
        {
            width: '100%',
            height: '100%',
            ...extraAttributes,
        },
        ...freshnessEvents,
    );
};

const /** @type Options */ defaultOptions = {
    width: 600,
    height: 200,
    freshLineColor: colorMap.limeGreen,
    staleLineColor: colorMap.red,
    lineWidth: 3,
    lineHeight: 5,
    staleMarkerSize: 8,
    freshMarkerSize: 4,
    nestedPosition: {x: 0, y: 0},
};

/**
 * @param {FreshnessEvent} event
 * @returns 
 */
const getFreshnessEventColor = (event) => {
    if (event.expected === false) {
        return colorMap.lightGrey;
    }
    if (event.changed) {
        return freshnessColorByStatus[event.status] || defaultOptions.freshLineColor;
    }
    return staleColorByStatus[event.status] || defaultOptions.staleLineColor;
}

/**
 * 
 * @param {FreshnessEvent} event
 * @returns {HTMLDivElement}
 */
const FreshnessChartTooltip = (event) => {
    return div(
        {class: 'flex-column'},
        span({class: 'text-left mb-1'}, formatTimestamp(event.time, false)),
        span({class: 'text-left text-small'}, event.changed ? 'Update' : 'No update'),
    );
};

export { FreshnessChart, getFreshnessEventColor };
