/**
 * @import {ChartViewBox, Point} from './chart_canvas.js';
 * 
 * @typedef Options
 * @type {object}
 * @property {number} lineWidth
 * @property {string} lineColor
 * @property {number} modsMarkerSize
 * @property {number} staleMarkerSize
 * @property {({x1: number, y1: number, x2: number, y2: number})?} middleLine
 * @property {Point?} nestedPosition
 * @property {ChartViewBox?} viewBox
 * @property {Function?} showTooltip
 * @property {Function?} hideTooltip
 * @property {((e: SchemaEvent) => void)} onClick
 * 
 * @typedef SchemaEvent
 * @type {object}
 * @property {Point} point
 * @property {string | number} time
 * @property {number} additions
 * @property {number} deletions
 * @property {number} modifications
 * @property {string | number} window_start
 */
import van from '../van.min.js';
import { colorMap, formatTimestamp } from '../display_utils.js';
import { scale } from '../axis_utils.js';
import { getValue } from '../utils.js';

const { div, span } = van.tags();
const { circle, g, line, rect, svg } = van.tags("http://www.w3.org/2000/svg");

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

    // const origin = {x: 0, y: 0};
    // const end = {x: _options.width, y: _options.height};
    // const center = {x: (origin.x + end.x) / 2, y: (origin.y + end.y) / 2};

    const maxAdditions = Math.ceil(Math.max(...events.map(e => e.additions)) / 10) * 10;
    const maxDeletions = Math.ceil(Math.max(...events.map(e => e.deletions)) / 10) * 10;
    const schemaEvents = events.map(e => {
        const xPosition = e.point.x;
        const yPosition = e.point.y;
        const markerProps = {};

        if (_options.showTooltip) {
            markerProps.onmouseenter = () => _options.showTooltip?.(SchemaChangesChartTooltip(e), e.point);
            markerProps.onmouseleave = () => _options.hideTooltip?.();
        }

        if (_options.onClick && (e.additions + e.deletions + e.modifications) > 0) {
            markerProps.onclick = () => _options.onClick?.(e);
            markerProps.style = 'cursor: pointer;';
        }

        const parts = [];
        if ((e.additions + e.deletions + e.modifications) <= 0) {
            parts.push(circle({
                cx: xPosition,
                cy: yPosition,
                r: _options.staleMarkerSize,
                fill: colorMap.lightGrey,
            }));
        } else {
            // const modificationsY = yPosition - (_options.modsMarkerSize / 2);
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

            if (e.additions > 0) {
                let offset = 0;
                const additionsY = scale(e.additions, {old: {min: 0, max: maxAdditions}, new: {min: yPosition, max: 0 }});
                if (e.modifications > 0 && Math.abs(additionsY - yPosition) <= (_options.modsMarkerSize / 2)) {
                    offset = _options.modsMarkerSize / 2;
                }

                parts.push(line({
                    x1: xPosition,
                    y1: yPosition - offset,
                    x2: xPosition,
                    y2: additionsY - offset,
                    'stroke-width': _options.lineWidth,
                    'stroke': _options.lineColor,
                }));
            }

            if (e.deletions > 0) {
                let offset = 0;
                const deletionsY = scale(e.deletions * -1, {old: {min: 0, max: maxDeletions}, new: {min: yPosition, max: 0}}, yPosition);
                if (e.modifications > 0 && Math.abs(deletionsY - yPosition) <= (_options.modsMarkerSize / 2)) {
                    offset = _options.modsMarkerSize / 2;
                }

                parts.push(line({
                    x1: xPosition,
                    y1: yPosition + offset,
                    x2: xPosition,
                    y2: scale(e.deletions * -1, {old: {min: 0, max: maxDeletions}, new: {min: yPosition, max: 0}}, yPosition) + offset,
                    'stroke-width': _options.lineWidth,
                    'stroke': _options.lineColor,
                }));
            }
        }

        return g(
            {...markerProps},
            ...parts,
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
        () => {
            const middleLine = getValue(_options.middleLine);
            return line({ ...middleLine, stroke: colorMap.lightGrey });
        },
        ...schemaEvents,
    );
};

const /** @type Options */ defaultOptions = {
    lineWidth: 3,
    lineColor: colorMap.red,
    modsMarkerSize: 8,
    staleMarkerSize: 4,
    middleLine: undefined,
    nestedPosition: {x: 0, y: 0},
};

/**
 * 
 * @param {SchemaEvent} event
 * @returns {HTMLDivElement}
 */
const SchemaChangesChartTooltip = (event) => {
    return div(
        {class: 'flex-column'},
        span({class: 'text-left mb-1'}, formatTimestamp(event.time, false)),
        span({class: 'text-left text-small'}, `Additions: ${event.additions}`),
        span({class: 'text-left text-small'}, `Modifications: ${event.modifications}`),
        span({class: 'text-left text-small'}, `Deletions: ${event.deletions}`),
    );
};

export { SchemaChangesChart };
