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
 * @property {boolean} is_anomaly
 * @property {boolean} is_pending
 * @property {boolean} is_training
 * @property {number?} lower_tolerance
 * @property {number?} upper_tolerance
 *
 * @typedef MetricTrendEvent
 * @type {object}
 * @property {number} time
 * @property {number} value
 * @property {boolean} is_anomaly
 * @property {boolean} is_training
 * @property {boolean} is_pending
 * @property {number?} lower_tolerance
 * @property {number?} upper_tolerance
 *
 * @typedef MetricEventGroup
 * @type {object}
 * @property {string} test_definition_id
 * @property {string} column_name
 * @property {MetricTrendEvent[]} events
 *
 * @typedef PredictionSet
 * @type {object}
 * @property {('predict'|'static'|'freshness_window')} method
 * @property {object?} mean
 * @property {object?} lower_tolerance
 * @property {object?} upper_tolerance
 * @property {{start: number?, end: number}?} window
 *
 * @typedef Predictions
 * @type {object}
 * @property {PredictionSet?} volume_trend
 * @property {PredictionSet?} freshness_trend
 *
 * @typedef Properties
 * @type {object}
 * @property {FreshnessEvent[]} freshness_events
 * @property {VolumeTrendEvent[]} volume_events
 * @property {SchemaEvent[]} schema_events
 * @property {MetricEventGroup[]} metric_events
 * @property {(DataStructureLog[])?} data_structure_logs
 * @property {Predictions?} predictions
 * @property {boolean} extended_history
 */
import van from '/app/static/js/van.min.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { emitEvent, getValue, loadStylesheet, parseDate, isEqual } from '/app/static/js/utils.js';
import { FreshnessChart } from '/app/static/js/components/freshness_chart.js';
import { colorMap, formatNumber } from '/app/static/js/display_utils.js';
import { SchemaChangesChart } from '/app/static/js/components/schema_changes_chart.js';
import { SchemaChangesList } from '/app/static/js/components/schema_changes_list.js';
import { getAdaptiveTimeTicksV2, scale } from '/app/static/js/axis_utils.js';
import { Tooltip } from '/app/static/js/components/tooltip.js';
import { DualPane } from '/app/static/js/components/dual_pane.js';
import { Button } from '/app/static/js/components/button.js';
import { MonitoringSparklineChart, MonitoringSparklineMarkers } from '/app/static/js/components/monitoring_sparkline.js';

const { div, span } = van.tags;
const { circle, clipPath, defs, foreignObject, g, line, path, rect, svg, text } = van.tags("http://www.w3.org/2000/svg");

const spacing = 8;
const chartsWidth = 700;
const baseChartsYAxisWidth = 24;
const fresshnessChartHeight = 40;
const schemaChartHeight = 80;
const volumeTrendChartHeight = 80;
const metricTrendChartHeight = 80;
const paddingLeft = 16;
const paddingRight = 16;
const timeTickFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  hour12: true,
});
const tickWidth = 90;

/**
 * @param {Properties} props
 */
const TableMonitoringTrend = (props) => {
  window.testgen.isPage = true;
  loadStylesheet('table-monitoring-trends', stylesheet);

  const shouldShowSidebar = van.state(false);
  const schemaChartSelection = van.state(null);
  van.derive(() => shouldShowSidebar.val = (getValue(props.data_structure_logs)?.length ?? 0) > 0);

  const getDataStructureLogs = (/** @type {SchemaEvent} */ event) => {
    emitEvent('ShowDataStructureLogs', { payload: { start_time: event.window_start, end_time: event.time } });
    shouldShowSidebar.val = true;
    schemaChartSelection.val = event;
  };

  return DualPane(
    {
      id: 'monitoring-trends-container',
      class: () => `table-monitoring-trend-wrapper ${shouldShowSidebar.val ? 'has-sidebar' : ''}`,
      minSize: 150,
      maxSize: 400,
      resizablePanel: 'right',
      resizablePanelDomId: 'data-structure-logs-sidebar',
    },
    div(
      { class: '', style: 'width: 100%;' },
      () => {
        const extendedHistory = getValue(props.extended_history) ?? false;
        return div(
          { class: 'extended-history-toggle' },
          Button({
            label: extendedHistory ? 'Show default view' : 'Show more history',
            icon: extendedHistory ? 'history_toggle_off' : 'history',
            width: 'auto',
            onclick: () => emitEvent('ToggleExtendedHistory', { payload: {} }),
          }),
        );
      },
      () => ChartsSection(props, { schemaChartSelection, getDataStructureLogs }),
      ChartLegend({
        '': {
          items: [
            { icon: svg({ width: 10, height: 10 },
              path({ d: 'M 8 5 A 3 3 0 0 0 2 5', fill: 'none', stroke: colorMap.emptyDark, 'stroke-width': 3, transform: 'rotate(45, 5, 5)' }),
              path({ d: 'M 2 5 A 3 3 0 0 0 8 5', fill: 'none', stroke: colorMap.blueLight, 'stroke-width': 3, transform: 'rotate(45, 5, 5)' }),
              circle({ cx: 5, cy: 5, r: 3, fill: 'var(--dk-dialog-background)', stroke: 'none' })
            ), label: 'Training' },
            { icon: svg({ width: 10, height: 10 }, circle({ cx: 5, cy: 5, r: 3, fill: colorMap.emptyDark, stroke: 'none' })), label: 'No change' },
          ],
        },
        'Freshness': {
          items: [
            { icon: svg({ width: 10, height: 10 }, line({ x1: 4, y1: 0, x2: 4, y2: 10, stroke: colorMap.emptyDark, 'stroke-width': 2 })), label: 'Update' },
            { icon: svg({ width: 10, height: 10 }, circle({ cx: 5, cy: 5, r: 4, fill: colorMap.limeGreen })), label: 'On Time' },
            {
              icon: svg(
                { width: 10, height: 10, style: 'overflow: visible;' },
                rect({ x: 1.5, y: 1.5, width: 7, height: 7, fill: colorMap.red, transform: 'rotate(45 5 5)' }),
              ),
              label: 'Early/Late',
            },
          ],
        },
        'Volume/Metrics': {
          items: [
            {
              icon: svg(
                { width: 16, height: 10 },
                line({ x1: 0, y1: 5, x2: 16, y2: 5, stroke: colorMap.blueLight, 'stroke-width': 2 }),
                circle({ cx: 8, cy: 5, r: 3, fill: colorMap.blueLight })
              ),
              label: 'Actual',
            },
            {
              icon: svg(
                { width: 10, height: 10, style: 'overflow: visible;' },
                rect({ x: 1.5, y: 1.5, width: 7, height: 7, fill: colorMap.red, transform: 'rotate(45 5 5)' }),
              ),
              label: 'Anomaly',
            },
            {
              icon: svg(
                { width: 16, height: 10 },
                path({ d: 'M 0,4 L 16,2 L 16,8 L 0,6 Z', fill: colorMap.emptyDark, opacity: 0.4 }),
                line({ x1: 0, y1: 5, x2: 16, y2: 5, stroke: colorMap.grey, 'stroke-width': 2 })
              ),
              label: 'Prediction',
            },
          ],
        },
        'Schema': {
          items: [
            { icon: svg({ width: 10, height: 10 }, rect({ width: 10, height: 10, fill: colorMap.blue })), label: 'Additions' },
            { icon: svg({ width: 10, height: 10 }, rect({ width: 10, height: 10, fill: colorMap.orange })), label: 'Deletions' },
            { icon: svg({ width: 10, height: 10 }, rect({ width: 10, height: 10, fill: colorMap.purple })), label: 'Modifications' },
          ],
        },
      }),
    ),

    () => {
      const _shouldShowSidebar = shouldShowSidebar.val;
      const selection = schemaChartSelection.val;
      if (!_shouldShowSidebar || !selection) {
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
 * @param {Properties} props
 * @param {object} options
 * @param {import('van').State} options.schemaChartSelection
 * @param {Function} options.getDataStructureLogs
 */
const ChartsSection = (props, { schemaChartSelection, getDataStructureLogs }) => {
  const metricEvents = getValue(props.metric_events) ?? [];
  const chartHeight = (
    + (spacing * 4) + fresshnessChartHeight
    + (spacing * 4) + volumeTrendChartHeight
    + (spacing * 4) + schemaChartHeight
    + metricEvents.length * ((spacing * 4) + metricTrendChartHeight)
  );

  const predictions = getValue(props.predictions);
  const freshnessWindow = predictions?.freshness_trend?.window;
  const predictionTimes = Object.values(predictions ?? {}).reduce((predictionTimes, v) => [
    ...predictionTimes,
    ...Object.keys(v.mean ?? {}).map(t => ({time: +t})),
    ...(v.window ? [
      v.window.start ? {time: v.window.start} : null,
      {time: v.window.end},
    ].filter(Boolean) : []),
  ], []);
  const freshnessEvents = (getValue(props.freshness_events) ?? []).map(e => ({ ...e, time: parseDate(e.time) }));
  const schemaChangeEvents = (getValue(props.schema_events) ?? []).map(e => ({ ...e, time: parseDate(e.time), window_start: parseDate(e.window_start) }));
  const schemaChangesMaxValue = schemaChangeEvents.reduce((currentValue, e) => Math.max(currentValue, e.additions, e.deletions), 10);

  // Compute dropped periods from schema events to hide volume/metric data between table drop and re-add
  const droppedPeriods = [];
  let dropStart = null;
  const sorted = [...schemaChangeEvents].sort((a, b) => a.time - b.time);
  for (const event of sorted) {
    if (event.table_change === 'D' && dropStart === null) {
      dropStart = event.time;
    } else if (event.table_change === 'A' && dropStart !== null) {
      droppedPeriods.push({ start: dropStart, end: event.time });
      dropStart = null;
    }
  }
  const isInDroppedPeriod = (time) => droppedPeriods.some(p => time >= p.start && time <= p.end);

  const volumeTrendEvents = (getValue(props.volume_events) ?? []).map(e => ({ ...e, time: parseDate(e.time) })).filter(e => !isInDroppedPeriod(e.time));

  const metricEventGroups = metricEvents.map(group => ({
    ...group,
    events: group.events.map(e => ({ ...e, time: parseDate(e.time) })).filter(e => !isInDroppedPeriod(e.time)),
  }));

  const volumes = [
    ...volumeTrendEvents
      .flatMap((e) => [e.record_count, parseInt(e.lower_tolerance), parseInt(e.upper_tolerance)])
      .filter((v) => Number.isFinite(v)),
    ...Object.keys(predictions?.volume_trend?.mean ?? {})
      .flatMap((time) => [
        parseInt(predictions.volume_trend.upper_tolerance[time]),
        parseInt(predictions.volume_trend.lower_tolerance[time]),
      ])
      .filter((v) => Number.isFinite(v)),
  ];
  const volumeRange = volumes.length > 0
    ? {min: Math.min(...volumes), max: Math.max(...volumes)}
    : {min: 0, max: 100};
  if (volumeRange.min === volumeRange.max) {
    volumeRange.max = volumeRange.max + 100;
  }
  const tickDecimals = (value, range) => (range.max - range.min) < 1 ? 3 : (value >= 1000 ? 0 : 3);

  const metricRanges = metricEventGroups.map(group => {
    const predictionKey = `metric:${group.test_definition_id}`;
    const metricPrediction = predictions?.[predictionKey];

    const metricValues = [
      ...group.events
        .flatMap(e => [e.value, parseFloat(e.lower_tolerance), parseFloat(e.upper_tolerance)])
        .filter((v) => Number.isFinite(v)),
      ...Object.keys(metricPrediction?.mean ?? {})
        .flatMap((time) => [
          parseFloat(metricPrediction.upper_tolerance[time]),
          parseFloat(metricPrediction.lower_tolerance[time]),
        ])
        .filter((v) => Number.isFinite(v)),
    ];

    const metricRange = metricValues.length > 0
      ? { min: Math.min(...metricValues), max: Math.max(...metricValues) }
      : { min: 0, max: 100 };
    if (metricRange.min === metricRange.max) {
      metricRange.max = metricRange.max + 100;
    }
    return metricRange;
  });

  const longestYTickText = Math.max(
    String(volumeRange.min).length,
    String(volumeRange.max).length,
    String(schemaChangesMaxValue).length,
    ...metricRanges.flatMap(range => [
      String(Number(range.min.toFixed(3))).length,
      String(Number(range.max.toFixed(3))).length,
    ]),
  );
  const longestYTickSize = longestYTickText * 6 - baseChartsYAxisWidth;
  const chartsYAxisWidth = baseChartsYAxisWidth + Math.max(longestYTickSize, 0);
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

  const allTimes = [
    ...freshnessEvents,
    ...schemaChangeEvents,
    ...volumeTrendEvents,
    ...metricEventGroups.flatMap(group => group.events),
    ...predictionTimes,
  ].map(e => e.time);

  const rawTimeline = [...new Set(allTimes)].sort();
  const dateRange = { min: rawTimeline[0] ?? (new Date()).getTime(), max: rawTimeline[rawTimeline.length - 1] ?? (new Date()).getTime() + 1 * 24 * 60 * 60 * 1000 };
  const toPixelX = (date) => scale(date.getTime(), { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x);
  const xTickMinSpacing = 65;
  const timeline = (() => {
    const adaptiveTicks = getAdaptiveTimeTicksV2(
      rawTimeline.map(time => new Date(time)),
      end.x - origin.x,
      xTickMinSpacing,
    );

    const seen = new Set();
    const candidates = [];
    for (const date of [new Date(dateRange.min), ...adaptiveTicks, new Date(dateRange.max)]) {
      if (!date) continue;
      const t = date.getTime();
      if (!seen.has(t)) {
        seen.add(t);
        candidates.push(date);
      }
    }
    candidates.sort((a, b) => a.getTime() - b.getTime());

    if (candidates.length <= 2) return candidates;

    const first = candidates[0];
    const last = candidates[candidates.length - 1];
    const firstPx = toPixelX(first);
    const lastPx = toPixelX(last);

    if (lastPx - firstPx < xTickMinSpacing) return [first];

    const result = [first];
    let prevPx = firstPx;

    for (let i = 1; i < candidates.length - 1; i++) {
      const px = toPixelX(candidates[i]);
      if (px - prevPx >= xTickMinSpacing && lastPx - px >= xTickMinSpacing) {
        result.push(candidates[i]);
        prevPx = px;
      }
    }

    result.push(last);
    return result;
  })();

  const parsedFreshnessEvents = freshnessEvents.map((e) => ({
    changed: e.changed,
    status: e.status,
    message: e.message,
    isTraining: e.is_training,
    isPending: e.is_pending,
    time: e.time,
    point: {
      x: scale(e.time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
      y: fresshnessChartHeight / 2,
    },
  }));
  const parsedFreshnessWindow = freshnessWindow ? {
    startX: freshnessWindow.start
      ? scale(freshnessWindow.start, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x)
      : null,
    endX: scale(freshnessWindow.end, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
    startTime: freshnessWindow.start,
    endTime: freshnessWindow.end,
  } : null;

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

  const parsedVolumeTrendEvents = volumeTrendEvents.toSorted((a, b) => a.time - b.time).map((e) => ({
    originalX: e.time,
    originalY: e.record_count,
    originalLowerTolerance: e.lower_tolerance != undefined
      ? parseInt(e.lower_tolerance)
      : undefined,
    originalUpperTolerance: e.upper_tolerance != undefined
      ? parseInt(e.upper_tolerance)
      : undefined,
    label: 'Row count',
    isAnomaly: e.is_anomaly,
    isTraining: e.is_training,
    isPending: e.is_pending,
    x: scale(e.time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
    y: scale(e.record_count, { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight),
    lowerTolerance: e.lower_tolerance != undefined
      ? scale(parseInt(e.lower_tolerance), { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight)
      : undefined,
    upperTolerance: e.upper_tolerance != undefined
      ? scale(parseInt(e.upper_tolerance), { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight)
      : undefined,
  }));

  const parsedVolumeTrendPredictionPoints = Object.entries(predictions?.volume_trend?.mean ?? {}).toSorted(([a,], [b,]) => (+a) - (+b)).map(([time, count]) => ({
    x: scale(+time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
    y: scale(+count, { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight),
    upper: predictions.volume_trend.upper_tolerance[time] != undefined
      ? scale(parseInt(predictions.volume_trend.upper_tolerance[time]), { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight)
      : undefined,
    lower: predictions.volume_trend.lower_tolerance[time] != undefined
      ? scale(parseInt(predictions.volume_trend.lower_tolerance[time]), { old: volumeRange, new: { min: volumeTrendChartHeight, max: 0 } }, volumeTrendChartHeight)
      : undefined,
  })).filter(p => p.x != undefined && (p.upper != undefined || p.lower != undefined));

  const parsedMetricCharts = metricEventGroups.map((group, idx) => {
    const predictionKey = `metric:${group.test_definition_id}`;
    const metricPrediction = predictions?.[predictionKey];
    const metricRange = metricRanges[idx];

    const parsedEvents = group.events.toSorted((a, b) => a.time - b.time).map(e => ({
      originalX: e.time,
      originalY: e.value,
      originalLowerTolerance: e.lower_tolerance,
      originalUpperTolerance: e.upper_tolerance,
      isAnomaly: e.is_anomaly,
      isTraining: e.is_training,
      isPending: e.is_pending,
      x: scale(e.time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
      y: scale(e.value, { old: metricRange, new: { min: metricTrendChartHeight, max: 0 } }, metricTrendChartHeight),
      lowerTolerance: e.lower_tolerance != undefined
        ? scale(parseFloat(e.lower_tolerance), { old: metricRange, new: { min: metricTrendChartHeight, max: 0 } }, metricTrendChartHeight)
        : undefined,
      upperTolerance: e.upper_tolerance != undefined
        ? scale(parseFloat(e.upper_tolerance), { old: metricRange, new: { min: metricTrendChartHeight, max: 0 } }, metricTrendChartHeight)
        : undefined,
    }));

    const parsedPredictionPoints = Object.entries(metricPrediction?.mean ?? {}).toSorted(([a,], [b,]) => (+a) - (+b)).map(([time, value]) => ({
      x: scale(+time, { old: dateRange, new: { min: origin.x, max: end.x } }, origin.x),
      y: scale(+value, { old: metricRange, new: { min: metricTrendChartHeight, max: 0 } }, metricTrendChartHeight),
      upper: metricPrediction.upper_tolerance[time] != undefined
        ? scale(parseFloat(metricPrediction.upper_tolerance[time]), { old: metricRange, new: { min: metricTrendChartHeight, max: 0 } }, metricTrendChartHeight)
        : undefined,
      lower: metricPrediction.lower_tolerance[time] != undefined
        ? scale(parseFloat(metricPrediction.lower_tolerance[time]), { old: metricRange, new: { min: metricTrendChartHeight, max: 0 } }, metricTrendChartHeight)
        : undefined,
    })).filter(p => p.x != undefined && (p.upper != undefined || p.lower != undefined));

    return {
      columnName: group.column_name,
      testDefinitionId: group.test_definition_id,
      events: parsedEvents,
      range: metricRange,
      predictionPoints: parsedPredictionPoints,
      predictionMethod: metricPrediction?.method,
    };
  });

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

      // Convert screen pixel dimensions to SVG user units for boundary checks
      const svgElement = document.getElementById('monitoring-trends-charts-svg');
      const screenToSvg = (chartsWidth + chartsYAxisWidth) / svgElement.getBoundingClientRect().width;
      const tooltipWidth = tooltipRect.width * screenToSvg;
      const tooltipHeight = tooltipRect.height * screenToSvg;

      let tooltipX = point.x + 10;
      let tooltipY = point.y + verticalOffset + 10;

      if ((tooltipX + tooltipWidth) >= (chartsWidth + chartsYAxisWidth)) {
        tooltipX = point.x - tooltipWidth - 10;
      }

      if (tooltipY + tooltipHeight >= chartHeight) {
        tooltipY = chartHeight - tooltipHeight;
      }
      if (tooltipY < 0) {
        tooltipY = 0;
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

  return svg(
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
          predictedWindow: parsedFreshnessWindow,
          showTooltip: showTooltip.bind(null, positionTracking.freshnessChart),
          hideTooltip,
        },
        ...parsedFreshnessEvents,
      ),
      DividerLine({ x: origin.x - paddingLeft, y: nextPosition({ offset: fresshnessChartHeight }) }, end),

      text({ x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small', fill: 'var(--primary-text-color)' }, 'Volume'),
      MonitoringSparklineChart(
        {
          width: chartsWidth,
          height: volumeTrendChartHeight,
          nestedPosition: { x: 0, y: nextPosition({ name: 'volumeTrendChart' }) },
          lineWidth: 2,
          attributes: {style: 'overflow: visible;'},
          prediction: parsedVolumeTrendPredictionPoints,
          predictionMethod: predictions.volume_trend?.method,
        },
        ...parsedVolumeTrendEvents,
      ),
      MonitoringSparklineMarkers(
        {
          size: 2,
          transform: `translate(0, ${positionTracking.volumeTrendChart})`,
          showTooltip: showTooltip.bind(null, positionTracking.volumeTrendChart),
          hideTooltip,
        },
        parsedVolumeTrendEvents,
      ),
      DividerLine({ x: origin.x - paddingLeft, y: nextPosition({ offset: volumeTrendChartHeight }) }, end),

      // Schema Chart Selection Highlight
      () => {
        const selection = schemaChartSelection.val;
        if (selection) {
          const width = 16;
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
          nestedPosition: { x: 0, y: nextPosition({ name: 'schemaChangesChart' }) },
          onClick: getDataStructureLogs,
          showTooltip: showTooltip.bind(null, positionTracking.schemaChangesChart),
          hideTooltip,
        },
        ...parsedSchemaChangeEvents,
      ),

      ...parsedMetricCharts.flatMap((metricChart, idx) => {
        const chartName = `metricTrendChart_${idx}`;
        return [
          DividerLine({ x: origin.x - paddingLeft, y: nextPosition({ offset: idx === 0 ? schemaChartHeight : metricTrendChartHeight }) }, end),
          text({ x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small', fill: 'var(--primary-text-color)' }, `Metric: ${metricChart.columnName}`),
          MonitoringSparklineChart(
            {
              width: chartsWidth,
              height: metricTrendChartHeight,
              nestedPosition: { x: 0, y: nextPosition({ name: chartName }) },
              lineWidth: 2,
              attributes: {style: 'overflow: visible;'},
              prediction: metricChart.predictionPoints,
              predictionMethod: metricChart.predictionMethod,
            },
            ...metricChart.events,
          ),
          MonitoringSparklineMarkers(
            {
              size: 2,
              transform: `translate(0, ${positionTracking[chartName]})`,
              showTooltip: showTooltip.bind(null, positionTracking[chartName]),
              hideTooltip,
            },
            metricChart.events,
          ),
        ];
      }),

      g(
        {},
        rect({
          width: chartsWidth,
          height: chartHeight,
          x: origin.x - paddingLeft,
          y: 0,
          rx: 4,
          ry: 4,
          stroke: 'var(--border-color)',
          fill: 'transparent',
          style: 'pointer-events: none;'
        }),

        timeline.map((value, idx) => {
          const valueAsDate = new Date(value);
          const label = timeTickFormatter.format(valueAsDate);
          const xPosition = scale(valueAsDate.getTime(), {
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

        // Volume Chart Y axis
        g(
          { transform: `translate(${chartsYAxisWidth - 4}, ${positionTracking.volumeTrendChart + (volumeTrendChartHeight / 2)})` },
          text({ x: 0, y: 35, class: 'tick-text', 'text-anchor': 'end', fill: 'var(--caption-text-color)' }, formatNumber(volumeRange.min, tickDecimals(volumeRange.min, volumeRange))),
          text({ x: 0, y: -35, class: 'tick-text', 'text-anchor': 'end', fill: 'var(--caption-text-color)' }, formatNumber(volumeRange.max, tickDecimals(volumeRange.max, volumeRange))),
        ),

        // Schema Chart Y axis
        g(
          { transform: `translate(${chartsYAxisWidth - 4}, ${positionTracking.schemaChangesChart + (schemaChartHeight / 2)})` },
          text({ x: 0, y: -35, class: 'tick-text', 'text-anchor': 'end', fill: 'var(--caption-text-color)' }, formatNumber(schemaChangesMaxValue)),
          text({ x: 0, y: 35, class: 'tick-text', 'text-anchor': 'end', fill: 'var(--caption-text-color)' }, 0),
        ),

        // Metric Chart Y axes
        ...parsedMetricCharts.map((metricChart, idx) => {
          const chartName = `metricTrendChart_${idx}`;
          return g(
            { transform: `translate(${chartsYAxisWidth - 4}, ${positionTracking[chartName] + (metricTrendChartHeight / 2)})` },
            text({ x: 0, y: 35, class: 'tick-text', 'text-anchor': 'end', fill: 'var(--caption-text-color)' }, formatNumber(metricChart.range.min, tickDecimals(metricChart.range.min, metricChart.range))),
            text({ x: 0, y: -35, class: 'tick-text', 'text-anchor': 'end', fill: 'var(--caption-text-color)' }, formatNumber(metricChart.range.max, tickDecimals(metricChart.range.max, metricChart.range))),
          );
        }),
      ),
      tooltipWrapperElement,
    );
};

/**
 * @param {Point} start
 * @param {Point} end
 */
const DividerLine = (start, end) => {
  return line({ x1: start.x, y1: start.y, x2: end.x + paddingRight, y2: start.y, stroke: 'var(--border-color)' });
}

/**
 * @typedef LegendItem
 * @type {object}
 * @property {Element} icon
 * @property {string} label
 *
 * @typedef LegendGroup
 * @type {object}
 * @property {LegendItem[]} items
 *
 * @param {Object.<string, LegendGroup>} legendGroups
 */
const ChartLegend = (legendGroups) => {
  return div(
    { class: 'chart-legend' },
    Object.entries(legendGroups).map(([groupName, { items }]) =>
      div(
        { class: 'chart-legend-group' },
        span({ class: `chart-legend-group-label ${groupName ? '' : 'hidden'}` }, groupName),
        ...items.map(item =>
          div(
            { class: 'chart-legend-item' },
            item.icon,
            span({ class: 'chart-legend-item-label' }, item.label),
          )
        ),
      )
    ),
  );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
  .table-monitoring-trend-wrapper {
    min-height: 200px;
    padding-top: 24px;
    padding-right: 24px;
    position: relative;
  }

  .extended-history-toggle {
    position: absolute;
    top: -70px;
    right: 48px;
    z-index: 1;
  }

  .table-monitoring-trend-wrapper:not(.has-sidebar) > .tg-dualpane-divider {
    display: none;
  }

  .data-structure-logs-sidebar {
    align-self: stretch;
    max-height: 500px;
  }

  .tick-text {
    font-size: 10px;
  }

  .chart-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 36px;
    row-gap: 8px;
    padding: 12px 16px;
    border-top: 1px solid var(--border-color);
    background: var(--dk-dialog-background);
    position: sticky;
    bottom: 0;
    margin-left: -24px;
    margin-right: -48px;
    margin-top: 24px;
  }

  .chart-legend-group {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .chart-legend-group-label {
    font-size: 11px;
    color: var(--secondary-text-color);
    font-weight: 500;
  }

  .chart-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .chart-legend-item-label {
    font-size: 11px;
    color: var(--caption-text-color);
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
