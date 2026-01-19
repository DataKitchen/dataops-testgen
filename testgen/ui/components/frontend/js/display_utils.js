function formatTimestamp(
    /** @type number | string */ timestamp,
    /** @type boolean */ showYear,
) {
    if (timestamp) {
        let date = timestamp;
        if (typeof timestamp === 'number') {
            date = new Date(timestamp.toString().length === 10 ? timestamp * 1000 : timestamp);
        }
        if (!isNaN(date)) {
            const months = [ 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec' ];
            const hours = date.getHours();
            const minutes = date.getMinutes();
            return `${months[date.getMonth()]} ${date.getDate()}, ${showYear ? date.getFullYear() + ' at ': ''}${(hours % 12) || 12}:${String(minutes).padStart(2, '0')} ${hours / 12 >= 1 ? 'PM' : 'AM'}`;
        }
    }
    return '--';
}

function formatDuration(
    /** @type Date | number | string */ startTime,
    /** @type Date | number | string */ endTime,
) {
    if (!startTime || !endTime) {
        return '--';
    }

    const startDate = new Date(typeof startTime === 'number' ? startTime * 1000 : startTime);
    const endDate = new Date(typeof endTime === 'number' ? endTime * 1000 : endTime);
    const totalSeconds = Math.floor((endDate.getTime() - startDate.getTime()) / 1000);

    let formatted = [
        { value: Math.floor(totalSeconds / (3600 * 24)), unit: 'd' },
        { value: Math.floor((totalSeconds % (3600 * 24)) / 3600), unit: 'h' },
        { value: Math.floor((totalSeconds % 3600) / 60), unit: 'm' },
        { value: totalSeconds % 60, unit: 's' },
    ].map(({ value, unit }) => value ? `${value}${unit}` : '')
    .join(' ');

    return formatted.trim() || '< 1s';
}

function humanReadableDuration(/** @type string */ duration) {
    if (duration === '< 1s') {
        return 'Less than 1 second';
    }

    const biggestPart = duration.split(' ')[0];

    const durationUnit = biggestPart.slice(-1)[0];
    const durationValue = Number(biggestPart.replace(durationUnit, ''));
    const unitTemplates = {
        d: (/** @type number */ value) => `${value} day${value === 1 ? '' : 's'}`,
        h: (/** @type number */ value) => `${value} hour${value === 1 ? '' : 's'}`,
        m: (/** @type number */ value) => `${value} minute${value === 1 ? '' : 's'}`,
        s: (/** @type number */ value) => `${value} second${value === 1 ? '' : 's'}`,
    };

    return unitTemplates[durationUnit](durationValue);
}

function formatNumber(/** @type number | string */ number, /** @type number */ decimals = 3) {
    if (!['number', 'string'].includes(typeof number) || isNaN(number)) {
        return '--';
    }
    // toFixed - rounds to specified number of decimal places
    // toLocaleString - adds commas as necessary
    return parseFloat(Number(number).toFixed(decimals)).toLocaleString();
}

function capitalize(/** @type string */ text) {
    return text.toLowerCase()
        .split(' ')
        .map((s) => s.charAt(0).toUpperCase() + s.substring(1))
        .join(' ');
}

/**
 * Display bytes in the closest unit with an integer part.
 * 
 * @param {number} bytes 
 * @returns {string}
 */
function humanReadableSize(bytes) {
    const thresholds = {
        MB: 1024 * 1024,
        KB: 1024,
    };

    for (const [unit, startsAt] of Object.entries(thresholds)) {
        if (bytes > startsAt) {
            return `${(bytes / startsAt).toFixed()}${unit}`;
        }
    }

    return `${bytes}B`;
}

const caseInsensitiveSort = new Intl.Collator('en').compare;
const caseInsensitiveIncludes = (/** @type string */ value, /** @type string */ search) => {
    if (value && search) {
        return value.toLowerCase().includes(search.toLowerCase());
    }
    return !search;
}

/**
 * Convert viewport units to pixels using the current
 * window's `innerHeight` and defaulting to the top window's
 * `innerHeight` when needed.
 * 
 * @param {number} value
 * @param {('height'|'width')} dim
 * @returns {number}
 */
function viewPortUnitsToPixels(value, dim) {
    if (typeof value !== 'number') {
        return 0;
    }

    const viewPortSize = window[`inner${capitalize(dim)}`] || window.top[`inner${capitalize(dim)}`];
    return (value / 100) * viewPortSize;
}

// https://m2.material.io/design/color/the-color-system.html#tools-for-picking-colors
const colorMap = {
    red: '#EF5350', // Red 400
    redLight: '#FFB6C180', // Clear red
    redDark: '#D32F2F', // Red 700
    orange: '#FF9800', // Orange 500
    yellow: '#FDD835', // Yellow 600
    green: '#9CCC65', // Light Green 400
    greenLight: '#90EE90FF', // Clear green
    limeGreen: '#C0CA33', // Lime Green 600
    purple: '#AB47BC', // Purple 400
    purpleLight: '#CE93D8', // Purple 200
    deepPurple: '#9575CD', // Deep Purple 300
    blue: '#2196F3', // Blue 500
    blueLight: '#90CAF9', // Blue 200
    indigo: '#5C6BC0', // Indigo 400
    teal: '#26A69A', // Teal 400
    tealDark: '#009688', // Teal 500
    brown: '#8D6E63', // Brown 400
    brownLight: '#D7CCC8', // Brown 100
    brownDark: '#4E342E', // Brown 800
    grey: '#BDBDBD', // Gray 400
    lightGrey: '#E0E0E0', // Gray 300
    empty: 'var(--empty)', // Light: Gray 200, Dark: Gray 800
    emptyLight: 'var(--empty-light)', // Light: Gray 50, Dark: Gray 900
    emptyTeal: 'var(--empty-teal)',
}

const DISABLED_ACTION_TEXT = 'You do not have permissions to perform this action. Contact your administrator.';

export {
    formatTimestamp,
    formatDuration,
    formatNumber,
    capitalize,
    humanReadableSize,
    caseInsensitiveSort,
    caseInsensitiveIncludes,
    humanReadableDuration,
    viewPortUnitsToPixels,
    colorMap,
    DISABLED_ACTION_TEXT,
};
