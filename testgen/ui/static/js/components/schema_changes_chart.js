/**
 * @import {ChartViewBox, Point} from './chart_canvas.js';
 * * @typedef Options
 * @type {object}
 * @property {number} lineWidth
 * @property {string} lineColor
 * @property {number} modsMarkerSize
 * @property {number} staleMarkerSize
 * @property {Point?} nestedPosition
 * @property {ChartViewBox?} viewBox
 * @property {Function?} showTooltip
 * @property {Function?} hideTooltip
 * @property {((e: SchemaEvent) => void)} onClick
 * * @typedef SchemaEvent
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
import { getValue, formatNumber } from '../utils.js';

const { div, span } = van.tags();
const { circle, g, rect, svg } = van.tags("http://www.w3.org/2000/svg");

/**
 * * @param {Options} options
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

    const currentViewBox = getValue(_options.viewBox);
    const chartHeight = currentViewBox?.height ?? getValue(_options.height) ?? 100;
    
    const maxValue = Math.ceil(Math.max(...events.map(e => Math.max(e.additions, e.deletions, e.modifications))) / 10) * 10 || 10;

    const schemaEvents = events.map(e => {
        const xPosition = e.point.x;
        const markerProps = {};
        const parts = [];

        if (_options.showTooltip) {
            markerProps.onmouseenter = () => _options.showTooltip?.(SchemaChangesChartTooltip(e), e.point);
            markerProps.onmouseleave = () => _options.hideTooltip?.();
        }

        const totalChanges = e.additions + e.deletions + e.modifications;

        if (totalChanges <= 0) {
            parts.push(circle({
                cx: xPosition,
                cy: chartHeight - (_options.staleMarkerSize * 2) - 5,
                r: _options.staleMarkerSize,
                fill: colorMap.lightGrey,
            }));
        } else {
            const barWidth = _options.lineWidth;
            const gap = 1;
            const groupWidth = (barWidth * 3) + (gap * 2);
            const startX = xPosition - (groupWidth / 2);

            const drawBar = (val, index, color) => {
                const barHeight = scale(val, {old: {min: 0, max: maxValue}, new: {min: 0, max: chartHeight}});
                const yPos = chartHeight - barHeight;

                return rect({
                    x: startX + (index * (barWidth + gap)),
                    y: yPos,
                    width: barWidth,
                    height: Math.max(barHeight, 0),
                    fill: color,
                    'shape-rendering': 'crispEdges'
                });
            };

            parts.push(drawBar(e.additions, 0, e.additions ? colorMap.blueLight : 'transparent'));
            parts.push(drawBar(e.deletions, 1, e.deletions ? colorMap.orange : 'transparent'));
            parts.push(drawBar(e.modifications, 2, e.modifications ? colorMap.purple : 'transparent'));

            if (_options.onClick && totalChanges > 0) {
                const barGroupWidth = (_options.lineWidth * 3) + 4;
                const clickableWidth = Math.max(barGroupWidth + 4, 14);
                parts.push(
                    rect({
                        width: clickableWidth,
                        height: chartHeight,
                        x: xPosition - (clickableWidth / 2),
                        y: 0,
                        fill: 'transparent',
                        style: `transform-box: fill-box; transform-origin: center; cursor: pointer;`,
                        onclick: () => _options.onClick?.(e),
                    })
                );
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
        ...schemaEvents,
    );
};

const defaultOptions = {
    lineWidth: 4,
    lineColor: colorMap.red,
    modsMarkerSize: 8,
    staleMarkerSize: 2,
    nestedPosition: {x: 0, y: 0},
};

/**
 * * @param {SchemaEvent} event
 * @returns {HTMLDivElement}
 */
const SchemaChangesChartTooltip = (event) => {
    return div(
        {class: 'flex-column'},
        span({class: 'text-left mb-1'}, formatTimestamp(event.time, false)),
        span({class: 'text-left text-small'}, `Additions: ${formatNumber(event.additions)}`),
        span({class: 'text-left text-small'}, `Deletions: ${formatNumber(event.deletions)}`),
        span({class: 'text-left text-small'}, `Modifications: ${formatNumber(event.modifications)}`),
    );
};

export { SchemaChangesChart };