/**
 * @import {Point} from '../components/chart_canvas.js';
 * @import {FreshnessEvent} from '../components/freshness_chart.js';
 * @import {SchemaEvent} from '../components/schema_changes_chart.js';
 * @import {MonitoringEvent} from '../components/monitoring_sparkline.js';
 * 
 * @typedef LineChart
 * @type {object}
 * @property {string} label
 * @property {MonitoringEvent[]} events
 * 
 * @typedef DataStructureLog
 * @type {object}
 * @property {('A'|'D'|'M')} change
 * @property {string} old_data_type
 * @property {string} new_data_type
 * @property {string} column_name
 * 
 * @typedef Properties
 * @type {object}
 * @property {FreshnessEvent[]} freshness_events
 * @property {MonitoringEvent[]} volume_events
 * @property {SchemaEvent[]} schema_events
 * @property {(DataStructureLog[])?} data_structure_logs
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { FreshnessChart, getFreshnessEventColor } from '../components/freshness_chart.js';
import { colorMap } from '../display_utils.js';
import { SchemaChangesChart } from '../components/schema_changes_chart.js';
import { getAdaptiveTimeTicks, scale } from '../axis_utils.js';
import { Tooltip } from '../components/tooltip.js';
import { Icon } from '../components/icon.js';
import { DualPane } from '../components/dual_pane.js';
import { Button } from '../components/button.js';

const { div, span } = van.tags;
const { circle, clipPath, defs, foreignObject, g, line, rect, svg, text } = van.tags("http://www.w3.org/2000/svg");

const spacing = 8;
const chartsWidth = 700;
const chartsYAxisWidth = 104;
const fresshnessChartHeight = 25;
const schemaChartHeight = 80;
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
  loadStylesheet('table-monitoring-trends', stylesheet);
  Streamlit.setFrameHeight(1);

  const domId = 'monitoring-trends-container';
  resizeFrameHeightToElement(domId);
  resizeFrameHeightOnDOMChange(domId);

  const chartHeight = (
    + (spacing * 2)
    + fresshnessChartHeight
    + (spacing * 3)
    // + volumeChartHeight
    // + (spacing * 3)
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

  const freshnessEvents = (getValue(props.freshness_events) ?? []).map(e => ({ ...e, time: Date.parse(e.time) }));
  const schemaChangeEvents = (getValue(props.schema_events) ?? []).map(e => ({ ...e, time: Date.parse(e.time) }));

  const rawTimeline = schemaChangeEvents.map(e => e.time).sort();
  const dataRange = { min: rawTimeline[0], max: rawTimeline[rawTimeline.length - 1] };
  const timeline = [
    dataRange.min,
    ...getAdaptiveTimeTicks(rawTimeline.slice(2, rawTimeline.length - 2), 5, 8),
    dataRange.max,
  ];

  const parsedFreshnessEvents = freshnessEvents.map((e) => ({
    changed: e.changed,
    expected: e.expected,
    status: e.status,
    time: e.time,
    point: {
      x: scale(e.time, { old: dataRange, new: { min: origin.x, max: end.x } }, origin.x),
      y: fresshnessChartHeight / 2,
    },
  }));
  const freshessChartLegendItems = Object.values(parsedFreshnessEvents.reduce((legendItems, e, idx) => {
    const itemColor = getFreshnessEventColor(e);
    const key = `${e.changed}-${itemColor}`;
    if (!legendItems[key]) {
      const position = `translate(0,${20 * (idx + 1)})`;
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
    point: {
      x: scale(e.time, { old: dataRange, new: { min: origin.x, max: end.x } }, origin.x),
      y: schemaChartHeight / 2,
    },
  }));
  const schemaChangesMaxValue = schemaChangeEvents.reduce((currentValue, e) => Math.max(currentValue, e.additions, e.deletions), 10);

  const shouldShowSidebar = van.state(false);
  const schemaChartSelection = van.state(null);
  van.derive(() => shouldShowSidebar.val = (getValue(props.data_structure_logs)?.length ?? 0) > 0);

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
    emitEvent('ShowDataStructureLogs', { payload: { time: event.time } });
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

        text({ x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small' }, 'Freshness'),
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

        // Schena Chart Selection Highlight
        () => {
          const selection = schemaChartSelection.val;
          if (selection) {
            const width = 10;
            const height = schemaChartHeight + 4 * spacing;
            return rect({
              width: width,
              height: height,
              x: selection.point.x - (width / 2),
              y: selection.point.y + positionTracking.schemaChangesChart - 1 * spacing - (height / 2),
              fill: colorMap.empty,
              style: `transform-box: fill-box; transform-origin: center;`,
            });
          }

          return g();
        },
        text({ x: origin.x, y: nextPosition({ spaces: 2 }), class: 'text-small' }, 'Schema'),
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
              old: dataRange,
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
            { transform: `translate(24, ${positionTracking.freshnessChart + (fresshnessChartHeight / 2) - 35 /* ~ height of this element */})` },
            ...freshessChartLegendItems,
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
      const dataStructureLogs = getValue(props.data_structure_logs) ?? [];
      if (!_shouldShowSidebar) {
        return span();
      }

      return div(
        { id: 'data-structure-logs-sidebar', class: 'flex-column data-structure-logs-sidebar' },
        span({ class: 'mb-4', style: 'min-width: 150px;' }, 'Schema Changes'),
        div(
          { class: 'flex-column fx-gap-1 fx-flex log-list mb-4' },
          ...dataStructureLogs.map(log => StructureLogEntry(log)),
        ),
        Button({
          label: 'Hide',
          style: 'margin-top: auto;',
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

const StructureLogEntry = (/** @type {DataStructureLog} */ log) => {
  if (log.change === 'A') {
    return div(
      { class: 'flex-row fx-gap-1' },
      Icon({ size: 20, classes: 'schema-added-icon' }, 'add'),
      div(
        { class: 'column-info flex-column' },
        span(log.column_name),
        span(log.new_data_type),
      ),
    );
  } else if (log.change === 'D') {
    return div(
      { class: 'flex-row fx-gap-1' },
      Icon({ size: 20, classes: 'schema-deleted-icon' }, 'remove'),
      div(
        { class: 'column-info flex-column' },
        span({ class: 'truncate-text' }, log.column_name),
      ),
    );
  } else if (log.change === 'M') {
    return div(
      { class: 'flex-row fx-gap-1' },
      span({ class: 'schema-modified-icon' }, ''),
      div(
        { class: 'column-info flex-column' },
        span({ class: 'truncate-text' }, log.column_name),

        div(
          { class: 'flex-row fx-gap-1' },
          span({ class: 'truncate-text' }, log.old_data_type),
          Icon({ size: 10 }, 'arrow_right_alt'),
          span({ class: 'truncate-text' }, log.new_data_type),
        ),
      ),
    );
  }

  return null;
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
  }

  .data-structure-logs-sidebar > .log-list {
    overflow-y: auto;
  }

  .column-info {
    color: var(--secondary-text-color);
    white-space: nowrap;
    text-overflow: ellipsis;
    overflow: hidden;
  }

  .column-info span {
    font-family: 'Courier New', Courier, monospace;

    white-space: nowrap;
    text-overflow: ellipsis;
    overflow: hidden;
  }

  .column-info > span:first-child {
    font-family: 'Roboto', 'Helvetica Neue', sans-serif;
  }

  .schema-added-icon {
    color: var(--green);
  }

  .schema-deleted-icon {
    color: var(--red);
  }

  .schema-modified-icon {
    width: 10px;
    min-width: 10px;
    height: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
        
  .schema-modified-icon:after {
    content: "";
    width: 7px;
    height: 7px;
    display: inline-block;
    border: 1px solid var(--blue);
    box-sizing: border-box;
    transform: rotate(45deg);
    background-color: var(--blue);
  }
`);

export { TableMonitoringTrend };
