/**
 * A container that renders a coordinate system and all the
 * provided (compatible) chart components "cocentered" in the
 * aforementioned coordinates.
 * 
 * Functionalities:
 * - display the axis and their ticks for the chart
 * - display the hover-over elements, if any
 * - allows zooming in and out
 * 
 * @typedef Options
 * @type {object}
 * @property {number} width
 * @property {number} height
 * @property {Point[]} points
 * @property {AxisConfigs?} axis
 * @property {((point: Point) => SVGElement)?} legend
 * @property {((getPoint: ((Point) => Point), showToolip: ((message: string, point: Point) => void), hideToolip: (() => void)) => SVGElement)?} markers
 * 
 * @typedef Point
 * @type {object}
 * @property {number} x
 * @property {number} y
 * @property {number} originalX
 * @property {number} originalY
 * 
 * @typedef AxisConfigs
 * @type {object}
 * @property {SingleAxisConfig?} x
 * @property {SingleAxisConfig?} y
 * 
 * @typedef SingleAxisConfig
 * @type {object}
 * @property {any?} min
 * @property {any?} max
 * @property {string?} label
 * @property {number?} ticksCount
 * @property {boolean?} renderLine
 * @property {boolean?} renderGridLines
 * 
 * @typedef ChartRenderer
 * @type {((viewBox: ChartViewBox, area: DrawingArea, getPoint: ((Point) => Point)) => SVGElement)}
 * 
 * @typedef ChartViewBox
 * @type {object}
 * @property {number} minX
 * @property {number} minY
 * @property {number} width
 * @property {number} height
 * 
 * @typedef DrawingArea
 * @type {object}
 * @property {Point} topLeft
 * @property {Point} topRight
 * @property {Point} bottomLeft
 * @property {Point} bottomRight
 */
import van from '../van.min.js';
import { afterMount, getRandomId, getValue, loadStylesheet } from '../utils.js';
import { colorMap } from '../display_utils.js';
import { formatSmartTimeTicks, getAdaptiveTimeTicks, niceTicks, scale, screenToSvgCoordinates } from '../axis_utils.js';
import { Button } from './button.js';
import { Tooltip, withTooltip } from './tooltip.js';

const { div } = van.tags;
const { clipPath, defs, foreignObject, g, line, rect, svg, text } = van.tags("http://www.w3.org/2000/svg");

const spacing = 8;
const topLegendHeight = spacing * 8;
const verticalAxisLabelWidth = spacing * 2;
const verticalAxisLabelLeftMargin = 5;
const verticalAxisTicksLeftMargin = spacing * 3;

const horizontalAxisLabelHeight = spacing * 2;
const horizontalAxisTicksHeight = spacing * 6;
const horizontalAxisLabelBottomMargin = 0;
const horizontalAxisTicksBottomMargin = spacing * 5;

const innerPaddingX = spacing * 3;
const innerPaddingY = spacing * 2;

const cornerDash = 10;
const draggingOverlayColor = '#FFFFFF66';

const tickTextHeight = 14;

const actionsWidth = 40;
const actionsHeight = 40;

/**
 * @param {Options} options
 * @param  {...ChartRenderer} charts
 * @returns {HTMLDivElement}
 */
const ChartCanvas = (options, ...charts) => {
    loadStylesheet('chartCanvas', stylesheet);

    const canvasWidth = van.state(0);
    const canvasHeight = van.state(0);

    const topLeft = van.state({x: 0, y: 0});
    const topRight = van.state({x: 0, y: 0});
    const bottomLeft = van.state({x: 0, y: 0});
    const bottomRight = van.state({x: 0, y: 0});

    const xAxisChartRange = van.state({min: 0, max: 0});
    const yAxisChartRange = van.state({min: 0, max: 0});

    const xAxisLabel = van.state(null);
    const xAxisDataRange = van.state({min: 0, max: 0});
    const initialXAxisDataRange = van.state({min: 0, max: 0});
    const xAxisTicksCount = van.state(8);
    const xRenderLine = van.state(false);
    const xRenderGridLines = van.state(true);

    const yAxisLabel = van.state(null);
    const yAxisDataRange = van.state({min: 0, max: 0});
    const initialYAxisDataRange = van.state({min: 0, max: 0});
    const yAxisTicksCount = van.state(4);
    const yRenderLine = van.state(false);
    const yRenderGridLines = van.state(false);

    const legendRenderer = van.state(null);
    const markersRenderer = van.state(null);

    const dataPoints = van.state([]);
    const dataPointsMapping = van.state({});

    const isZoomed = van.state(false);
    const isDragZooming = van.state(false);
    const dragZoomStartingPoint = van.state(null);
    const dragZoomCurrentPoint = van.state(null);
    const isHoveringOver = van.state(false);

    let /** @type {SVGElement?} */ interactiveLayerSvg;

    const DOMIdSuffix = getRandomId();
    const getDOMId = (domId) => `${domId}-${DOMIdSuffix}`;

    const asSVGX = (value) => scale(value, {old: xAxisDataRange.rawVal, new: xAxisChartRange.rawVal}, bottomLeft.rawVal.x);
    const asSVGY = (value) => scale(value, {old: yAxisDataRange.rawVal, new: yAxisChartRange.rawVal}, bottomLeft.rawVal.y);

    van.derive(() => {
        canvasWidth.val = getValue(options.width);
    });

    van.derive(() => {
        canvasHeight.val = getValue(options.height);
    });

    van.derive(() => {
        const axisConfig = getValue(options.axis);
        const originalPoints = getValue(options.points);

        const xRange = {min: axisConfig?.x?.min, max: axisConfig?.x?.max};
        const yRange = {min: axisConfig?.y?.min, max: axisConfig?.y?.max};

        if (!xRange.min || !xRange.max) {
            const xAxisValues = originalPoints.map(p => p.x);
            xRange.min = Math.min(...xAxisValues);
            xRange.max = Math.max(...xAxisValues);
        }

        if (!yRange.min || !yRange.max) {
            const yAxisValues = originalPoints.map(p => p.y);
            yRange.min = Math.min(...yAxisValues);
            yRange.max = Math.max(...yAxisValues);
        }

        xAxisLabel.val = axisConfig?.x?.label ?? null;
        xAxisTicksCount.val = axisConfig?.x?.ticksCount ?? 8;
        xAxisDataRange.val = {min: xRange.min, max: xRange.max};
        initialXAxisDataRange.val = {...xAxisDataRange.rawVal};
        xRenderLine.val = axisConfig?.x?.renderLine ?? false;
        xRenderGridLines.val = axisConfig?.x?.renderGridLines ?? false;

        yAxisLabel.val = axisConfig?.y?.label ?? null;
        yAxisTicksCount.val = axisConfig?.y?.ticksCount ?? 4;
        yAxisDataRange.val = {min: yRange.min, max: yRange.max};
        initialYAxisDataRange.val = {...yAxisDataRange.rawVal};
        yRenderLine.val = axisConfig?.y?.renderLine ?? false;
        yRenderGridLines.val = axisConfig?.y?.renderGridLines ?? false;
    });

    van.derive(() => {
        legendRenderer.val = getValue(options.legend);
    });

    van.derive(() => {
        markersRenderer.val = getValue(options.markers);
    });

    van.derive(() => {
        xAxisChartRange.val;
        yAxisChartRange.val;

        const originalPoints = getValue(options.points);
        const dataPoints_ = [];
        const dataPointsMapping_ = {};

        for (const original of originalPoints) {
            const point = {x: asSVGX(original.x), y: asSVGY(original.y)};
            dataPoints_.push(point);
            dataPointsMapping_[`${original.x}-${original.y}`] = point;
        }

        dataPoints.val = dataPoints_;
        dataPointsMapping.val = dataPointsMapping_;
    });

    const resizeChartBoundaries = () => {
        const marginTop = topLegendHeight;
        const marginBottom = (xAxisLabel.rawVal ? horizontalAxisLabelHeight : 0) + horizontalAxisTicksHeight;
        
        let marginLeft = (yAxisLabel.rawVal ? verticalAxisLabelWidth : 0) + spacing * 2;
        const yAxisElement = document.getElementById(getDOMId('y-axis-ticks-group'));
        if (yAxisElement) {
            const box = yAxisElement.getBoundingClientRect();
            marginLeft += box.width;
        }

        topLeft.val = {x: marginLeft, y: marginTop};
        topRight.val = {x: canvasWidth.rawVal, y: marginTop};
        bottomLeft.val = {x: marginLeft, y: Math.max(canvasHeight.rawVal - marginBottom, 0)};
        bottomRight.val = {x: canvasWidth.rawVal, y: Math.max(canvasHeight.rawVal - marginBottom, 0)};

        xAxisChartRange.val = {min: bottomLeft.rawVal.x + innerPaddingX, max: bottomRight.rawVal.x - innerPaddingX};
        yAxisChartRange.val = {min: bottomLeft.rawVal.y - innerPaddingY, max: topLeft.rawVal.y + innerPaddingY};
    };

    van.derive(() => {
        canvasWidth.val;
        canvasHeight.val;
        resizeChartBoundaries();

        xAxisDataRange.val = {...xAxisDataRange.rawVal};
        yAxisDataRange.val = {...yAxisDataRange.rawVal};
    });

    const startDragZoom = (event) => {
        interactiveLayerSvg = event.target.parentNode;
        dragZoomStartingPoint.val = screenToSvgCoordinates(interactiveLayerSvg, event);
        isDragZooming.val = true;
        document.addEventListener('mousemove', updateDragZoomRect);
        document.addEventListener('mouseup', stopDragZoom);
        document.addEventListener('touchmove', updateDragZoomRect);
        document.addEventListener('touchend', stopDragZoom);
    };
    const updateDragZoomRect = (event) => {
        if (isDragZooming.val) {
            dragZoomCurrentPoint.val = screenToSvgCoordinates(interactiveLayerSvg, event);
        }
    };
    const stopDragZoom = (event) => {
        document.removeEventListener('mousemove', updateDragZoomRect);
        document.removeEventListener('mouseup', stopDragZoom);
        document.removeEventListener('touchmove', updateDragZoomRect);
        document.removeEventListener('touchend', stopDragZoom);

        const startingPoint = dragZoomStartingPoint.rawVal;
        const currentPoint = screenToSvgCoordinates(interactiveLayerSvg, event);

        isDragZooming.val = false;
        dragZoomStartingPoint.val = null;
        dragZoomCurrentPoint.val = null;

        const selectedMinX = Math.min(startingPoint.x, currentPoint.x);
        const selectedMaxX = Math.max(startingPoint.x, currentPoint.x);
        const selectedMinY = Math.min(startingPoint.y, currentPoint.y);
        const selectedMaxY = Math.max(startingPoint.y, currentPoint.y);

        const selectedWidth = selectedMaxX - selectedMinX;
        const selectedHeight = selectedMaxY - selectedMinY;

        if (selectedWidth > 0 || selectedHeight > 0) {
            const currentXDataRange = xAxisDataRange.rawVal;
            const currentYDataRange = yAxisDataRange.rawVal;
            const currentXChartRange = xAxisChartRange.rawVal;
            const currentYChartRange = yAxisChartRange.rawVal;

            let newXDataMin = scale(selectedMinX, {old: currentXChartRange, new: currentXDataRange}, 0);
            let newXDataMax = scale(selectedMaxX, {old: currentXChartRange, new: currentXDataRange}, 0);
            let newYDataMin = scale(selectedMinY, {old: currentYChartRange, new: currentYDataRange}, 0);
            let newYDataMax = scale(selectedMaxY, {old: currentYChartRange, new: currentYDataRange}, 0);

            if (newXDataMin > newXDataMax) [newXDataMin, newXDataMax] = [newXDataMax, newXDataMin];
            if (newYDataMin > newYDataMax) [newYDataMin, newYDataMax] = [newYDataMax, newYDataMin];

            xAxisDataRange.val = {min: newXDataMin, max: newXDataMax};
            yAxisDataRange.val = {min: newYDataMin, max: newYDataMax};

            isZoomed.val = true;
        }
    };

    const getSharedDefinitions = (drawinAreaClipId, yAxisClipId, xAxisClipId) => defs(
        {},
        clipPath(
            {id: getDOMId(drawinAreaClipId)},
            () => rect({
                x: topLeft.val.x,
                y: topLeft.val.y,
                width: Math.max(bottomRight.val.x - bottomLeft.val.x, 0),
                height: Math.max(bottomLeft.val.y - topLeft.val.y, 0),
            }),
        ),
        yAxisClipId ? clipPath(
            {id: getDOMId(yAxisClipId)},
            () => rect({
                x: 0,
                y: topLeft.val.y - 10,
                width: 999999.9,
                height: Math.max(bottomLeft.val.y - topLeft.val.y, 0),
            }),
        ) : undefined,
        xAxisClipId ? clipPath(
            {id: getDOMId(xAxisClipId)},
            () => rect({
                x: topLeft.val.x,
                y: topLeft.val.y,
                width: Math.max(bottomRight.val.x - bottomLeft.val.x, 0),
                height: 999999.9,
            }),
        ) : undefined,
    );

    const resetZoom = () => {
        isZoomed.val = false;
        xAxisDataRange.val = {...initialXAxisDataRange.rawVal};
        yAxisDataRange.val = {...initialYAxisDataRange.rawVal};
        dataPoints.val = [...dataPoints.rawVal];
    };

    const getPoint = (original) => {
        let point = dataPointsMapping.rawVal[`${original.x}-${original.y}`];
        if (!point) {
            point = {x: asSVGX(original.x), y: asSVGY(original.y)};
        }
        return {...point, originalX: original.x, originalY: original.y};
    };

    const tooltipText = van.state('');
    const shouldShowTooltip = van.state(false);
    const tooltipExtraStyle = van.state('');
    const tooltipElement = Tooltip({
        text: tooltipText,
        show: shouldShowTooltip,
        position: '--',
        style: tooltipExtraStyle,
    });
    const showTooltip = (message, point) => {
        let timeout;

        tooltipText.val = message;
        tooltipExtraStyle.val = 'visibility: hidden;';
        shouldShowTooltip.val = true;

        timeout = setTimeout(() => {
            const tooltipRect = tooltipElement.getBoundingClientRect();
            let tooltipX = point.x + 10;
            let tooltipY = point.y + 10;

            if (tooltipX + tooltipRect.width >= bottomRight.rawVal.x) {
                tooltipX = point.x - tooltipRect.width - 10;
            }

            tooltipExtraStyle.val = `transform: translate(${tooltipX}px, ${tooltipY}px);`;

            clearTimeout(timeout);
        }, 0);
    };
    const hideTooltip = () => {
        tooltipText.val = '';   
        tooltipExtraStyle.val = '';
        shouldShowTooltip.val = false;
    };

    return div(
        {
            id: getDOMId('chart-canvas'),
            class: 'tg-chart',
            style: () => `width: ${canvasWidth.val}px; height: ${canvasHeight.val}px;`,
            onmouseenter: () => isHoveringOver.val = true,
            onmouseleave: () => isHoveringOver.val = false,
        },
        svg(
            {
                width: '100%',
                height: '100%',
                style: 'z-index: 0;',
                class: 'tg-chart-layer axis-layer',
                viewBox: () => `0 0 ${canvasWidth.val} ${canvasHeight.val}`,
            },
            getSharedDefinitions('axis-clippath', 'y-axis-ticks-clippath', 'x-axis-ticks-clippath'),
            () => {
                const maxY = canvasHeight.val;
                const yLabelPos = {x: verticalAxisLabelLeftMargin, y: (bottomLeft.val.y - topLeft.val.y) / 2 + topLeft.val.y};
                const xLabelPos = {x: (bottomRight.val.x - bottomLeft.val.x) / 2, y: maxY - horizontalAxisLabelBottomMargin};

                return g(
                    {},
                    yAxisLabel.val ? text({...yLabelPos, 'text-anchor': 'middle', 'dominant-baseline': 'central', transform: `rotate(-90, ${yLabelPos.x}, ${yLabelPos.y})`, fill: 'var(--caption-text-color)'}, yAxisLabel.val) : null,
                    xAxisLabel.val ? text({...xLabelPos, fill: 'var(--caption-text-color)'}, xAxisLabel.val) : null,
                );
            },
            () => {
                const {min: yMin, max: yMax} = yAxisDataRange.val;
                const ticks = niceTicks(yMin, yMax, yAxisTicksCount.val);
                if (!yAxisLabel.val) {
                    return g();
                }

                afterMount(() => {
                    resizeChartBoundaries();
                });

                return g(
                    {},
                    g(
                        {id: getDOMId('y-axis-ticks-group'), 'clip-path': `url(#${getDOMId('y-axis-ticks-clippath')})`},
                        ...ticks.map(value => {
                            const tickY = asSVGY(value);
                            if (tickY < topLeft.rawVal.y || (tickY + tickTextHeight) > bottomLeft.rawVal.y) {
                                return undefined;
                            }

                            return text(
                                {x: verticalAxisTicksLeftMargin, y: tickY, class: 'text-small', 'dominant-baseline': 'central', fill: 'var(--caption-text-color)'},
                                Math.floor(value * 1000) / 1000,
                            );
                        }),
                    ),
                    () => yRenderGridLines.val ? g(
                        {'clip-path': `url(#${getDOMId('y-axis-ticks-clippath')})`},
                        ...ticks.map(value => {
                            const tickY = asSVGY(value);
                            if (tickY < topLeft.rawVal.y || (tickY + tickTextHeight) > bottomLeft.rawVal.y) {
                                return undefined;
                            }

                            return line({
                                x1: bottomLeft.val.x,
                                y1: tickY,
                                x2: bottomRight.val.x,
                                y2: tickY,
                                stroke: colorMap.lightGrey,
                            });
                        }),
                    ) : g(),
                );
            },
            () => {
                xAxisChartRange.val;

                const maxY = canvasHeight.val;
                const {min: xMin, max: xMax} = xAxisDataRange.val;
                const ticks = getAdaptiveTimeTicks([xMin, xMax], 4, 8);
                const labels = formatSmartTimeTicks(ticks);

                return g(
                    {},
                    g(
                        {id: getDOMId('x-axis-ticks-group'), 'clip-path': `url(#${getDOMId('x-axis-ticks-clippath')})`},
                        ...ticks.map((value, idx) => {
                            const tickX = asSVGX(value.getTime());
                            const labelLines = typeof labels[idx] === 'string' ? [labels[idx]] : labels[idx];
                            return g(
                                {},
                                labelLines.map((line, lineIdx) => text(
                                    {x: tickX, y: maxY - horizontalAxisTicksBottomMargin + (lineIdx * 15), 'text-anchor': 'middle', 'dominant-baseline': 'central', class: 'text-small', fill: 'var(--caption-text-color)'},
                                    line,
                                )),
                            );
                        }),
                    ),
                    () => xRenderGridLines.val ? g(
                        {'clip-path': `url(#${getDOMId('x-axis-ticks-clippath')})`},
                        ...ticks.map(value => {
                            const tickX = asSVGX(value.getTime());

                            return line({
                                x1: tickX,
                                y1: bottomRight.val.y,
                                x2: tickX,
                                y2: topRight.val.y,
                                stroke: colorMap.lightGrey,
                            });
                        }),
                    ) : g(),
                );
            },
            g(
                {},
                () => yRenderLine.val ? line({x1: bottomLeft.val.x, y1: bottomLeft.val.y, x2: topLeft.val.x, y2: topLeft.val.y, stroke: colorMap.grey }) : g(),
                () => xRenderLine.val ? line({x1: bottomLeft.val.x, y1: bottomLeft.val.y, x2: bottomRight.val.x, y2: bottomRight.val.y, stroke: colorMap.grey }) : g(),
            ),
        ),
        svg(
            {
                width: '100%',
                height: '100%',
                style: 'z-index: 2;',
                class: 'tg-chart-layer interactive-layer',
                viewBox: () => `0 0 ${canvasWidth.val} ${canvasHeight.val}`,
            },
            getSharedDefinitions('markers-clippath'),
            () => {
                const width = bottomRight.val.x - bottomLeft.val.x;
                const height = bottomLeft.val.y - topLeft.val.y;

                return rect({
                    x: topLeft.val.x,
                    y: topLeft.val.y,
                    width: Math.max(width, 0),
                    height: Math.max(height, 0),
                    fill: isDragZooming.val ? draggingOverlayColor : 'transparent',
                    ontouchstart: startDragZoom,
                    onmousedown: startDragZoom,
                });
            },
            () => {
                const children = [];
                if (legendRenderer.val) {
                    children.push(
                        legendRenderer.rawVal({y: 20, x: topLeft.val.x}),
                    );
                }

                if (markersRenderer.val) {
                    children.push(
                        g(
                            {'clip-path': `url(#${getDOMId('markers-clippath')})`},
                            markersRenderer.rawVal(getPoint, showTooltip, hideTooltip),
                        )
                    );
                }

                if (isHoveringOver.val) {
                    children.push(
                        foreignObject(
                            {y: 0, x: canvasWidth.val - actionsWidth - (spacing * 2), width: actionsWidth, height: actionsHeight, class: 'visible-overflow'},
                            withTooltip(
                                Button({
                                    type: 'icon',
                                    icon: 'zoom_out_map',
                                    iconSize: 20,
                                    style: 'overflow: visible;',
                                    onclick: resetZoom,
                                }),
                                {position: 'bottom-left', text: 'Autoscale'},
                            ),
                        )
                    );
                }

                if (children.length <= 0) {
                    children.push(g());
                }

                return g(
                    {class: 'visible-overflow'},
                    ...children,
                );
            },
            () => {
                const isDragging = isDragZooming.val;
                const currentPoint = dragZoomCurrentPoint.val;
                const startingPoint = dragZoomStartingPoint.rawVal;
                if (!isDragging || !currentPoint || !startingPoint) {
                    return g(); // NOTE: vanjs+svg might have an issue, if this is null, subsquent state changes won't trigger this reactive function
                }

                const x = Math.min(startingPoint.x, currentPoint.x);
                const y = Math.min(startingPoint.y, currentPoint.y);
                const rectHeight = Math.abs(currentPoint?.y - startingPoint?.y);
                const rectWidth = Math.abs(currentPoint?.x - startingPoint?.x);

                const strokeDashArray = [
                    cornerDash,
                    rectWidth - cornerDash*2,
                    cornerDash + 0.001,
                    0.001,
                    cornerDash,
                    rectHeight - cornerDash*2,
                    cornerDash,
                    0.001,
                    cornerDash,
                    rectWidth - cornerDash*2,
                    cornerDash,
                    0.001,
                    cornerDash,
                    rectHeight - cornerDash*2,
                    cornerDash,
                    0.001,
                ];

                return g(
                    {style: 'z-index: 3;'},
                    rect({
                        x: x,
                        y: y,
                        width: rectWidth,
                        height: rectHeight,
                        fill: 'transparent',
                        stroke: colorMap.grey,
                        'stroke-width': 3,
                        'stroke-dasharray': strokeDashArray.join(','),
                    }),
                );
            },
            foreignObject({fill: 'none', width: '100%', height: '100%', 'pointer-events': 'none', style: 'overflow: visible;'}, tooltipElement),
        ),
        svg(
            {
                width: '100%',
                height: '100%',
                style: 'z-index: 1;',
                viewBox: () => `0 0 ${canvasWidth.val} ${canvasHeight.val}`,
            },
            getSharedDefinitions('charts-clippath'),
            g(
                {'clip-path': `url(#${getDOMId('charts-clippath')})`},
                ...charts.map((renderer) => () => {
                    const dataPointsMapping_ = dataPointsMapping.val;
                    if (Object.keys(dataPointsMapping_).length <= 0) {
                        return g();
                    }

                    return renderer(
                        { minX: 0, minY: 0, width: canvasWidth.val, height: canvasHeight.val },
                        { topLeft: topLeft.val, topRight: topRight.val, bottomLeft: bottomLeft.val, bottomRight: bottomRight.val },
                        getPoint,
                    );
                }),
            ),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-chart {
    position: relative;
}

.tg-chart > svg {
    z-index: 1;
}

.tg-chart > svg {
    position: absolute;
}
`);

export { ChartCanvas };
