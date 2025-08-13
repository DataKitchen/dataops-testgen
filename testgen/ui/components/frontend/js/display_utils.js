function formatTimestamp(
    /** @type number | string */ timestamp,
    /** @type boolean */ show_year,
) {
    if (timestamp) {
        const date = new Date(typeof timestamp === 'number' ? timestamp * 1000 : timestamp);
        if (!isNaN(date)) {
            const months = [ 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec' ];
            const hours = date.getHours();
            const minutes = date.getMinutes();
            return `${months[date.getMonth()]} ${date.getDate()}, ${show_year ? date.getFullYear() + ' at ': ''}${(hours % 12) || 12}:${String(minutes).padStart(2, '0')} ${hours / 12 >= 1 ? 'PM' : 'AM'}`;
        }
    }
    return '--';
}

function formatDuration(/** @type string */ duration) {
    if (!duration) {
        return '--';
    }

    const [ hour, minute, second ] = duration.split(':');
    let formatted = [
        { value: Number(hour), unit: 'h' },
        { value: Number(minute), unit: 'm' },
        { value: Number(second), unit: 's' },
    ].map(({ value, unit }) => value ? `${value}${unit}` : '')
    .join(' ');

    return formatted.trim() || '< 1s';
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

// https://m2.material.io/design/color/the-color-system.html#tools-for-picking-colors
const colorMap = {
    red: '#EF5350', // Red 400
    orange: '#FF9800', // Orange 500
    yellow: '#FDD835', // Yellow 600
    green: '#9CCC65', // Light Green 400
    limeGreen: '#C0CA33', // Lime Green 600
    purple: '#AB47BC', // Purple 400
    purpleLight: '#CE93D8', // Purple 200
    blue: '#2196F3', // Blue 500
    blueLight: '#90CAF9', // Blue 200
    indigo: '#5C6BC0', // Indigo 400
    teal: '#26A69A', // Teal 400
    brown: '#8D6E63', // Brown 400
    brownLight: '#D7CCC8', // Brown 100
    brownDark: '#4E342E', // Brown 800
    grey: '#BDBDBD', // Gray 400
    empty: 'var(--empty)', // Light: Gray 200, Dark: Gray 800
    emptyLight: 'var(--empty-light)', // Light: Gray 50, Dark: Gray 900
    emptyTeal: 'var(--empty-teal)',
}

const DISABLED_ACTION_TEXT = 'You do not have permissions to perform this action. Contact your administrator.';

export { formatTimestamp, formatDuration, formatNumber, capitalize, humanReadableSize, colorMap, DISABLED_ACTION_TEXT };
