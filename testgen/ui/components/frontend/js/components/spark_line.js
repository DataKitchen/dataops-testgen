/**
 * @typedef SparklineOptions
 * @type {object}
 * @property {string} color
 * @property {number} stroke
 * @property {number?} opacity
 * @property {bool?} hidden
 * @property {boolean?} interactive
 * @property {Function<void>?} onPointMouseEnter
 * @property {Function<void>?} onPointMouseLeave
 * @property {string?} testId
 * 
 * @typedef Point
 * @type {object}
 * @property {number} x
 * @property {number} y
*/
import { getValue } from '../utils.js';
import van from '../van.min.js';

const { circle, g, polyline } = van.tags("http://www.w3.org/2000/svg");
const defaultCircleRadius = 3;
const onHoverCircleRadius = 5;

/**
 * Creates a line to be redenred inside an SVG.
 * 
 * @param {SparklineOptions} options
 * @param {Array<Point>} line
 * @returns 
 */
const SparkLine = (
    /** @type {SparklineOptions} */ options,
    /** @type {Array<Point>} */ line,
) => {
    const display = van.derive(() => getValue(options.hidden) === true ? 'none' : '');
    return g(
        { fill: 'none', opacity: options.opacity ?? 1, style: 'overflow: visible;', 'data-testid': options.testId, display },
        polyline({
            points: line.map(point => `${point.x} ${point.y}`).join(', '),
            style: `stroke: ${options.color}; stroke-width: ${options.stroke ?? 1};`,
        }),
        options?.interactive
            ? line.map(point => {
                const circleRadius = van.state(defaultCircleRadius);
    
                return circle({
                    cx: point.x,
                    cy: point.y,
                    r: circleRadius,
                    'pointer-events': 'all',
                    fill: options.color,
                    onmouseenter: () => {
                        circleRadius.val = onHoverCircleRadius;
                        options?.onPointMouseEnter?.(point, line);
                    },
                    onmouseleave: () => {
                        circleRadius.val = defaultCircleRadius;
                        options?.onPointMouseLeave?.(point, line);
                    },
                });
            })
            : '',
    );
};

export { SparkLine };
