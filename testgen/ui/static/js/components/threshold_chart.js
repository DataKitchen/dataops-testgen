/**
 * @import {ChartViewBox, DrawingArea} from './chart_canvas.js';
 * 
 * @typedef Point
 * @type {object}
 * @property {number} x
 * @property {number} y
 * 
 * @typedef Options
 * @type {object}
 * @property {number} width
 * @property {number} height
 * @property {DrawingArea} area
 * @property {ChartViewBox} viewBox
 * @property {number} paddingLeft
 * @property {number} paddingRight
 * @property {string} color
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
import { getValue } from '../utils.js';

const { polygon, polyline, svg } = van.tags("http://www.w3.org/2000/svg");

/**
 * 
 * @param {Options} options
 * @param {Array<Point>} line1
 * @param {Array<Point>?} line2
 */
const ThresholdChart = (options, line1, line2) => {
    const _options = {
        ...defaultOptions,
        ...(options ?? {}),
    };

    const minX = van.state(0);
    const minY = van.state(0);
    const width = van.state(0);
    const height = van.state(0);
    const widthFactor = van.state(1.0);

    van.derive(() => {
        const viewBox = getValue(_options.viewBox);
        width.val = viewBox.width;
        height.val = viewBox.height;
        minX.val = viewBox.minX;
        minY.val = viewBox.minY;
        widthFactor.val = viewBox.widthFactor;
    });

    const extraAttributes = {};
    if (_options.nestedPosition) {
        extraAttributes.x = () => (_options.nestedPosition?.rawVal || _options.nestedPosition).x;
        extraAttributes.y = () => (_options.nestedPosition?.rawVal || _options.nestedPosition).y;
    } else {
        extraAttributes.viewBox = () => `${minX.val} ${minY.val} ${width.val} ${height.val}`;
    }

    let content = () => polyline({
        points: line1.map(point => `${point.x} ${point.y}`).join(', '),
        style: `stroke: ${getValue(_options.color)}; stroke-width: ${getValue(_options.lineWidth)};`,
        fill: 'none',
    });
    if (line2) {
        content = () => polygon({
            points: `${line1.map(point => `${point.x} ${point.y}`).join(', ')} ${line2.map(point => `${point.x} ${point.y}`).join(', ')}`,
            fill: getValue(_options.color),
            stroke: 'none',
        });
    }

    return svg(
        {
            width: '100%',
            height: '100%',
            style: `overflow: visible;`,
            ...extraAttributes,
        },
        content,
    );
};

const /** @type Options */ defaultOptions = {
    width: 600,
    height: 200,
    paddingLeft: 16,
    paddingRight: 16,
    color: colorMap.redLight,
    lineWidth: 3,
    markerColor: colorMap.red,
    markerSize: 8,
    yAxisTicks: undefined,
};

export { ThresholdChart };
