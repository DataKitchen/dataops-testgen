/**
 * @import {ChartViewBox, Point} from './chart_canvas.js';
 * 
 * @typedef Options
 * @type {object}
 * @property {number} width
 * @property {number} height
 * @property {number} lineWidth
 * @property {number} lineHeight
 * @property {number} staleMarkerSize
 * @property {number} freshMarkerSize
 * @property {Point?} nestedPosition
 * @property {ChartViewBox?} viewBox
 * @property {Function?} showTooltip
 * @property {Function?} hideTooltip
 * @property {PredictedEvent[]?} prediction
 * 
 * @typedef FreshnessEvent
 * @type {object}
 * @property {Point} point
 * @property {number} time
 * @property {boolean} changed
 * @property {string} status
 * @property {boolean} isTraining
 * 
 * @typedef PredictedEvent
 * @type {Object}
 * @property {number} x
 * @property {number} y
 * @property {number} time
 */
import van from '../van.min.js';
import { colorMap, formatTimestamp } from '../display_utils.js';
import { getValue } from '../utils.js';

const { div, span } = van.tags;
const { circle, g, line, rect, svg } = van.tags("http://www.w3.org/2000/svg");
const colorByStatus = {
    Passed: colorMap.limeGreen,
    Failed: colorMap.red,
    Warning: colorMap.orange,
    Log: colorMap.blueLight,
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
        const minY = point.y - (_options.lineHeight / 2) + 2;
        const maxY = point.y + (_options.lineHeight / 2) - 2;
        const lineProps = { x1: point.x, y1: minY, x2: point.x, y2: maxY };
        const eventColor = getFreshnessEventColor(event);
        const markerProps = _options.showTooltip ? {
            onmouseenter: () => _options.showTooltip?.(FreshnessChartTooltip(event), point),
            onmouseleave: () => _options.hideTooltip?.(),
        } : {};

        return g(
            {...markerProps},
            event.changed 
                ? line({
                    ...lineProps,
                    style: `stroke: ${eventColor}; stroke-width: ${event.isTraining ? '1' : _options.lineWidth};`,
                })
                : null,
            !['Passed', 'Log'].includes(event.status)
                ? rect({
                    width: _options.staleMarkerSize,
                    height: _options.staleMarkerSize,
                    x: lineProps.x1 - (_options.staleMarkerSize / 2),
                    y: maxY - (_options.staleMarkerSize / 2),
                    fill: eventColor,
                    style: `transform-box: fill-box; transform-origin: center;`,
                    transform: 'rotate(45)',
                })
                : circle({
                    cx: lineProps.x1,
                    cy: maxY,
                    r: 2,
                    fill: event.isTraining ? 'var(--dk-dialog-background)' : eventColor,
                    style: `stroke: ${eventColor}; stroke-width: 1;`,
                }),
        );
    });
    const predicitedEvents = (getValue(_options.prediction) ?? []).map((event) => {
        const minY = event.y - (_options.lineHeight / 2) + 2;
        const maxY = event.y + (_options.lineHeight / 2) - 2;
        const lineProps = { x1: event.x, y1: minY, x2: event.x, y2: maxY };
        const markerProps = _options.showTooltip ? {
            onmouseenter: () => _options.showTooltip?.(FreshnessChartPredictionTooltip(event), event),
            onmouseleave: () => _options.hideTooltip?.(),
        } : {};
        const barHeight = getValue(_options.height);

        return g(
            {...markerProps},
            rect({
                width: _options.staleMarkerSize,
                height: barHeight,
                x: lineProps.x1 - (_options.staleMarkerSize / 2),
                y: 0,
                fill: colorMap.emptyDark,
                opacity: 0.25,
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
        ...predicitedEvents,
    );
};

const /** @type Options */ defaultOptions = {
    width: 600,
    height: 200,
    lineWidth: 2,
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
    if (!event.changed && (event.status === 'Passed' || event.isTraining)) {
        return colorMap.emptyDark;
    }
    return colorByStatus[event.status];
}

/**
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

/**
 * @param {PredictedEvent} event
 * @returns {HTMLDivElement}
 */
const FreshnessChartPredictionTooltip = (event) => {
    return div(
        {class: 'flex-column'},
        span({class: 'text-left mb-1'}, formatTimestamp(event.time, false)),
        span({class: 'text-left text-small'}, 'Update expected'),
    );
};

export { FreshnessChart };
