function formatTimestamp(/** @type number */ timestamp) {
    if (!timestamp) {
        return '--';
    }
    
    const date = new Date(timestamp);
    const months = [ 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec' ];
    const hours = date.getHours();
    const minutes = date.getMinutes();
    return `${months[date.getMonth()]} ${date.getDate()}, ${hours % 12}:${String(minutes).padStart(2, '0')} ${hours / 12 > 1 ? 'PM' : 'AM'}`;
}

function formatDuration(/** @type string */ duration) {
    if (!duration) {
        return '--';
    }
        
    const { hour, minute, second } = duration.split(':');
    let formatted = [
        { value: Number(hour), unit: 'h' },
        { value: Number(minute), unit: 'm' },
        { value: Number(second), unit: 's' },
    ].map(({ value, unit }) => value ? `${value}${unit}` : '')
    .join(' ');

    return formatted.trim() || '< 1s';
}

export { formatTimestamp, formatDuration };
