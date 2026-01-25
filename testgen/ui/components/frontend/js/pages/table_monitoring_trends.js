/**
 * @import {Point} from '../components/chart_canvas.js';
 * @import {FreshnessEvent} from '../components/freshness_chart.js';
 * @import {SchemaEvent} from '../components/schema_changes_chart.js';
 * @import {DataStructureLog} from '../components/schema_changes_list.js';
 * 
 * @typedef VolumeTrendEvent
 * @type {object}
 * @property {number} time
 * @property {number} record_count
 * 
 * @typedef MetricPrediction
 * @type {object}
 * @property {PredictionSet} volume_trend
 * 
 * @typedef PredictionSet
 * @type {object}
 * @property {object} mean
 * @property {object} lower_tolerance
 * @property {object} upper_tolerance
 * 
 * @typedef Properties
 * @type {object}
 * @property {FreshnessEvent[]} freshness_events
 * @property {VolumeTrendEvent[]} volume_events
 * @property {SchemaEvent[]} schema_events
 * @property {(DataStructureLog[])?} data_structure_logs
 * @property {MetricPrediction?} predictions
 */
import van from '/app/static/js/van.min.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { emitEvent, getValue, loadStylesheet, parseDate, isEqual } from '/app/static/js/utils.js';
import { FreshnessChart, getFreshnessEventColor } from '/app/static/js/components/freshness_chart.js';
import { colorMap } from '/app/static/js/display_utils.js';
import { SchemaChangesChart } from '/app/static/js/components/schema_changes_chart.js';
import { SchemaChangesList } from '/app/static/js/components/schema_changes_list.js';
import { getAdaptiveTimeTicks, scale } from '/app/static/js/axis_utils.js';
import { Tooltip } from '/app/static/js/components/tooltip.js';
import { DualPane } from '/app/static/js/components/dual_pane.js';
import { Button } from '/app/static/js/components/button.js';
import { MonitoringSparklineChart, MonitoringSparklineMarkers } from '/app/static/js/components/monitoring_sparkline.js';

const { div, span } = van.tags;
const { circle, clipPath, defs, foreignObject, g, line, rect, svg, text } = van.tags("http://www.w3.org/2000/svg");

const spacing = 8;
const chartsWidth = 700;
const chartsYAxisWidth = 104;
const fresshnessChartHeight = 25;
const schemaChartHeight = 80;
const volumeTrendChartHeight = 80;
const paddingLeft = 16;
const paddingRight = 16;
const timeTickFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  hour12: true,
});

/**
 * @param {Properties} props
 */
const TableMonitoringTrend = (props) => {
  window.testgen.isPage = true;
  loadStylesheet('table-monitoring-trends', stylesheet);

  const domId = 'monitoring-trends-container';

  const chartHeight = (
    + (spacing * 2)
    + fresshnessChartHeight
    + (spacing * 3)
    + volumeTrendChartHeight
    + (spacing * 3)
    + schemaChartHeight
    // + (spacing * 3)
    // + (lineChartHeight * lineCharts.length)
    // + ((spacing * 3) * lineCharts.length - 1)
    + (spacing * 3) // padding
  );

  const origin = { x: chartsYAxisWidth + paddingLeft, y: chartHeight + spacing };
  const end = { x: chartsWidth + chartsYAxisWidth - paddingRight, y: chartHeight - spacing };

  let verticalPosition = 0;
  const positionTracking = {};
  const nextPosition = (options) => {
    verticalPosition += (options.spaces ?? 1) * spacing + (options.offset ?? 0);
    if (options.name) {
      positionTracking[options.name] = verticalPosition;
    }
    return verticalPosition;
  };

  const predictions = getValue(props.predictions);
  const predictionTimes = Object.values(predictions ?? {}).reduce((predictionTimes, v) => [
    ...predictionTimes,
    ...Object.keys(v.mean).map(t => ({time: +t}))
  ], []);
  const freshnessEvents = (getValue(props.freshness_events) ?? []).map(e => ({ ...e, time: parseDate(e.time) }));
  const schemaChangeEvents = (getValue(props.schema_events) ?? []).map(e => ({ ...e, time: parseDate(e.time), window_start: parseDate(e.window_start) }));

  let volumeTrendEvents = (getValue(props.volume_events) ?? []).map(e => ({ ...e, time: parseDate(e.time) }));
  if (predictions.volume_trend) {
    for (const [time, records] of Object.entries(predictions.volume_trend.mean)) {
      volumeTrendEvents.push({
        time: +time,
        record_count: parseInt(records),
      });
    }
  }

  const allTimes = [...freshnessEvents, ...schemaChangeEvents, ...volumeTrendEvents, ...predictionTimes].map(e => e.time);
  const rawTimeline = [...new Set(allTimes)].sort();
  const dateRange = { min: rawTimeline[0], max: rawTimeline[rawTimeline.length - 1] };
  const timeline = [
    dateRange.min,
    ...getAdaptiveTimeTicks(rawTimeline.slice(2, rawTimeline.length - 2), 5, 8),
    dateRange.max,
  ];

  const parsedFreshnessEvents = freshnessEvents.map((e) => ({
    changed: e.changed,
    expected: e.expected,
    status: e.status,
    time: e.time,
    point: {
      x: scale(e.time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
      y: fresshnessChartHeight / 2,
    },
  }));
  const freshessChartLegendItems = Object.values(parsedFreshnessEvents.reduce((legendItems, e, idx) => {
    const itemColor = getFreshnessEventColor(e);
    const key = `${e.changed}-${itemColor}`;
    if (!legendItems[key]) {
      const position = `translate(0,${20 * (Object.keys(legendItems).length + 1)})`;
      legendItems[key] = e.changed
        ? g(
          { transform: position },
          circle({
            r: 4,
            cx: 0,
            cy: -4,
            fill: itemColor,
          }),
          text({ x: 10, y: 0, class: 'text-small', fill: 'var(--caption-text-color)' }, 'Update'),
        )
        : g(
          { transform: position },
          rect({
            x: -3,
            y: -7,
            width: 7,
            height: 7,
            fill: itemColor,
            style: `transform-box: fill-box; transform-origin: center;`,
            transform: 'rotate(45)',
          }),
          text({ x: 10, y: 0, class: 'text-small', fill: 'var(--caption-text-color)' }, 'No update'),
        );
    }
    return legendItems;
  }, {}));
  if (freshessChartLegendItems.length === 0) {
    freshessChartLegendItems.push(
      g(
        { transform: 'translate(0,20)' },
        circle({
          r: 4,
          cx: 0,
          cy: -4,
          fill: colorMap.green,
        }),
        text({ x: 10, y: 0, class: 'text-small', fill: 'var(--caption-text-color)' }, 'Update'),
      ),
      g(
        { transform: 'translate(0,40)' },
        rect({
          x: -3,
          y: -7,
          width: 7,
          height: 7,
          fill: colorMap.red,
          style: `transform-box: fill-box; transform-origin: center;`,
          transform: 'rotate(45)',
        }),
        text({ x: 10, y: 0, class: 'text-small', fill: 'var(--caption-text-color)' }, 'No update'),
      ),
    );
  }

  const parsedSchemaChangeEvents = schemaChangeEvents.map((e) => ({
    time: e.time,
    additions: e.additions,
    deletions: e.deletions,
    modifications: e.modifications,
    window_start: e.window_start,
    point: {
      x: scale(e.time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
      y: schemaChartHeight / 2,
    },
  }));
  const schemaChangesMaxValue = schemaChangeEvents.reduce((currentValue, e) => Math.max(currentValue, e.additions, e.deletions), 10);

  const shouldShowSidebar = van.state(false);
  const schemaChartSelection = van.state(null);
  van.derive(() => shouldShowSidebar.val = (getValue(props.data_structure_logs)?.length ?? 0) > 0);

  const volumes = [
    ...volumeTrendEvents.map((e) => e.record_count),
    ...Object.keys(predictions?.volume_trend?.mean ?? {}).reduce((values, time) => [
      ...values,
      parseInt(predictions.volume_trend.upper_tolerance[time]),
      parseInt(predictions.volume_trend.lower_tolerance[time]),
    ], []),
  ];
  const volumeRange = {min: Math.min(...volumes), max: Math.max(...volumes)};
  if (volumeRange.min === volumeRange.max) {
    volumeRange.max = volumeRange.max + 100;
  }
  const parsedVolumeTrendEvents = volumeTrendEvents.map((e) => ({
    originalX: e.time,
    originalY: e.record_count,
    x: scale(e.time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
    y: scale(e.record_count, { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight),
  }));
  let parsedVolumeTrendPredictionPoints = Object.keys(predictions?.volume_trend?.mean ?? {}).map((time) => ({
    x: scale(+time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
    upper: scale(parseInt(predictions.volume_trend.upper_tolerance[time]), { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight),
    lower: scale(parseInt(predictions.volume_trend.lower_tolerance[time]), { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight),
  })).filter(p => p.x != undefined && p.upper != undefined && p.lower != undefined);

  let tooltipText = '';
  const shouldShowTooltip = van.state(false);
  const tooltipExtraStyle = van.state('');
  const /** @type {HTMLDivElement} */ tooltipWrapperElement = foreignObject(
    { fill: 'none', width: '100%', height: '100%', 'pointer-events': 'none', style: 'overflow: visible; position: absolute;' },
    () => {
      const show = shouldShowTooltip.val;
      const style = tooltipExtraStyle.val;

      return Tooltip({
        text: tooltipText,
        position: '--',
        show,
        style,
      });
    },
  );
  const showTooltip = (verticalOffset, message, point) => {
    let timeout;

    tooltipText = message;
    tooltipExtraStyle.val = 'visibility: hidden;';
    shouldShowTooltip.val = true;

    timeout = setTimeout(() => {
      const tooltipRect = tooltipWrapperElement.querySelector('.tg-tooltip').getBoundingClientRect();
      const tooltipRectWidth = tooltipRect.width;
      const tooltipRectHeight = tooltipRect.height;

      let tooltipX = point.x + 10;
      let tooltipY = point.y + verticalOffset + 10;

      if ((tooltipX + tooltipRectWidth) >= (chartsWidth + chartsYAxisWidth)) {
        tooltipX = point.x - tooltipRect.width - 10;
      }

      if (tooltipY + tooltipRectHeight >= (chartHeight - spacing)) {
        tooltipY = (point.y + verticalOffset) - tooltipRectHeight - 10;
      }

      tooltipExtraStyle.val = `transform: translate(${tooltipX}px, ${tooltipY}px);`;

      clearTimeout(timeout);
    }, 0);
  };
  const hideTooltip = () => {
    shouldShowTooltip.val = false;
    tooltipExtraStyle.val = '';
    tooltipText = '';
  };

  const getDataStructureLogs = (/** @type {SchemaEvent} */ event) => {
    emitEvent('ShowDataStructureLogs', { payload: { start_time: event.window_start, end_time: event.time } });
    shouldShowSidebar.val = true;
    schemaChartSelection.val = event;
  };

  return DualPane(
    {
      id: domId,
      class: () => `table-monitoring-trend-wrapper ${shouldShowSidebar.val ? 'has-sidebar' : ''}`,
      minSize: 150,
      maxSize: 400,
      resizablePanel: 'right',
      resizablePanelDomId: 'data-structure-logs-sidebar',
    },
    div(
      { class: '', style: 'width: 100%;' },
      svg(
        {
          id: 'monitoring-trends-charts-svg',
          viewBox: `0 0 ${chartsWidth + chartsYAxisWidth} ${chartHeight}`,
          style: `overflow: visible;`,
        },

        text({ x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small', fill: 'var(--primary-text-color)' }, 'Freshness'),
        FreshnessChart(
          {
            width: chartsWidth,
            height: fresshnessChartHeight,
            lineHeight: fresshnessChartHeight,
            nestedPosition: { x: 0, y: nextPosition({ name: 'freshnessChart' }) },
            showTooltip: showTooltip.bind(null, 0 + fresshnessChartHeight / 2),
            hideTooltip,
          },
          ...parsedFreshnessEvents,
        ),
        DividerLine({ x: origin.x - paddingLeft, y: nextPosition({ offset: fresshnessChartHeight }) }, end),

        text({ x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small', fill: 'var(--primary-text-color)' }, 'Volume'),
        MonitoringSparklineChart(
          {
            width: chartsWidth,
            height: schemaChartHeight,
            nestedPosition: { x: 0, y: nextPosition({ name: 'volumeTrendChart' }) },
            lineWidth: 2,
            attributes: {style: 'overflow: visible;'},
            prediction: parsedVolumeTrendPredictionPoints,
          },
          ...parsedVolumeTrendEvents,
        ),
        MonitoringSparklineMarkers(
          {
            color: 'transparent',
            transform: `translate(0, ${positionTracking.volumeTrendChart})`,
            showTooltip: showTooltip.bind(null, 0 + volumeTrendChartHeight / 2),
            hideTooltip,
          },
          parsedVolumeTrendEvents,
        ),
        DividerLine({ x: origin.x - paddingLeft, y: nextPosition({ offset: volumeTrendChartHeight }) }, end),

        // Schema Chart Selection Highlight
        () => {
          const selection = schemaChartSelection.val;
          if (selection) {
            const width = 10;
            const height = schemaChartHeight + 3 * spacing;
            return rect({
              width: width,
              height: height,
              x: selection.point.x - (width / 2),
              y: selection.point.y + positionTracking.schemaChangesChart - 1.5 * spacing - (height / 2),
              fill: colorMap.empty,
              style: `transform-box: fill-box; transform-origin: center;`,
            });
          }

          return g();
        },
        text({ x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small', fill: 'var(--primary-text-color)' }, 'Schema'),
        SchemaChangesChart(
          {
            width: chartsWidth,
            height: schemaChartHeight,
            middleLine: { x1: origin.x - paddingLeft, y1: schemaChartHeight / 2, x2: end.x + paddingRight, y2: schemaChartHeight / 2 },
            nestedPosition: { x: 0, y: nextPosition({ name: 'schemaChangesChart' }) },
            onClick: getDataStructureLogs,
            showTooltip: showTooltip.bind(null, positionTracking.schemaChangesChart + schemaChartHeight / 2),
            hideTooltip,
          },
          ...parsedSchemaChangeEvents,
        ),

        g(
          {},
          rect({
            width: chartsWidth,
            height: chartHeight,
            x: origin.x - paddingLeft,
            y: 0,
            rx: 4,
            ry: 4,
            stroke: colorMap.lightGrey,
            fill: 'transparent',
            style: 'pointer-events: none;'
          }),

          timeline.map((value, idx) => {
            const label = timeTickFormatter.format(new Date(value));
            const xPosition = scale(value, {
              old: dateRange,
              new: { min: origin.x, max: end.x },
            }, origin.x);

            return g(
              {},
              defs(
                clipPath(
                  { id: `xTickClip-${idx}` },
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
            { transform: `translate(24, ${positionTracking.freshnessChart + (fresshnessChartHeight / 2) - 35})` },
            ...freshessChartLegendItems,
          ),

          // Volume Chart Y axis
          g(
            { transform: `translate(40, ${positionTracking.volumeTrendChart + (volumeTrendChartHeight / 2)})` },
            text({ x: 60, y: 35, class: 'text-small', 'text-anchor': 'end', fill: 'var(--caption-text-color)' }, volumeRange.min),
            text({ x: 60, y: -35, class: 'text-small', 'text-anchor': 'end', fill: 'var(--caption-text-color)' }, volumeRange.max),
          ),

          // Schema Chart Y axis
          g(
            { transform: `translate(10, ${positionTracking.schemaChangesChart + (schemaChartHeight / 2)})` },
            text({ x: 65, y: -35, class: 'text-small', fill: 'var(--caption-text-color)' }, schemaChangesMaxValue),
            text({ x: 30, y: -20, class: 'text-small', fill: 'var(--caption-text-color)' }, 'Adds'),
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
              text({ x: 12, y: 0, class: 'text-small', fill: 'var(--caption-text-color)' }, 'Modifications'),
            ),
            text({ x: 17, y: 20, class: 'text-small', fill: 'var(--caption-text-color)' }, 'Deletes'),

            text({ x: 65, y: 35, class: 'text-small', fill: 'var(--caption-text-color)' }, schemaChangesMaxValue),
          ),
        ),
        tooltipWrapperElement,
      ),
    ),

    () => {
      const _shouldShowSidebar = shouldShowSidebar.val;
      const selection = schemaChartSelection.val;
      if (!_shouldShowSidebar) {
        return span();
      }

      return div(
        { id: 'data-structure-logs-sidebar', class: 'flex-column data-structure-logs-sidebar' },
        SchemaChangesList({
          data_structure_logs: props.data_structure_logs,
          window_start: selection.window_start,
          window_end: selection.time,
        }),
        Button({
          label: 'Hide',
          style: 'margin-top: 8px; width: auto; align-self: flex-end;',
          icon: 'double_arrow',
          onclick: () => {
            shouldShowSidebar.val = false;
            schemaChartSelection.val = null;
          },
        }),
      );
    },
  );
};

/**
 * @param {Point} start
 * @param {Point} end
 */
const DividerLine = (start, end) => {
  return line({ x1: start.x, y1: start.y, x2: end.x + paddingRight, y2: start.y, stroke: colorMap.lightGrey });
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
  .table-monitoring-trend-wrapper {
    min-height: 200px;
    padding-top: 24px;
    padding-right: 24px;
  }

  .table-monitoring-trend-wrapper:not(.has-sidebar) > .tg-dualpane-divider {
    display: none;
  }

  .data-structure-logs-sidebar {
    align-self: stretch;
    max-height: 500px;
  }
`);

export { TableMonitoringTrend };

export default (component) => {
  const { data, setStateValue, setTriggerValue, parentElement } = component;

  Streamlit.enableV2(setTriggerValue);

  let componentState = parentElement.state;
  if (componentState === undefined) {
    componentState = {};
    for (const [ key, value ] of Object.entries(data)) {
      componentState[key] = van.state(value);
    }

    parentElement.state = componentState;
    van.add(parentElement, TableMonitoringTrend(componentState));
  } else {
    for (const [ key, value ] of Object.entries(data)) {
      if (!isEqual(componentState[key].val, value)) {
        componentState[key].val = value;
      }
    }
  }

  return () => {
    parentElement.state = null;
  };
};
