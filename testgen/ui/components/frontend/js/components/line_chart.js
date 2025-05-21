/**
 * @import { Point } from './spark_line.js';
 * 
 * @typedef TrendChartOptions
 * @type {object}
 * @property {number?} width
 * @property {number?} height
 * @property {Ticks?} ticks
 * @property {number?} xMinSpanBetweenTicks
 * @property {number?} yMinSpanBetweenTicks
 * @property {number?} padding
 * @property {number?} xAxisLeftPadding
 * @property {number?} xAxisRightPadding
 * @property {number?} yAxisTopPadding
 * @property {number?} yAxisBottomPadding
 * @property {string?} axisColor
 * @property {number?} axisWidth
 * @property {number?} tooltipOffsetX
 * @property {number?} tooltipOffsetY
 * @property {TrendChartFormatters?} formatters
 * @property {TrendChartValueGetters?} getters
 * @property {Function<string>?} lineDiscriminator
 * @property {Function<string>?} lineColor
 * @property {Function?} onShowPointTooltip
 * @property {Function?} onRefreshClicked
 * 
 * @typedef Ticks
 * @type {object}
 * @property {Array<number>} x
 * @property {Array<number>} y
 * 
 * @typedef TrendChartValueGetters
 * @type {object}
 * @property {(item: any) => number} x
 * @property {(item: any) => number} y
 * 
 * @typedef TrendChartFormatters
 * @type {object}
 * @property {(tick: number) => string} x
 * @property {(tick: number) => string} y
 * 
 * @typedef TrendLegendOptions
 * @type {object}
 * @property {Point} origin
 * @property {Point} end
 * @property {string?} refreshTooltip
 * @property {() => void} onRefreshClicked
 * @property {(lineId: string) => void} onLineClicked
 * @property {(lineId: string) => void} onLineMouseEnter
 * @property {(lineId: string) => void} onLineMouseLeave
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { colorMap } from '../display_utils.js';
import { Tooltip } from './tooltip.js';
import { SparkLine } from './spark_line.js';
import { Button } from './button.js';
import { scale } from '../axis_utils.js';

const { div, i, span } = van.tags();
const { circle, foreignObject, g, line, polyline, svg, text } = van.tags("http://www.w3.org/2000/svg");

/**
 * Draws 2D coordinate system and sparklines inside.
 * 
 * @param {TrendChartOptions} options
 * @param {Array<object> | Array<Point>} values
 */
const LineChart = (
    options,
    ...values
) => {
    const _options = {
        ...defaultOptions,
        ...(options ?? {}),
    };
    const variables = {
        'axis-color': _options.axisColor,
        'axis-width': _options.axisWidth,
        'line-width': _options.lineWidth,
    };
    const style = Object.entries(variables).map(([key, value]) => `--${key}: ${value}`).join(';');
    const origin = {x: _options.padding, y: _options.padding};
    const end = {x: _options.width - _options.padding, y: _options.height - _options.padding};
    const xAxis = {x1: origin.x, y1: end.y, x2: end.x, y2: end.y};
    const yAxis = {x1: end.x, y1: origin.y, x2: end.x, y2: end.y};

    let /** @type {Array<number>} */ xValues = _options.ticks?.x;
    let /** @type {Array<number>} */ yValues = _options.ticks?.y;

    if (!xValues) {
        xValues = Array.from(values.reduce((set, v) => set.add(_options.getters.x(v)), new Set()))
            .sort((a, b) => a - b);
    }

    if (!yValues) {
        yValues = Array.from(values.reduce((set, v) => set.add(_options.getters.y(v)), new Set()))
            .sort((a, b) => a - b);
    }

    const xTicks = xValues.filter((value, idx, ticks) => {
        return idx === 0 || ((value - ticks[idx - 1]) >= _options.xMinSpanBetweenTicks);
    }).map((value) => ({ value, label: _options.formatters.x(value) }));
    const yTicks = yValues.filter((value, idx, ticks) => {
        return idx === 0 || ((value - ticks[idx - 1]) >= _options.yMinSpanBetweenTicks);
    }).map((value) => ({ value, label: _options.formatters.y(value) }));

    const asSVGX = (/** @type {number} */ value) => {
        return scale(value, {
            old: {min: Math.min(...xValues), max: Math.max(...xValues)},
            new: {min: origin.x + _options.xAxisLeftPadding, max: end.x - _options.xAxisRightPadding},
        }, origin.x + _options.xAxisLeftPadding);
    };
    const asSVGY = (/** @type {number} */ value) => {
        return _options.height - scale(value, {
            old: {min: Math.min(...yValues), max: Math.max(...yValues)},
            new: {min: origin.y + _options.yAxisBottomPadding, max: end.y - _options.yAxisTopPadding},
        }, end.y - _options.yAxisTopPadding);
    };

    const lines = values
        .map(v => ({...v, x: asSVGX(_options.getters.x(v)), y: asSVGY(_options.getters.y(v))}))
        .reduce((lines, value) => {
            const lineId = _options.lineDiscriminator(value);
            if (!Object.keys(lines).includes(String(lineId))) {
                lines[lineId] = [];
            }
            lines[lineId].push(value);
            return lines;
        }, {});
    const linesStates = Object.keys(lines).reduce((result, lineId) => ({
        ...result,
        [lineId]: {
            dimmed: van.state(false),
            hidden: van.state(false),
        },
    }), {});
    const linesOpacity = Object.entries(linesStates).reduce((result, [lineId, {dimmed, hidden}]) => ({
        ...result,
        [lineId]: van.derive(() => (getValue(dimmed) || getValue(hidden)) ? 0.2 : 1.0),
    }), {});

    function dimAllExcept(lineId) {
        if (linesStates[lineId].hidden.val) {
            return;
        }

        Object.values(linesStates).forEach(states => states.dimmed.val = true);
        linesStates[lineId].dimmed.val = false;
    }

    function resetDimmedLines() {
        Object.values(linesStates).forEach(states => states.dimmed.val = false);
    }

    function toggleLineVisibility(lineId) {
        linesStates[lineId].hidden.val = !linesStates[lineId].hidden.val;
    }

    const tooltipText = van.state('');
    const showTooltip = van.state(false);
    const tooltipExtraStyle = van.state('');
    const tooltip = Tooltip({
        text: tooltipText,
        show: showTooltip,
        position: '--',
        style: tooltipExtraStyle,
    });

    return svg(
        {
            width: '100%',
            height: '100%',
            viewBox: `0 0 ${_options.width} ${_options.height}`,
            style: `${style}; overflow: visible;`,
        },

        Legend(
            {
                origin,
                end,
                refreshTooltip: 'Recalculate Trend',
                onLineMouseEnter: dimAllExcept,
                onLineMouseLeave: resetDimmedLines,
                onLineClicked: toggleLineVisibility,
                onRefreshClicked: _options.onRefreshClicked,
            },
            Object.entries(lines).map(([lineId, _], idx) => ({ id: lineId, color: _options.lineColor(lineId, idx), opacity: linesOpacity[lineId] })),
        ),

        line({...xAxis, style: 'stroke: var(--axis-color); stroke-width: var(--axis-width)'}),
        xTicks.map(({ value }) => circle({ cx: asSVGX(value), cy: end.y, r: 2, 'pointer-events': 'none', fill: 'var(--axis-color)' })),
        xTicks.map(({ value, label }) => {
            const dx = Math.max(5, label.length * 5.5 / 2);
            return text({x: asSVGX(value), y: end.y, dx: -dx, dy: 20, style: 'stroke: var(--axis-color); stroke-width: .1; fill: var(--axis-color);' }, label);
        }),

        line({...yAxis, style: 'stroke: var(--axis-color); stroke-width: var(--axis-width)'}),
        yTicks.map(({ value, label }) => text({
            x: end.x,
            y: asSVGY(value),
            dx: 5,
            dy: 5,
            style: 'stroke: var(--axis-color); stroke-width: .1; fill: var(--axis-color);' },
            label,
        )),

        Object.entries(lines).map(([lineId, line], idx) =>
            SparkLine(
                {
                    color: _options.lineColor(lineId, idx),
                    stroke: _options.lineWidth,
                    opacity: linesOpacity[lineId],
                    hidden: linesStates[lineId].hidden,
                    interactive: _options.onShowPointTooltip != undefined,
                    onPointMouseEnter: (point, line) => {
                        tooltipText.val = _options.onShowPointTooltip?.(point, line);
                        tooltipExtraStyle.val = `transform: translate(${point.x + _options.tooltipOffsetX}px, ${point.y + _options.tooltipOffsetY}px);`;
                        showTooltip.val = true;
                    },
                    onPointMouseLeave: () => {
                        tooltipText.val = '';   
                        tooltipExtraStyle.val = '';
                        showTooltip.val = false;
                    },
                    testId: lineId,
                },
                line,
            )
        ),

        _options.onShowPointTooltip
            ? foreignObject({fill: 'none', width: '100%', height: '100%', 'pointer-events': 'none', style: 'overflow: visible;'}, tooltip)
            : '',
    );
};

/**
 * Renders a representation of each line displayed in the chart and allows reacting to events on each.
 * 
 * @param {TrendLegendOptions} options
 * @param {Array<{lineId: string, color: string, opacity: number}>} lines
 */
const Legend = (options, lines) => {
    const title = 'Score Trend';
    const lineLength = 15;
    const lineHeight = 4;

    return foreignObject(
        {
            x: 0,
            y: 0,
            width: '100%',
            height: '40',
            overflow: 'visible',
        },
        div(
            {class: 'flex-row pt-2 pl-6 pr-6'},
            span({class: 'mr-1 text-secondary', style: 'font-size: 16px; font-weight: 500;'}, title),
            options?.onRefreshClicked ?
                Button({
                    type: 'icon',
                    icon: 'refresh',
                    style: 'width: 32px; height: 32px;',
                    tooltip: options?.refreshTooltip || null,
                    onclick: options?.onRefreshClicked,
                    'data-testid': 'refresh-history',
                })
                : null,
            div(
                {class: 'flex-row ml-7', style: 'margin-right: auto;'},
                ...lines.map((line) =>
                    div(
                        {
                            class: 'flex-row clickable mr-3',
                            style: () => `opacity: ${getValue(line.opacity)}`,
                            onclick: () => options?.onLineClicked(line.id),
                            onmouseenter: () => options?.onLineMouseEnter(line.id),
                            onmouseleave: () => options?.onLineMouseLeave(line.id),
                        },
                        i({style: `width: ${lineLength}px; height: ${lineHeight}px; background: ${line.color}; display: block; margin-right: 2px; border-radius: 10px;`}),
                        span({class: 'text-caption'}, line.id),
                    )
                ),
            ),
        )
    );
};

const defaultOptions = {
    width: 600,
    height: 200,
    padding: 32,
    xMinSpanBetweenTicks: 10,
    yMinSpanBetweenTicks: 10,
    xAxisLeftPadding: 16,
    xAxisRightPadding: 16,
    yAxisTopPadding: 16,
    yAxisBottomPadding: 16,
    axisColor: colorMap.grey,
    axisWidth: 2,
    lineWidth: 3,
    tooltipOffsetX: 10,
    tooltipOffsetY: 10,
    formatters: {
        x: String,
        y: String,
    },
    getters: {
        x: (/** @type {Point} */ item) => item.x,
        y: (/** @type {Point} */ item) => item.y,
    },
    lineDiscriminator: (/** @type {Point} */ item) => '0',
    lineColor: (lineId, idx) => ['blue', 'green', 'yellow', 'brown'][idx] ?? 'grey',
};

export { LineChart };
