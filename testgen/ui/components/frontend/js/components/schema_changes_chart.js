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
 * @property {string} lineColor
 * @property {number} modsMarkerSize
 * @property {number} staleMarkerSize
 * 
 * @typedef SchemaEvent
 * @type {object}
 * @property {number} additions
 * @property {number} deletions
 * @property {number} modifications
 * @property {string} time
 */
import van from '../van.min.js';
import { colorMap } from '../display_utils.js';
import { scale } from '../axis_utils.js';

const { circle, g, line, rect, svg, text } = van.tags("http://www.w3.org/2000/svg");

/**
 * 
 * @param {Options} options
 * @param {Array<SchemaEvent>} events
 */
const SchemaChangesChart = (options, ...events) => {
    const _options = {
        ...defaultOptions,
        ...(options ?? {}),
    };
    const origin = {x: 0, y: 0};
    const end = {x: _options.width, y: _options.height};
    const center = {x: (origin.x + end.x) / 2, y: (origin.y + end.y) / 2};
    const timeline = events.map(e => Date.parse(e.time));
    const maxAdditions = Math.ceil(Math.max(...events.map(e => e.additions)) / 10) * 10;
    const maxDeletions = Math.ceil(Math.max(...events.map(e => e.deletions)) / 10) * 10;
    const schemaEvents = events.map(e => {
        const xPosition = scale(Date.parse(e.time), {
            old: {min: Math.min(...timeline), max: Math.max(...timeline)},
            new: {min: origin.x + _options.paddingLeft, max: end.x - _options.paddingRight},
        }, origin.x);
        const yPosition = center.y;

        const parts = [];
        if ((e.additions + e.deletions + e.modifications) <= 0) {
            parts.push(circle({
                cx: xPosition,
                cy: yPosition,
                r: _options.staleMarkerSize,
                fill: colorMap.lightGrey,
            }));
        } else {
            // TODO: handle small numbers for additions and deletions
            if (e.additions > 0) {
                parts.push(line({
                    x1: xPosition,
                    y1: yPosition,
                    x2: xPosition,
                    y2: scale(e.additions, {
                        old: {min: 0, max: maxAdditions},
                        new: {min: center.y, max: origin.y },
                    }),
                    'stroke-width': _options.lineWidth,
                    'stroke': _options.lineColor,
                }));
            }

            if (e.deletions > 0) {
                parts.push(line({
                    x1: xPosition,
                    y1: yPosition,
                    x2: xPosition,
                    y2: scale(e.deletions * -1, {
                        old: {min: 0, max: maxDeletions},
                        new: {min: center.y, max: origin.y},
                    }, center.y),
                    'stroke-width': _options.lineWidth,
                    'stroke': _options.lineColor,
                }));
            }
            
            if (e.modifications > 0) {
                parts.push(
                    rect({
                        width: _options.modsMarkerSize,
                        height: _options.modsMarkerSize,
                        x: xPosition - (_options.modsMarkerSize / 2),
                        y: yPosition - (_options.modsMarkerSize / 2),
                        fill: _options.lineColor,
                        style: `transform-box: fill-box; transform-origin: center;`,
                        transform: 'rotate(45)',
                    })
                );
            }
        }

        return g(
            {},
            ...parts,
        );
    });

    return svg(
        {
            width: '100%',
            height: '100%',
            style: `overflow: visible;`,
            ...(_options.nestedPosition ? {..._options.nestedPosition} : {viewBox: `0 0 ${_options.width} ${_options.height}`}),
        },
        line({x1: origin.x, y1: _options.height / 2, x2: end.x, y2: _options.height / 2, stroke: colorMap.lightGrey }),
        ...schemaEvents,
    );
};

const /** @type Options */ defaultOptions = {
    width: 600,
    height: 200,
    paddingLeft: 16,
    paddingRight: 16,
    lineWidth: 3,
    lineColor: colorMap.red,
    modsMarkerSize: 8,
    staleMarkerSize: 4,
    nestedPosition: {x: 0, y: 0},

    // xMinSpanBetweenTicks: 10,
    // yMinSpanBetweenTicks: 10,
    // xAxisLeftPadding: 16,
    // xAxisRightPadding: 16,
    // yAxisTopPadding: 16,
    // yAxisBottomPadding: 16,
    // tooltipOffsetX: 10,
    // tooltipOffsetY: 10,
    // formatters: {
    //     x: String,
    //     y: String,
    // },
    // getters: {
    //     x: (/** @type {Point} */ item) => item.x,
    //     y: (/** @type {Point} */ item) => item.y,
    // },
};

export { SchemaChangesChart };
