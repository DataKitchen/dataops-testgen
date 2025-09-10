/**
 * @import {FreshnessEvent} from '../components/freshness_chart.js';
 * @import {SchemaEvent} from '../components/schema_changes_chart.js';
 * @import {MonitoringEvent} from '../components/monitoring_sparkline.js';
 * 
 * @typedef LineChart
 * @type {object}
 * @property {string} label
 * @property {MonitoringEvent[]} events
 * 
 * @typedef Properties
 * @type {object}
 * @property {FreshnessEvent[]} freshness_events
 * @property {MonitoringEvent[]} volume_events
 * @property {SchemaEvent[]} schema_change_events
 * @property {LineChart[]} line_charts
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { FreshnessChart } from '../components/freshness_chart.js';
import { colorMap, formatNumber } from '../display_utils.js';
import { SchemaChangesChart } from '../components/schema_changes_chart.js';
import { MonitoringSparklineChart } from '../components/monitoring_sparkline.js';
import { scale } from '../axis_utils.js';

const { div } = van.tags;
const { circle, clipPath, defs, g, line, rect, svg, text } = van.tags("http://www.w3.org/2000/svg");

const spacing = 8;
const chartsWidth = 700;
const fresshnessChartHeight = 25;
const volumeChartHeight = 80;
const schemaChartHeight = 80;
const lineChartHeight = 60;
const paddingLeft = 16;
const paddingRight = 16;
const timeTickFormatter = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    hour12: true,
});

/**
 * 
 * @param {Properties} props
 */
const TableMonitoringTrend = (props) => {
    loadStylesheet('table-monitoring-trends', stylesheet);
    Streamlit.setFrameHeight(1);
    
    const domId = 'monitoring-trends-container';
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    const freshnessEvents = getValue(props.freshness_events) ?? [];
    const volumeEvents = getValue(props.volume_events) ?? [];
    const schemaChangeEvents = getValue(props.schema_change_events) ?? [];
    const lineCharts = getValue(props.line_charts) ?? [];

    const volumeChangesValues = volumeEvents.map(e => e.value);
    const volumeChangesRange = [volumeChangesValues.length > 0 ? Math.min(...volumeChangesValues) : 0, volumeChangesValues.length > 0 ? Math.max(...volumeChangesValues) : 100000];
    const schemaChangesMaxValue = schemaChangeEvents.reduce((currentValue, e) => Math.max(currentValue, e.additions, e.deletions), 10);

    const chartHeight = (
        + (spacing * 2)
        + fresshnessChartHeight
        + (spacing * 3)
        + volumeChartHeight
        + (spacing * 3)
        + schemaChartHeight
        + (spacing * 3)
        + (lineChartHeight * lineCharts.length)
        + ((spacing * 3) * lineCharts.length - 1)
        + (spacing * 2) // padding
    );

    const origin = {x: paddingLeft, y: chartHeight + spacing};
    const end = {x: chartsWidth - paddingRight, y: chartHeight - spacing};

    let verticalPosition = 0;
    const positionTracking = {};
    const nextPosition = (options) => {
        verticalPosition += (options.spaces ?? 1) * spacing + (options.offset ?? 0);
        if (options.name) {
            positionTracking[options.name] = verticalPosition;
        }
        return verticalPosition;
    };

    const rawTimeline = [
        ...freshnessEvents,
        ...volumeEvents,
        ...schemaChangeEvents,
        ...lineCharts.reduce((all, chart) => [...all, ...chart.events], []),
    ].map(e => Date.parse(e.time)).sort();
    const timeline = getTimelineTicks(rawTimeline);

    return div(
        {
            id: domId,
            class: 'table-monitoring-trend-wrapper p-5',
            style: 'padding-left: 96px;'
        },
        svg(
            {
                width: '100%',
                height: '100%',
                viewBox: `0 0 ${chartsWidth} ${chartHeight}`,
                style: `overflow: visible;`,
            },

            text({x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small'}, 'Freshness'),
            FreshnessChart(
                {width: chartsWidth, height: fresshnessChartHeight, nestedPosition: {x: 0, y: nextPosition({ name: 'freshnessChart' })}},
                ...freshnessEvents,
            ),

            DividerLine(nextPosition({ offset: fresshnessChartHeight }), end),

            text({x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small'}, 'Volume'),
            MonitoringSparklineChart(
                {width: chartsWidth, height: volumeChartHeight, lineWidth: 2, nestedPosition: {x: 0, y: nextPosition({ name: 'volumeChart' })}},
                ...volumeEvents,
            ),

            DividerLine(nextPosition({ offset: volumeChartHeight }), end),

            text({x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small'}, 'Schema'),
            SchemaChangesChart(
                {width: chartsWidth, height: schemaChartHeight, nestedPosition: {x: 0, y: nextPosition({ name: 'schemaChangesChart' })}},
                ...schemaChangeEvents,
            ),

            lineCharts.map(({ label, events }, idx) => [
                DividerLine(nextPosition({ offset: idx === 0 ? schemaChartHeight : lineChartHeight }), end),

                text({x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small'}, label),

                // TODO: add support for threshold failure
                MonitoringSparklineChart(
                    {width: chartsWidth, height: lineChartHeight, lineWidth: 2, yAxisTicks: [0, 1000], nestedPosition: {x: 0, y: nextPosition({ name: `lineChart${idx}` })}},
                    ...events,
                ),
            ]),

            g(
                {},
                rect({
                    width: chartsWidth,
                    height: chartHeight,
                    x: 0,
                    y: 0,
                    rx: 4,
                    ry: 4,
                    stroke: colorMap.lightGrey,
                    fill: 'transparent',
                }),

                timeline.map((value, idx) => {
                    const label = timeTickFormatter.format(new Date(value));
                    const xPosition = scale(value, {
                        old: {min: Math.min(...rawTimeline), max: Math.max(...rawTimeline)},
                        new: {min: origin.x, max: end.x},
                    }, origin.x);

                    return g(
                        {},
                        defs(
                            clipPath(
                                {id: `xTickClip-${idx}`},
                                rect({ x: xPosition, y: -4, width: 4, height: 4 }),
                            ),
                        ),

                        rect({
                            x: xPosition,
                            y: -4,
                            width: 4,
                            height: 8,
                            rx: 2,
                            ry: 1,
                            fill: colorMap.lightGrey,
                            'clip-path': `url(#xTickClip-${idx})`,
                        }),

                        text(
                            {
                                x: xPosition,
                                y: 0,
                                dx: -30,
                                dy: -8,
                                fill: colorMap.grey,
                                'stroke-width': .1,
                                style: `font-size: 10px;`,
                            },
                            label,
                        ),
                    );
                }),

                // Freshness Chart Y axis
                g(
                    {transform: `translate(-70, ${positionTracking.freshnessChart + (fresshnessChartHeight / 2) - 35 /* ~ height of this element */})`},
                    g(
                        {transform: 'translate(0,20)'},
                        circle({
                            r: 4,
                            cx: 0,
                            cy: -4,
                            fill: colorMap.green,
                        }),
                        text({x: 10, y: 0, class: 'text-small', fill: 'var(--caption-text-color)'}, 'Update'),
                    ),
                    g(
                        {transform: 'translate(0,40)'},
                        rect({
                            x: -3,
                            y: -7,
                            width: 7,
                            height: 7,
                            fill: colorMap.red,
                            style: `transform-box: fill-box; transform-origin: center;`,
                            transform: 'rotate(45)',
                        }),
                        text({x: 10, y: 0, class: 'text-small', fill: 'var(--caption-text-color)'}, 'No update'),
                    ),
                ),

                // Volume Chart Y axis
                g(
                    {transform: `translate(-100, ${positionTracking.volumeChart + (volumeChartHeight / 2)})`},
                    text({x: 50, y: -35, class: 'text-small', fill: 'var(--caption-text-color)'}, formatNumber(volumeChangesRange[1])),
                    text({x: 50, y: 35, class: 'text-small', fill: 'var(--caption-text-color)'}, formatNumber(volumeChangesRange[0])),
                ),

                // Schema Chart Y axis
                g(
                    {transform: `translate(-90, ${positionTracking.schemaChangesChart + (schemaChartHeight / 2)})`},
                    text({x: 65, y: -35, class: 'text-small', fill: 'var(--caption-text-color)'}, schemaChangesMaxValue),
                    text({x: 30, y: -20, class: 'text-small', fill: 'var(--caption-text-color)'}, 'Adds'),
                    g(
                        {},
                        rect({
                            x: -3,
                            y: -7,
                            width: 7,
                            height: 7,
                            fill: colorMap.red,
                            style: `transform-box: fill-box; transform-origin: center;`,
                            transform: 'rotate(45)',
                        }),
                        text({x: 10, y: 0, class: 'text-small', fill: 'var(--caption-text-color)'}, 'Modifications'),
                    ),
                    text({x: 17, y: 20, class: 'text-small', fill: 'var(--caption-text-color)'}, 'Deletes'),

                    text({x: 65, y: 35, class: 'text-small', fill: 'var(--caption-text-color)'}, schemaChangesMaxValue),
                ),

                // Line Charts Y axis
                lineCharts.map((_, idx) => g(
                    {transform: `translate(-70, ${positionTracking[`lineChart${idx}`] + (lineChartHeight / 2)})`},
                    text({x: 35, y: -20, class: 'text-small', fill: 'var(--caption-text-color)'}, '1000'),
                    text({x: 55, y: 20, class: 'text-small', fill: 'var(--caption-text-color)'}, '0'),
                )),
            ),
        ),
    );
};

/**
 * @param {number} position
 * @param {Point} end
 */
const DividerLine = (position, end) => {
    return line({x1: 0, y1: position, x2: end.x + paddingRight, y2: position, stroke: colorMap.lightGrey });
}

/**
 * @param {number[]} timeline
 * @returns {number[]}
 */
function getTimelineTicks(timeline) {
    const datetimes = [];
    const minTimestamp = Math.min(...timeline);
    const maxTimestamp = Math.max(...timeline);

    let interval = {unit: 'days', value: 1};
    if (maxTimestamp - minTimestamp <= 2 * 24 * 60 * 60 * 1000) {
        interval = {unit: 'hours', value: 5};
    }

    datetimes.push(minTimestamp);
    let currentTimestamp = addInterval(minTimestamp, interval);
    while (currentTimestamp < maxTimestamp) {
        datetimes.push(currentTimestamp);
        currentTimestamp = addInterval(currentTimestamp, interval).getTime();
    }
    datetimes.push(maxTimestamp);

    return datetimes;
}

/**
 * @typedef Interval
 * @type {object}
 * @property {'days'|'hours'} unit
 * @property {number} value
 *
 * @param {number} timestamp
 * @param {Interval} interval
 */
function addInterval(timestamp, interval) {
    let currentDate = new Date(timestamp);
    if (interval.unit === 'days') {
        currentDate.setDate(currentDate.getDate() + interval.value);
    } else if (interval.unit === 'hours') {
        currentDate.setHours(currentDate.getHours() + interval.value);
    }
    return currentDate;
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
`);

export { TableMonitoringTrend };
