/**
 * @typedef RangeBounds
 * @type {object}
 * @property {number} start Epoch milliseconds, inclusive
 * @property {number} end Epoch milliseconds, exclusive
 *
 * @typedef RangePreset
 * @type {object}
 * @property {string} value
 * @property {string} label
 */

const DEFAULT_RANGE = 'default';
const CUSTOM_RANGE = 'custom';

/** @type {RangePreset[]} */
const TREND_RANGE_PRESETS = [
    { value: DEFAULT_RANGE, label: 'Default' },
    { value: '7d', label: '7 days' },
    { value: '1mo', label: '1 month' },
    { value: '3mo', label: '3 months' },
    { value: CUSTOM_RANGE, label: 'Custom' },
];

const RANGE_EXPRESSION = /^(\d+)(d|w|mo|y)$/;

// Widest window a custom range may cover. 366 days so that a calendar year spanning a leap day
// still fits.
const MAX_CUSTOM_SPAN = { ms: 366 * 24 * 60 * 60 * 1000, label: '1 year' };

/**
 * Shift a date back by whole months, snapping to the last day of the target month instead of
 * rolling forward. Without this, Mar 31 minus one month lands on Mar 3.
 *
 * @param {Date} date
 * @param {number} months
 * @returns {Date}
 */
function shiftMonthsBack(date, months) {
    const dayOfMonth = date.getDate();
    const shifted = new Date(date.getTime());
    shifted.setDate(1);
    shifted.setMonth(shifted.getMonth() - months);

    const lastDayOfTargetMonth = new Date(shifted.getFullYear(), shifted.getMonth() + 1, 0).getDate();
    shifted.setDate(Math.min(dayOfMonth, lastDayOfTargetMonth));
    return shifted;
}

/**
 * Convert a relative range expression into absolute epoch-millisecond bounds ending at `now`,
 * using the browser's local calendar. Returns null for the default range and for any expression
 * that cannot be parsed, meaning "no bounds".
 *
 * @param {string} expression `<count><unit>`, unit one of d, w, mo, y — e.g. '7d', '2w', '3mo'
 * @param {Date} now
 * @returns {RangeBounds?}
 */
function relativeRangeToBounds(expression, now = new Date()) {
    const match = RANGE_EXPRESSION.exec(expression ?? '');
    if (!match) {
        return null;
    }

    const count = Number(match[1]);
    const unit = match[2];

    let start = new Date(now.getTime());
    if (unit === 'd' || unit === 'w') {
        start.setDate(start.getDate() - count * (unit === 'w' ? 7 : 1));
    } else {
        start = shiftMonthsBack(now, unit === 'mo' ? count : count * 12);
    }

    return { start: start.getTime(), end: now.getTime() };
}

/**
 * Whether a forecast that opens at `firstPredictionTime` belongs on the axis for the given window.
 *
 * The forecast sits near the present, so a window that closed well before it would stretch the axis
 * across the intervening gap and squeeze the selected days into a sliver. The gap is measured
 * against the window's own width, which keeps the forecast for a window ending at now and drops it
 * for one ending months back, with no threshold to tune. An unbounded window, or one with no
 * forecast, always passes.
 *
 * @param {number?} windowStart Epoch milliseconds
 * @param {number?} windowEnd Epoch milliseconds
 * @param {number?} firstPredictionTime Epoch milliseconds
 * @returns {boolean}
 */
function forecastBelongsOnAxis(windowStart, windowEnd, firstPredictionTime) {
    if (windowStart == null || windowEnd == null || firstPredictionTime == null) {
        return true;
    }
    return firstPredictionTime - windowEnd <= windowEnd - windowStart;
}

/**
 * @typedef Parts
 * @type {object}
 * @property {number?} month 1-12
 * @property {number?} day
 * @property {number?} year
 * @property {number?} hour 1-12
 * @property {number?} minute
 * @property {('AM'|'PM')?} meridiem
 */

const DATE_TIME_PARTS = ['month', 'day', 'year', 'hour', 'minute', 'meridiem'];

const PART_LIMITS = {
    month: { min: 1, max: 12, length: 2 },
    day: { min: 1, max: 31, length: 2 },
    year: { min: 1970, max: 9999, length: 4 },
    hour: { min: 1, max: 12, length: 2 },
    minute: { min: 0, max: 59, length: 2 },
};

const EMPTY_PARTS = { month: null, day: null, year: null, hour: null, minute: null, meridiem: null };

/**
 * @param {number} year
 * @param {number} month 1-12
 * @returns {number}
 */
function daysInMonth(year, month) {
    return new Date(year, month, 0).getDate();
}

/**
 * Upper bound for a segment. February accepts 29 until a *complete* year is typed, so a leap day
 * can be entered in either order; composeDateTime makes the final call. A half-typed year is not a
 * year: `2` on the way to `2024` would otherwise resolve against 1902, since JS maps years 0-99 to
 * 1900 + year.
 *
 * @param {string} part
 * @param {Parts} parts
 * @returns {number}
 */
function partMax(part, parts) {
    if (part === 'day') {
        const yearIsComplete = String(parts.year ?? '').length === PART_LIMITS.year.length;
        return daysInMonth(yearIsComplete ? parts.year : 2024, parts.month ?? 1);
    }
    return PART_LIMITS[part].max;
}

/**
 * @param {Parts} parts
 * @returns {Parts}
 */
function clampParts(parts) {
    if (parts.day == null) {
        return parts;
    }
    const max = partMax('day', parts);
    return parts.day > max ? { ...parts, day: max } : parts;
}

/**
 * @param {string} part
 * @param {Parts} parts
 * @param {number} delta
 * @returns {Parts}
 */
function stepPart(part, parts, delta) {
    if (part === 'meridiem') {
        return { ...parts, meridiem: parts.meridiem === 'PM' ? 'AM' : 'PM' };
    }

    const { min } = PART_LIMITS[part];
    const max = partMax(part, parts);
    const current = parts[part] ?? (part === 'year' ? new Date().getFullYear() : min);

    let next = current + delta;
    if (next > max) {
        next = min;
    }
    if (next < min) {
        next = max;
    }
    return clampParts({ ...parts, [part]: next });
}

/**
 * Fold one typed digit into a segment. `buffer` holds the digits typed so far in this segment and
 * is returned empty once the segment fills. `advance` is true when no further digit could refine
 * the value, so the caller should move focus on.
 *
 * @param {string} part
 * @param {Parts} parts
 * @param {string} buffer
 * @param {string} digit
 * @returns {{parts: Parts, buffer: string, advance: boolean}}
 */
function applyDigit(part, parts, buffer, digit) {
    const limits = PART_LIMITS[part];
    const max = partMax(part, parts);

    let typed = `${buffer}${digit}`;
    if (typed.length > limits.length) {
        typed = digit;
    }
    if (part !== 'year' && Number(typed) > limits.max) {
        typed = digit;
    }

    const numeric = Number(typed);
    const filled = typed.length >= limits.length;
    const value = part === 'year' && !filled ? numeric : Math.min(Math.max(numeric, limits.min), max);

    return {
        parts: clampParts({ ...parts, [part]: value }),
        buffer: filled ? '' : typed,
        advance: filled || (part !== 'year' && numeric * 10 > max),
    };
}

/**
 * @param {Parts} parts
 * @returns {Date?} null unless every segment is filled and the combination is a real date
 */
function composeDateTime(parts) {
    const { month, day, year, hour, minute, meridiem } = parts;
    if ([month, day, year, hour, minute].some((value) => value == null) || !meridiem) {
        return null;
    }
    if (month < 1 || month > 12 || hour < 1 || hour > 12 || minute < 0 || minute > 59) {
        return null;
    }
    if (year < PART_LIMITS.year.min || year > PART_LIMITS.year.max) {
        return null;
    }
    if (day < 1 || day > daysInMonth(year, month)) {
        return null;
    }

    const hours24 = meridiem === 'PM' ? (hour % 12) + 12 : hour % 12;
    return new Date(year, month - 1, day, hours24, minute, 0, 0);
}

/**
 * @param {Date?} date
 * @returns {Parts}
 */
function decomposeDateTime(date) {
    if (!date) {
        return { ...EMPTY_PARTS };
    }

    const hours = date.getHours();
    return {
        month: date.getMonth() + 1,
        day: date.getDate(),
        year: date.getFullYear(),
        hour: (hours % 12) || 12,
        minute: date.getMinutes(),
        meridiem: hours >= 12 ? 'PM' : 'AM',
    };
}

export {
    CUSTOM_RANGE,
    DATE_TIME_PARTS,
    DEFAULT_RANGE,
    EMPTY_PARTS,
    MAX_CUSTOM_SPAN,
    PART_LIMITS,
    TREND_RANGE_PRESETS,
    applyDigit,
    clampParts,
    composeDateTime,
    daysInMonth,
    decomposeDateTime,
    forecastBelongsOnAxis,
    partMax,
    relativeRangeToBounds,
    stepPart,
};
