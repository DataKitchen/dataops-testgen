/**
 * @import {ChartViewBox, Point} from './chart_canvas.js';
 * 
 * @typedef Options
 * @type {object}
 * @property {ChartViewBox} viewBox
 * @property {string} lineColor
 * @property {number} lineWidth
 * @property {string} markerColor
 * @property {number} markerSize
 * @property {Point?} nestedPosition
 * @property {number[]?} yAxisTicks
 */
import van from '../van.min.js';
import { colorMap, formatTimestamp } from '../display_utils.js';
import { getValue } from '../utils.js';

const { circle,  g, polyline, svg } = van.tags("http://www.w3.org/2000/svg");

/**
 * 
 * @param {Options} options
 * @param {Point[]} points
 */
const MonitoringSparklineChart = (options, ...points) => {
    const _options = {
        ...defaultOptions,
        ...(options ?? {}),
    };

    const minX = van.state(0);
    const minY = van.state(0);
    const width = van.state(0);
    const height = van.state(0);
    const linePoints = van.state(points);

    van.derive(() => {
        const viewBox = getValue(_options.viewBox);
        width.val = viewBox.width;
        height.val = viewBox.height;
        minX.val = viewBox.minX;
        minY.val = viewBox.minY;
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
        () => polyline({
            points: linePoints.val.map(point => `${point.x} ${point.y}`).join(', '),
            style: `stroke: ${getValue(_options.lineColor)}; stroke-width: ${getValue(_options.lineWidth)};`,
            fill: 'none',
        }),
    );
};

/**
 * 
 * @param {*} options 
 * @param {Point[]} points 
 * @returns 
 */
const MonitoringSparklineMarkers = (options, points) => {
    return g(
        {},
        ...points.map((point) => {
            return circle({
                cx: point.x,
                cy: point.y,
                r: options.size || defaultMarkerSize,
                fill: options.color || defaultMarkerColor,
                onmouseenter: () => options.showTooltip?.(`(${formatTimestamp(point.originalX, true)}; ${point.originalY})`, point),
                onmouseleave: () => options.hideTooltip?.(),
            });
        }),
    );
};

const /** @type Options */ defaultOptions = {
    lineColor: colorMap.blueLight,
    lineWidth: 3,
    yAxisTicks: undefined,
};
const defaultMarkerSize = 3;
const defaultMarkerColor = colorMap.blueLight;

export { MonitoringSparklineChart, MonitoringSparklineMarkers };
