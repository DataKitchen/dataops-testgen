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
 * @property {Object?} attributes
 * @property {PredictionPoint[]?} prediction
 * 
 * @typedef MonitoringPoint
 * @type {Object}
 * @property {number} x
 * @property {number} y
 * @property {boolean?} isAnomaly
 * 
 * @typedef PredictionPoint
 * @type {Object}
 * @property {number} x
 * @property {number} upper
 * @property {number} lower
 */
import van from '../van.min.js';
import { colorMap, formatTimestamp } from '../display_utils.js';
import { getValue } from '../utils.js';

const { circle, g, path, polyline, rect, svg } = van.tags("http://www.w3.org/2000/svg");

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
        width.val = viewBox?.width;
        height.val = viewBox?.height;
        minX.val = viewBox?.minX;
        minY.val = viewBox?.minY;
    });

    const extraAttributes = {...(_options.attributes ?? {})};
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
        () => _options.prediction && _options.prediction.length > 0
            ? path({
                d: generateShadowPath(_options.prediction ?? []),
                fill: 'rgba(218, 218, 218, 0.3)',
                fillOpacity: 0.3,
                stroke: 'none',
            })
            : '',
        () => polyline({
            points: linePoints.val.map(point => `${point.x} ${point.y}`).join(', '),
            style: `stroke: ${getValue(_options.lineColor)}; stroke-width: ${getValue(_options.lineWidth)};`,
            fill: 'none',
        }),
    );
};

function generateShadowPath(data) {
  let pathString = `M ${data[0].x} ${data[0].upper}`;
  for (let i = 1; i < data.length; i++) {
    pathString += ` L ${data[i].x} ${data[i].upper}`;
  }
  for (let i = data.length - 1; i >= 0; i--) {
    pathString += ` L ${data[i].x} ${data[i].lower}`;
  }
  pathString += " Z";
  return pathString;
}

/**
 * 
 * @param {*} options 
 * @param {MonitoringPoint[]} points 
 * @returns 
 */
const MonitoringSparklineMarkers = (options, points) => {
    return g(
        {transform: options.transform ?? undefined},
        ...points.map((point) => {
            if (point.isAnomaly) {
                const size = options.anomalySize || defaultAnomalyMarkerSize;
                return rect({
                    width: size,
                    height: size,
                    x: point.x - (size / 2),
                    y: point.y - (size / 2),
                    fill: options.anomalyColor || defaultAnomalyMarkerColor,
                    style: `transform-box: fill-box; transform-origin: center;`,
                    transform: 'rotate(45)',
                    onmouseenter: () => options.showTooltip?.(`(${formatTimestamp(point.originalX, true)}; ${point.originalY})`, point),
                    onmouseleave: () => options.hideTooltip?.(),
                });
            }

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
    attributes: {},
};
const defaultMarkerSize = 3;
const defaultMarkerColor = colorMap.blueLight;
const defaultAnomalyMarkerSize = 3;
const defaultAnomalyMarkerColor = colorMap.red;

export { MonitoringSparklineChart, MonitoringSparklineMarkers };
