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
 * @property {('predict'|'static')?} predictionMethod
 *
 * @typedef MonitoringPoint
 * @type {Object}
 * @property {number} x
 * @property {number} y
 * @property {string?} label
 * @property {boolean?} isAnomaly
 * @property {boolean?} isTraining
 * @property {boolean?} isPending
 * @property {number?} lowerTolerance
 * @property {number?} upperTolerance
 *
 * @typedef PredictionPoint
 * @type {Object}
 * @property {number} x
 * @property {number?} y
 * @property {number} upper
 * @property {number} lower
 */
import van from '../van.min.js';
import { colorMap, formatNumber, formatTimestamp } from '../display_utils.js';
import { getValue } from '../utils.js';

const { div, span } = van.tags();
const { circle, g, path, polyline, rect, svg } = van.tags("http://www.w3.org/2000/svg");

/**
 * 
 * @param {Options} options
 * @param {MonitoringPoint[]} points
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
    const linePoints = van.state(points.filter(e => !e.isPending));
    const isStaticPrediction = _options.predictionMethod === 'static';
    const predictionPoints = van.derive(() => {
        const _linePoints = linePoints.val;
        const _predictionPoints = _options.prediction ?? [];
        if (_linePoints.length > 0 && _predictionPoints.length > 0) {
            const lastPoint = _linePoints[_linePoints.length - 1];
            if (isStaticPrediction) {
                _predictionPoints.unshift({
                    x: lastPoint.x,
                    y: lastPoint.y,
                    upper: lastPoint.upperTolerance ?? lastPoint.y,
                    lower: lastPoint.lowerTolerance ?? lastPoint.y,
                });
            } else {
                _predictionPoints.unshift({
                    x: lastPoint.x,
                    y: lastPoint.y,
                    upper: lastPoint.upperTolerance ?? lastPoint.y,
                    lower: lastPoint.lowerTolerance ?? lastPoint.y,
                });
            }
        }
        return _predictionPoints;
    });

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
        () => {
            const validPoints = linePoints.val.filter(p =>
                Number.isFinite(p.x) && Number.isFinite(p.y)
            );
            if (validPoints.length < 2) return '';
            return polyline({
                points: validPoints.map(point => `${point.x} ${point.y}`).join(', '),
                style: `stroke: ${getValue(_options.lineColor)}; stroke-width: ${getValue(_options.lineWidth)};`,
                fill: 'none',
            });
        },
        () => {
            const tolerancePoints = linePoints.val.filter(p =>
                Number.isFinite(p.lowerTolerance) || Number.isFinite(p.upperTolerance)
            );
            if (tolerancePoints.length < 2) return '';

            return path({
                d: generateTolerancePath(tolerancePoints, _options.height, getValue(_options.lineWidth)),
                fill: colorMap.blue,
                'fill-opacity': 0.1,
                stroke: 'none',
            });
        },
        () => {
            const validPoints = predictionPoints.rawVal.filter(p =>
                Number.isFinite(p.x) && (Number.isFinite(p.upper) || Number.isFinite(p.lower))
            );
            if (validPoints.length < 2) return '';
            return path({
                d: generateShadowPath(validPoints, _options.height),
                fill: colorMap.emptyDark,
                opacity: 0.25,
                stroke: 'none',
            });
        },
        () => {
            if (isStaticPrediction) return '';
            const validPoints = predictionPoints.rawVal.filter(p =>
                Number.isFinite(p.x) && Number.isFinite(p.y)
            );
            if (validPoints.length < 2) return '';
            return polyline({
                points: validPoints.map(point => `${point.x} ${point.y}`).join(', '),
                style: `stroke: ${getValue(colorMap.grey)}; stroke-width: ${getValue(_options.lineWidth)};`,
                fill: 'none',
            });
        },
    );
};

function generateTolerancePath(points, chartHeight, minHeight = 0) {
    const getBounds = (p) => {
        let upper = Number.isFinite(p.upperTolerance) ? p.upperTolerance : 0;
        let lower = Number.isFinite(p.lowerTolerance) ? p.lowerTolerance : chartHeight;
        const height = lower - upper;
        if (minHeight > 0 && height < minHeight) {
            const midpoint = (upper + lower) / 2;
            const halfMin = minHeight / 2;
            upper = midpoint - halfMin;
            lower = midpoint + halfMin;
        }
        return { upper, lower };
    };

    const bounds = points.map(getBounds);

    let pathString = `M ${points[0].x} ${bounds[0].upper}`;
    for (let i = 1; i < points.length; i++) {
        pathString += ` L ${points[i].x} ${bounds[i].upper}`;
    }
    for (let i = points.length - 1; i >= 0; i--) {
        pathString += ` L ${points[i].x} ${bounds[i].lower}`;
    }
    pathString += ' Z';
    return pathString;
}

function generateShadowPath(data, chartHeight) {
  const getUpper = (p) => Number.isFinite(p.upper) ? p.upper : 0;
  const getLower = (p) => Number.isFinite(p.lower) ? p.lower : chartHeight;

  let pathString = `M ${data[0].x} ${getUpper(data[0])}`;
  for (let i = 1; i < data.length; i++) {
    pathString += ` L ${data[i].x} ${getUpper(data[i])}`;
  }
  for (let i = data.length - 1; i >= 0; i--) {
    pathString += ` L ${data[i].x} ${getLower(data[i])}`;
  }
  pathString += ' Z';
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
            if (point.isPending || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
                return null;
            }

            const size = options.anomalySize || defaultAnomalyMarkerSize;
            return g(
                {
                    onmouseenter: () => options.showTooltip?.(MonitoringSparklineChartTooltip(point), point),
                    onmouseleave: () => options.hideTooltip?.(),
                },
                circle({
                    cx: point.x,
                    cy: point.y,
                    r: size,
                    fill: 'transparent',
                }),
                point.isAnomaly
                    ? rect({
                        width: size,
                        height: size,
                        x: point.x - (size / 2),
                        y: point.y - (size / 2),
                        fill: options.anomalyColor || defaultAnomalyMarkerColor,
                        style: `transform-box: fill-box; transform-origin: center;`,
                        transform: 'rotate(45)',
                        
                    })
                    : circle({
                        cx: point.x,
                        cy: point.y,
                        r: options.size || defaultMarkerSize,
                        fill: point.isTraining ? 'var(--dk-dialog-background)' : (options.color || defaultMarkerColor),
                        style: `stroke: ${options.color || defaultMarkerColor}; stroke-width: 1;`,
                    }),
            );
        }),
    );
};

/**
 * * @param {MonitoringPoint} point
 * @returns {HTMLDivElement}
 */
const MonitoringSparklineChartTooltip = (point) => {
    return div(
        {class: 'flex-column'},
        span({class: 'text-left mb-1'}, formatTimestamp(point.originalX)),
        span({class: 'text-left text-small'}, `${point.label || 'Value'}: ${formatNumber(point.originalY)}`),
        point.lowerTolerance != undefined
            ? span({class: 'text-left text-small'}, `Lower bound: ${formatNumber(point.originalLowerTolerance)}`)
            : '',
        point.upperTolerance != undefined
            ? span({class: 'text-left text-small'}, `Upper bound: ${formatNumber(point.originalUpperTolerance)}`)
            : '',
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
const defaultAnomalyMarkerSize = 8;
const defaultAnomalyMarkerColor = colorMap.red;

export { MonitoringSparklineChart, MonitoringSparklineMarkers };
