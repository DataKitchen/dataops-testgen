// https://stackoverflow.com/a/4955179
function niceNumber(value, round = false) {
    const exponent = Math.floor(Math.log10(value));
    const fraction = value / Math.pow(10, exponent);
    let niceFraction;

    if (round) {
        if (fraction < 1.5) {
            niceFraction = 1;
        } else if (fraction < 3) {
            niceFraction = 2;
        } else if (fraction < 7) {
            niceFraction = 5;
        } else {
            niceFraction = 10;
        }
    } else {
        if (fraction <= 1) {
            niceFraction = 1;
        } else if (fraction <= 2) {
            niceFraction = 2;
        } else if (fraction <= 5) {
            niceFraction = 5;
        } else {
            niceFraction = 10;
        }
    }

    return niceFraction * Math.pow(10, exponent);
}

function niceBounds(axisStart, axisEnd, tickCount = 4) {
    let axisWidth = axisEnd - axisStart;

    if (axisWidth == 0) {
        axisStart -= 0.5;
        axisEnd += 0.5;
        axisWidth = axisEnd - axisStart;
    }

    const niceRange = niceNumber(axisWidth);
    const niceTick = niceNumber(niceRange / (tickCount - 1), true);
    axisStart = Math.floor(axisStart / niceTick) * niceTick;
    axisEnd = Math.ceil(axisEnd / niceTick) * niceTick;

    return {
        min: axisStart,
        max: axisEnd,
        step: niceTick,
        range: axisEnd - axisStart,
    };
}

function niceTicks(axisStart, axisEnd, tickCount = 4) {
    const { min, max, step } = niceBounds(axisStart, axisEnd, tickCount);
    const ticks = [];
    let currentTick = min;
    while (currentTick <= max) {
        ticks.push(currentTick);
        currentTick = currentTick + step;
    }
    return ticks;
}

/**
 *
 * @typedef Range
 * @type {object}
 * @property {number} max
 * @property {number} min
 *
 * @param {number} value
 * @param {({new: Range, old: Range})} ranges
 * @property {number?} zero
 */
function scale(value, ranges, zero=0) {
    const oldRange = (ranges.old.max - ranges.old.min);
    const newRange = (ranges.new.max - ranges.new.min);

    if (oldRange === 0) {
        return zero;
    }

    return ((value - ranges.old.min) * newRange / oldRange) + ranges.new.min;
}

/**
 * @param {SVGElement} svg 
 * @param {MouseEvent} event 
 * @returns {({x: number, y: number})}
 */
function screenToSvgCoordinates(svg, event) {
    const pt = svg.createSVGPoint();
    pt.x = event.offsetX;
    pt.y = event.offsetY;
    const inverseCTM = svg.getScreenCTM().inverse();
    const svgPoint = pt.matrixTransform(inverseCTM);
    return svgPoint;
}

/**
 * Generates an array of "nice" and properly spaced tick dates for a time-series axis.
 * It automatically selects the best time step (granularity) based on the range.
 *
 * @param {Date[]} dates An array of Date objects representing the data points.
 * @param {number} minTicks The minimum number of ticks desired.
 * @param {number} maxTicks The maximum number of ticks desired.
 * @returns {Date[]} An array of Date objects for the axis ticks.
 */
function getAdaptiveTimeTicks(dates, minTicks, maxTicks) {
    if (!dates || dates.length === 0) {
        return [];
    }

    if (typeof dates[0] === 'number') {
        dates = dates.map(d => new Date(d));
    }

    const timestamps = dates.map(d => d.getTime());
    const minTime = Math.min(...timestamps);
    const maxTime = Math.max(...timestamps);
    const rangeMs = maxTime - minTime;

    const timeSteps = [
        { name: 'hour', ms: 3600000 },
        { name: '4 hours', ms: 4 * 3600000 },
        { name: '8 hours', ms: 8 * 3600000 },
        { name: 'day', ms: 86400000 },
        { name: 'week', ms: 7 * 86400000 },
        { name: 'month', ms: null, count: 1 },
        { name: '3 months', ms: null, count: 3 },
        { name: '6 months', ms: null, count: 6 },
        { name: 'year', ms: null, count: 12 },
    ];
    
    let bestStepIndex = -1;
    let ticks = [];

    for (let i = timeSteps.length - 1; i >= 0; i--) {
        const step = timeSteps[i];
        let estimatedTickCount;

        if (step.ms !== null) {
            estimatedTickCount = Math.ceil(rangeMs / step.ms) + 1;
        } else {
            estimatedTickCount = estimateMonthYearTicks(minTime, maxTime, step.count);
        }

        if (estimatedTickCount <= maxTicks) {
            bestStepIndex = i;
            break; 
        }
    }
    
    if (bestStepIndex === -1) {
        const roughStep = rangeMs / (maxTicks - 1);
        const niceMsStep = getNiceStep(roughStep);
        return generateMsTicks(minTime, maxTime, niceMsStep).map(t => new Date(t));
    }

    const bestStep = timeSteps[bestStepIndex];
    if (bestStep.ms !== null) {
        ticks = generateMsTicks(minTime, maxTime, bestStep.ms).map(t => new Date(t));
    } else {
        ticks = generateMonthYearTicks(minTime, maxTime, bestStep.count);
    }
    
    while (ticks.length < minTicks && bestStepIndex > 0) {
        bestStepIndex--;
        const nextStep = timeSteps[bestStepIndex];

        if (nextStep.ms !== null) {
            ticks = generateMsTicks(minTime, maxTime, nextStep.ms).map(t => new Date(t));
        } else {
            ticks = generateMonthYearTicks(minTime, maxTime, nextStep.count);
        }
    }
    
    return ticks;
}

/** Calculates a "nice" step size (1, 2, 5, etc. * power of 10) for raw milliseconds. */
function getNiceStep(step) {
    const exponent = Math.floor(Math.log10(step)); 
    const fraction = step / Math.pow(10, exponent); 
    let niceFraction;
    if (fraction <= 1) niceFraction = 1;
    else if (fraction <= 2) niceFraction = 2;
    else if (fraction <= 5) niceFraction = 5;
    else return 1 * Math.pow(10, exponent + 1); // Next power of 10
    
    return niceFraction * Math.pow(10, exponent);
}

/** Generates ticks for fixed-length steps (hours, days, weeks). */
function generateMsTicks(minTime, maxTime, niceStepMs) {
    // let tickStart = minTime; // Use it to start at minimum tick
    let tickStart = Math.floor(minTime / niceStepMs) * niceStepMs; // Use it to start at a nicer tick
    while (tickStart > minTime) {
        tickStart -= niceStepMs;
    }

    const ONE_DAY = 86400000;
    if (niceStepMs >= ONE_DAY) {
        const date = new Date(tickStart);
        date.setHours(0, 0, 0, 0);
        tickStart = date.getTime();
        while (tickStart + niceStepMs < minTime) {
             tickStart += niceStepMs;
        }
    }

    const ticks = [];
    const epsilon = 1e-10; 
    let currentTick = tickStart;
    
    while (currentTick <= maxTime + niceStepMs + epsilon) {
        ticks.push(Math.round(currentTick)); 
        currentTick += niceStepMs;
    }

    return ticks;
}

/** Generates ticks for variable-length steps (months, years). */
function generateMonthYearTicks(minTime, maxTime, monthStep) {
    const ticks = [];
    let currentDate = new Date(minTime);
    
    currentDate.setDate(1); // Set to the 1st of the month
    currentDate.setHours(0, 0, 0, 0); 
    
    let year = currentDate.getFullYear();
    let month = currentDate.getMonth();
    
    while (month % monthStep !== 0) {
        month--;
        if (month < 0) {
            month = 11;
            year--;
        }
    }
    currentDate.setFullYear(year, month, 1);
    
    while (currentDate.getTime() + monthStep * 30 * 86400000 < minTime) {
        currentDate.setMonth(currentDate.getMonth() + monthStep);
    }
    
    while (currentDate.getTime() <= maxTime) {
        ticks.push(new Date(currentDate.getTime()));
        currentDate.setMonth(currentDate.getMonth() + monthStep);
    }
    
    if (ticks.length > 0 && currentDate.getTime() - maxTime < monthStep * 30 * 86400000 / 2) {
         ticks.push(new Date(currentDate.getTime()));
    }

    return ticks;
}

/** Estimates the number of ticks for month/year steps. */
function estimateMonthYearTicks(minTime, maxTime, monthStep) {
    const minDate = new Date(minTime);
    const maxDate = new Date(maxTime);
    
    let years = maxDate.getFullYear() - minDate.getFullYear();
    let months = maxDate.getMonth() - minDate.getMonth();
    let totalMonths = years * 12 + months;

    return Math.ceil(totalMonths / monthStep) + 2;
}

/**
 * Formats an array of Date objects into smart, non-redundant labels.
 * It only displays the year, month, or day when it changes from the previous tick.
 *
 * @param {Date[]} ticks An array of Date objects (the tick values).
 * @returns {Array<string|string[]>} An array of formatted labels (strings or string arrays).
 */
function formatSmartTimeTicks(ticks) {
    if (!ticks || ticks.length === 0) {
        return [];
    }

    const formattedLabels = [];
    const locale = 'en-US';

    const yearFormat = { year: 'numeric' };
    const monthFormat = { month: 'short' };
    const dayFormat = { day: 'numeric' };
    const timeFormat = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
    const ONE_DAY_MS = 86400000;

    const formatPart = (date, options) => date.toLocaleString(locale, options);

    for (let i = 0; i < ticks.length; i++) {
        const currentTick = ticks[i];
        const previousTick = ticks[i - 1];
        const nextTick = ticks[i + 1];
        
        let needsYear = false;
        let needsMonth = false;
        let needsDay = false;
        let needsTime = false;
        
        if (!previousTick) {
            needsYear = true;
            needsMonth = true;
            needsDay = true;
            needsTime = nextTick && nextTick.getTime() - currentTick.getTime() < ONE_DAY_MS;
        } else {
            const curr = currentTick;
            const prev = previousTick;

            if (curr.getFullYear() !== prev.getFullYear()) {
                needsYear = true;
                needsMonth = true;
                needsDay = true;
            } else if (curr.getMonth() !== prev.getMonth()) {
                needsMonth = true;
                needsDay = true;
            } else if (curr.getDate() !== prev.getDate()) {
                needsDay = true;
                needsMonth = true;
            }

            const stepMs = currentTick.getTime() - previousTick.getTime();
            if (stepMs < ONE_DAY_MS || (curr.getHours() !== 0 || curr.getMinutes() !== 0)) {
                needsTime = true;
            }
        }
        
        let line1 = [];
        let line2 = [];

        if (needsTime) {
            line1.push(formatPart(currentTick, timeFormat));
        }

        if (needsMonth || needsDay) {
            let datePart = [];
            if (needsMonth) {
                datePart.push(formatPart(currentTick, monthFormat));
            }
            if (needsDay) {
                datePart.push(formatPart(currentTick, dayFormat));
            }
            const dateString = datePart.join(' ');

            if (needsTime) {
                line2.push(dateString);
            } else {
                line1.push(dateString);
            }
        }

        if (needsYear) {
            line2.push(formatPart(currentTick, yearFormat));
        }
        
        line1 = line1.filter(p => p.length > 0).join(' ');
        line2 = line2.filter(p => p.length > 0).join(' ');

        if (line2.length > 0) {
            formattedLabels.push([line1, line2]);
        } else {
            formattedLabels.push(line1);
        }
    }

    return formattedLabels;
}

export { niceBounds, niceTicks, scale, screenToSvgCoordinates, getAdaptiveTimeTicks, formatSmartTimeTicks };
