// Chrome does not include UTC: https://github.com/mdn/browser-compat-data/issues/25828
const timezones = [ 'UTC', ...Intl.supportedValuesOf('timeZone').filter(tz => tz !== 'UTC') ];

export { timezones };
