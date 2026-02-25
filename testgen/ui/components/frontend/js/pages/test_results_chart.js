import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { getValue, loadStylesheet, onFrameResized, parseDate, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { ChartCanvas } from '../components/chart_canvas.js';
import { MonitoringSparklineChart, MonitoringSparklineMarkers } from '../components/monitoring_sparkline.js';
import { ThresholdChart } from '../components/threshold_chart.js';
import { colorMap } from '../display_utils.js';
import { FreshnessChart } from '../components/freshness_chart.js';

const { div } = van.tags;
const { circle, g, rect, text } = van.tags("http://www.w3.org/2000/svg");

const freshnessColorByStatus = {
    Passed: colorMap.limeGreen,
    Log: colorMap.blueLight,
};
const staleColorByStatus = {
    Failed: colorMap.red,
    Warning: colorMap.orange,
    Log: colorMap.lightGrey,
};

const TestResultsChart = (/** @type Properties */ props) => {
    loadStylesheet('testResultsChart', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const width = van.state(0);
    const height = van.state(0);
    const points = van.state([]);
    const thresholdPoints = van.state([]);
    const allPoints = van.derive(() => [...points.val, ...thresholdPoints.val]);
    const axis = van.state({
        x: {
            min: null,
            max: null,
            label: null,
            ticksCount: 8,
            renderLine: false,
            renderGridLines: false,
        },
        y: {
            min: 0,
            max: 1,
            label: null,
            ticksCount: 8,
            renderLine: false,
            renderGridLines: false,
        },
    });
    const legend = van.state(null);
    const markers = van.state(null);
    const visualizationType = van.state('line_chart');

    const sharedInitialization = (data) => {
        const dataPoints = [];

        let minY = null;
        let maxY = null;
        let minThreshold = null;
        let maxThreshold = null;
        for (const item of data) {
            dataPoints.push({x: parseDate(item.test_date), y: item.result_measure});

            minY = minY == undefined ? item.result_measure : Math.min(minY, item.result_measure);
            maxY = maxY == undefined ? item.result_measure : Math.max(maxY, item.result_measure);
            minThreshold = minThreshold == undefined ? item.threshold_value : Math.min(minThreshold, item.threshold_value);
            maxThreshold = maxThreshold == undefined ? item.threshold_value : Math.max(maxThreshold, item.threshold_value);
        }

        minY = Math.min(minY, minThreshold);
        maxY = Math.max(maxY, maxThreshold);
        if ((minY > 0 && maxY - minY < 0.1 * maxY) || minY === maxY) {
            axis.val = {
                x: {
                    ...axis.val.x,
                },
                y: {
                    ...axis.val.y,
                    min: minY - 1,
                    max: maxY + 1,
                },
            };
        } else {
            axis.val = {
                x: {
                    ...axis.val.x,
                },
                y: {
                    ...axis.val.y,
                    min: undefined,
                    max: undefined,
                },
            };
        }
        points.val = dataPoints;
    };
    const initilizeLineChart = (data) => {
        const thresholdDataPoints = [];
        for (const item of data) {
            thresholdDataPoints.push({x: parseDate(item.test_date), y: item.threshold_value});
        }

        let thresholdLineColor = colorMap.redLight;
        if (data.every(item => '<>' === item.test_operator)) {
            thresholdLineColor = colorMap.greenLight;
        }

        thresholdPoints.val = thresholdDataPoints;
        axis.val = {
            x: {
                ...axis.val.x,
                label: 'Test Date',
                renderLine: true,
                renderGridLines: true,
            },
            y: {
                ...axis.val.y,
                label: data[0].measure_uom,
            },
        };

        legend.val = (point) => g(
            {transform: `translate(${point.x},${point.y})`},
            g(
                {},
                circle({
                    r: 4,
                    cx: 0,
                    cy: -4,
                    fill: colorMap.blue,
                }),
                text({x: 10, y: 0, class: 'text-small', fill: 'var(--caption-text-color)'}, 'Observations'),
            ),
            g(
                {transform: 'translate(0, 24)'},
                rect({
                    x: -3,
                    y: -7,
                    width: 14,
                    height: 7,
                    fill: thresholdLineColor,
                }),
                text({x: 18, y: 0, class: 'text-small', fill: 'var(--caption-text-color)'}, 'Threshold'),
            ),
        );
        markers.val = (getPoint, showTooltip, hideTooltip) => {
            const markerPoints = points.val.map((point) => getPoint(point)).filter((point) => !Number.isNaN(point.x) && !Number.isNaN(point.y));
            return MonitoringSparklineMarkers({showTooltip, hideTooltip}, markerPoints);
        };
    };
    const initilizeFreshnessChart = (data) => {
        const updateStatuses = new Set();
        const staleStatuses = new Set();
        const dataPoints = [];

        for (const item of data) {
            dataPoints.push({x: parseDate(item.test_date), y: item.result_measure, ...item});
            
            if (item.result_measure >= 1) {
                updateStatuses.add(item.result_status);
            } else {
                staleStatuses.add(item.result_status);
            }
        }

        points.val = dataPoints;
        axis.val = {
            x: {
                ...axis.val.x,
                label: 'Test Date',
                renderLine: true,
            },
            y: {
                ...axis.val.y,
                min: -1,
                max: 1,
                ticksCount: 3,
            },
        };
        legend.val = (point) => g(
            {transform: `translate(${point.x},${point.y})`},
            updateStatuses.size > 0
                ? g(
                    {},
                    Array.from(updateStatuses).map((status, idx) =>
                        circle({
                            r: 4,
                            cx: 0 + (11 * idx),
                            cy: -4,
                            fill: freshnessColorByStatus[status],
                        })
                    ),
                    text({x: 10 + (11 * (updateStatuses.size - 1)), y: 0, class: 'text-small', fill: 'var(--caption-text-color)'}, 'Update'),
                )
                : null,
            staleStatuses.size > 0
                ? g(
                    {transform: `translate(0, ${staleStatuses.size > 0 ? '24' : '0'})`},
                    Array.from(staleStatuses).map((status, idx) =>
                        rect({
                            x: -3 + (12 * idx),
                            y: -7,
                            width: 7,
                            height: 7,
                            fill: staleColorByStatus[status],
                            style: `transform-box: fill-box; transform-origin: center;`,
                            transform: 'rotate(45)',
                        })
                    ),
                    text({x: 10 + (12 * (staleStatuses.size - 1)), y: 0, class: 'text-small', fill: 'var(--caption-text-color)'}, 'No update'),
                )
                : null,
        );
    };
    const initializers = {
        line_chart: initilizeLineChart,
        binary_chart: initilizeFreshnessChart,
    };

    van.derive(() => {
        const data = getValue(props.data);

        sharedInitialization(data);
        visualizationType.val = data[0]?.result_visualization ?? 'line_chart';
        initializers[visualizationType.rawVal]?.(data);
    });

    const wrapperId = 'test-results-chart-wrapper';
    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    onFrameResized(wrapperId, (box, element) => {
        width.val = box.width;
        height.val = box.height;
    });

    return div(
        { id: wrapperId },
        ChartCanvas(
            {
                width,
                height,
                axis,
                legend,
                markers,
                points: allPoints,
                
            },
            (viewBox, area, getPoint) => {
                let data = points.val.map((point) => getPoint(point));
                const visualization = visualizationType.val;
                if (visualization === 'binary_chart') {
                    data = points.val.map((point) => ({changed: point.y > 0, expected: undefined, status: point.result_status, point: getPoint({x: point.x, y: 0})}));
                    return FreshnessChart(
                        {width: viewBox.width, height: viewBox.height, lineHeight: viewBox.height * 0.60},
                        ...data,
                    );
                }
                return MonitoringSparklineChart(
                    {viewBox: viewBox, lineWidth: 2, paddingLeft: area.bottomLeft.x, paddingRight: 0},
                    ...data,
                );
            },
            (viewBox, area, getPoint) => {
                if (visualizationType.val !== 'line_chart') {
                    return null;
                }

                const data = getValue(props.data);
                const testOperators = data.map(r => r.test_operator);
                const lines = [
                    thresholdPoints.val.map((point) => getPoint(point)),
                ];

                let lineWidth = 2;
                let lineColor = colorMap.redLight;
                if (testOperators.every(op => ['<', '<='].includes(op))) {
                    lines.unshift(
                        thresholdPoints.val.map((point) => getPoint({ x: point.x, y: -99999 })).slice().reverse(),
                    );
                } else if (testOperators.every(op => ['>', '>='].includes(op))) {
                    const maxThresholdValue = Math.max(...thresholdPoints.val.map((point) => point.y));
                    lines.unshift(
                        thresholdPoints.val.map((point) => getPoint({ x: point.x, y: maxThresholdValue * 1.1 })).slice().reverse(),
                    );
                } else if (testOperators.every(op => ['=', '<>'].includes(op))) {
                    lineWidth = 5;
                    if (testOperators.every(op => op === '<>')) {
                        lineColor = colorMap.greenLight;
                    }
                }

                if (lines.length <= 0) {
                    return null;
                }
                return ThresholdChart(
                    {viewBox: viewBox, lineWidth, paddingLeft: area.bottomLeft.x, paddingRight: 0, color: lineColor},
                    ...lines,
                );
            },
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
#test-results-chart-wrapper {
    min-height: 450px;
}
`);

export { TestResultsChart };
