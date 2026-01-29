/**
 * @import { CronSample } from '../types.js';
 * 
 * @typedef Schedule
 * @type {object}
 * @property {string?} cron_tz
 * @property {string} cron_expr
 * @property {boolean} active
 * 
 * @typedef MonitorSuite
 * @type {object}
 * @property {string?} id
 * @property {string?} table_groups_id
 * @property {string?} test_suite
 * @property {number?} monitor_lookback
 * @property {boolean?} monitor_regenerate_freshness
 * @property {('low'|'medium'|'high')?} predict_sensitivity
 * @property {number?} predict_min_lookback
 * @property {boolean?} predict_exclude_weekends
 * @property {string?} predict_holiday_codes
 *
 * @typedef FormState
 * @type {object}
 * @property {boolean} dirty
 * @property {boolean} valid
 * 
 * @typedef Properties
 * @type {object}
 * @property {Schedule} schedule
 * @property {MonitorSuite} monitorSuite
 * @property {CronSample?} cronSample
 * @property {boolean?} hideActiveCheckbox
 * @property {(sch: Schedule, ts: MonitorSuite, state: FormState) => void} onChange
 */
import van from '../van.min.js';
import { getValue, isEqual, loadStylesheet, emitEvent } from '../utils.js';
import { Input } from './input.js';
import { RadioGroup } from './radio_group.js';
import { Caption } from './caption.js';
import { Select } from './select.js';
import { Checkbox } from './checkbox.js';
import { CrontabInput } from './crontab_input.js';
import { Icon } from './icon.js';
import { Link } from './link.js';
import { numberBetween, required } from '../form_validators.js';
import { timezones, holidayCodes } from '../values.js';
import { formatDurationSeconds, humanReadableDuration } from '../display_utils.js';

const { div, span } = van.tags;

/**
 * 
 * @param {Properties} props 
 * @returns 
 */
const MonitorSettingsForm = (props) => {
    loadStylesheet('monitor-settings-form', stylesheet);

    const schedule = getValue(props.schedule) ?? {};
    const cronTimezone = van.state(schedule.cron_tz ?? Intl.DateTimeFormat().resolvedOptions().timeZone);
    const cronExpression = van.state(schedule.cron_expr ?? '0 */12 * * *');
    const scheduleActive = van.state(schedule.active ?? true);

    const monitorSuite = getValue(props.monitorSuite) ?? {};
    const monitorLookback = van.state(monitorSuite.monitor_lookback ?? 14);
    const monitorRegenerateFreshness = van.state(monitorSuite.monitor_regenerate_freshness ?? true);
    const predictSensitivity = van.state(monitorSuite.predict_sensitivity ?? 'medium');
    const predictMinLookback = van.state(monitorSuite.predict_min_lookback ?? 30);
    const predictExcludeWeekends = van.state(monitorSuite.predict_exclude_weekends ?? false);
    const predictHolidayCodes = van.state(monitorSuite.predict_holiday_codes);

    const updatedSchedule = van.derive(() => {
        return {
            cron_tz: cronTimezone.val,
            cron_expr: cronExpression.val,
            active: scheduleActive.val,
        };
    });
    const updatedTestSuite = van.derive(() => {
        return {
            id: monitorSuite.id,
            table_groups_id: monitorSuite.table_groups_id,
            test_suite: monitorSuite.test_suite,
            monitor_lookback: monitorLookback.val,
            monitor_regenerate_freshness: monitorRegenerateFreshness.val,
            predict_sensitivity: predictSensitivity.val,
            predict_min_lookback: predictMinLookback.val,
            predict_exclude_weekends: predictExcludeWeekends.val,
            predict_holiday_codes: predictHolidayCodes.val,
        };
    });

    const dirty = van.derive(() => !isEqual(updatedSchedule.val, schedule) || !isEqual(updatedTestSuite.val, monitorSuite));
    const validityPerField = van.state({});

    van.derive(() => {
        const fieldsValidity = validityPerField.val;
        const isValid = Object.keys(fieldsValidity).length > 0 &&
            Object.values(fieldsValidity).every(v => v);
        props.onChange?.(updatedSchedule.val, updatedTestSuite.val, { dirty: dirty.val, valid: isValid });
    });

    const setFieldValidity = (field, validity) => {
        validityPerField.val = {...validityPerField.rawVal, [field]: validity};
    }

    return div(
        { class: 'flex-column fx-gap-4' },
        MainForm(
            { setValidity: setFieldValidity },
            monitorLookback,
            monitorRegenerateFreshness,
            cronExpression,
        ),
        ScheduleForm(
            { 
                hideActiveCheckbox: getValue(props.hideActiveCheckbox),
                originalActive: schedule.active ?? true,
                cronSample: props.cronSample,
                setValidity: setFieldValidity,
            },
            cronTimezone,
            cronExpression,
            scheduleActive,
        ),
        PredictionForm(
            { setValidity: setFieldValidity },
            predictSensitivity,
            predictMinLookback,
            predictExcludeWeekends,
            predictHolidayCodes,
        ),
    );
};

const MainForm = (
    options,
    monitorLookback,
    monitorRegenerateFreshness,
    cronExpression,
) => {
    return div(
        { class: 'flex-column fx-gap-4' },
        div(
            { class: 'flex-row fx-align-flex-start fx-gap-3 fx-flex-wrap monitor-settings-row' },
            Input({
                name: 'monitor_lookback',
                label: 'Lookback Runs',
                value: monitorLookback,
                help: 'Number of monitor runs to summarize on dashboard views',
                helpPlacement: 'bottom-right',
                type: 'number',
                step: 1,
                onChange: (value, state) => {
                    monitorLookback.val = value;
                    options.setValidity?.('monitor_lookback', state.valid);
                },
                validators: [
                    numberBetween(1, 200, 1),
                ],
            }),
            () => {
                const cronDuration = determineDuration(cronExpression.val);
                if (!cronDuration || !monitorLookback.val) {
                    return span({});
                }

                const lookbackDuration = monitorLookback.val * cronDuration;
                return div(
                    { class: 'flex-column' },
                    span({ class: 'text-caption mt-1 mb-3' }, 'Lookback Window'),
                    span(humanReadableDuration(formatDurationSeconds(lookbackDuration))),
                );
            }
        ),
        div(
            { class: 'flex-row fx-align-flex-start fx-gap-3 fx-flex-wrap mb-2 monitor-settings-row' },
            Checkbox({
                name: 'monitor_regenerate_freshness',
                label: 'Reconfigure Freshness monitors after profiling',
                help: 'When enabled, Freshness monitors will be automatically reconfigured with new fingerprints after each profiling run',
                width: 350,
                checked: monitorRegenerateFreshness,
                onChange: (value) => monitorRegenerateFreshness.val = value,
            }),
        ),
    );
};

const ScheduleForm = (
    options,
    cronTimezone,
    cronExpression,
    scheduleActive,
) => {
    const cronEditorValue = van.derive(() => {
        if (cronExpression.val && cronTimezone.val) {
            emitEvent('GetCronSample', {payload: {cron_expr: cronExpression.val, tz: cronTimezone.val}});
        }
        return {
            timezone: cronTimezone.val,
            expression: cronExpression.val,
        };
    });

    return div(
        { class: 'flex-column fx-gap-3 border border-radius-1 p-3', style: 'position: relative;' },
        Caption({content: 'Monitor Schedule', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),        
        div(
            { class: 'flex-row fx-gap-3 fx-flex-wrap fx-align-flex-start monitor-settings-row' },
            () => Select({
                label: 'Timezone',
                options: timezones.map(tz_ => ({label: tz_, value: tz_})),
                value: cronTimezone,
                allowNull: false,
                filterable: true,
                onChange: (value) => cronTimezone.val = value,
                portalClass: 'short-select-portal',
            }),
            CrontabInput({
                name: 'monitor_settings_schedule',
                sample: options.cronSample,
                value: cronEditorValue,
                modes: ['x_hours', 'x_days'],
                onChange: (value) => cronExpression.val = value,
            }),
        ),
        !options.hideActiveCheckbox
            ? div(
                { class: 'flex-row fx-gap-6 fx-flex-wrap' },
                Checkbox({
                    name: 'schedule_active',
                    label: 'Activate schedule',
                    checked: scheduleActive,
                    onChange: (value) => scheduleActive.val = value,
                }),
                () => !scheduleActive.val
                    ? div(
                        { class: 'flex-row fx-gap-1' },
                        Icon({ style: 'font-size: 16px; color: var(--purple);' }, 'info'),
                        span(
                            { class: 'text-caption', style: 'color: var(--purple);' },
                            options.originalActive ? 'Monitor schedule will be paused.' : 'Monitor schedule is paused.',
                        ),
                    )
                    : '',
            )
            : null,
    );
};

const PredictionForm = (
    options,
    predictSensitivity,
    predictMinLookback,
    predictExcludeWeekends,
    predictHolidayCodes,
) => {
    const excludeHolidays = van.state(!!predictHolidayCodes.val);
    return div(
        { class: 'flex-column fx-gap-4 border border-radius-1 p-3', style: 'position: relative;' },
        Caption({content: 'Prediction Model', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),        
        div(
            { class: 'flex-row fx-gap-3 fx-flex-wrap monitor-settings-row' },
            RadioGroup({
                name: 'predict_sensitivity',
                label: 'Sensitivity',
                options: [
                    { label: 'Low', value: 'low' },
                    { label: 'Medium', value: 'medium' },
                    { label: 'High', value: 'high' },
                ],
                value: predictSensitivity,
                onChange: (value) => predictSensitivity.val = value,
            }),
            Input({
                name: 'predict_min_lookback',
                type: 'number',
                label: 'Minimum Training Lookback',
                value: predictMinLookback,
                help: 'Minimum number of monitor runs to use for training models',
                type: 'number',
                step: 1,
                onChange: (value, state) => {
                    predictMinLookback.val = value;
                    options.setValidity?.('predict_min_lookback', state.valid);
                },
                validators: [
                    numberBetween(30, 1000, 1),
                ],
            }),
        ),
        Checkbox({
            name: 'predict_exclude_weekends',
            label: 'Exclude weekends from training',
            width: 250,
            checked: predictExcludeWeekends,
            onChange: (value) => predictExcludeWeekends.val = value,
        }),
        Checkbox({
            name: 'predict_exclude_holidays',
            label: 'Exclude holidays from training',
            width: 250,
            checked: excludeHolidays,
            onChange: (value) => excludeHolidays.val = value,
        }),
        () => excludeHolidays.val
            ? div(
                { style: 'width: 250px; margin: -8px 0 0 25px; position: relative;' },
                Input({
                    name: 'predict_holiday_codes',
                    label: 'Holiday Codes',
                    value: predictHolidayCodes,
                    help: 'Comma-separated list of country or financial market codes',
                    autocompleteOptions: holidayCodes,
                    onChange: (value, state) => {
                        predictHolidayCodes.val = value;
                        options.setValidity?.('predict_holiday_codes', state.valid);
                    },
                    validators: [
                        required,
                    ],
                }),
                div(
                    { class: 'flex-row fx-gap-1 mt-1 text-caption' },
                    span({}, 'See supported'),
                    Link({
                        open_new: true,
                        label: 'codes',
                        href: 'https://holidays.readthedocs.io/en/latest/#available-countries',
                        right_icon: 'open_in_new',
                        right_icon_size: 13,
                    }),
                ),
            )
            : '',
    );
};

/**
 * @param {string} expression
 * @returns {number}
 */
function determineDuration(expression) {
    // Normalize whitespace
    const expr = (expression || '').trim().replace(/\s+/g, ' ');
    // "M * * * *"
    if (/^\d{1,2} \* \* \* \*$/.test(expr)) {
        return 60 * 60; // 1 hour
    }
    // "M */H * * *"
    let match = expr.match(/^\d{1,2} \*\/(\d+) \* \* \*$/);
    if (match) {
        return Number(match[1]) * 60 * 60; // H hours
    }
    // "M H * * *"
    if (/^\d{1,2} \d{1,2} \* \* \*$/.test(expr)) {
        return 24 * 60 * 60; // 1 day
    }
    // "M H */D * *"
    match = expr.match(/^\d{1,2} \d{1,2} \*\/(\d+) \* \*$/);
    if (match) {
        return Number(match[1]) * 24 * 60 * 60; // D days
    }
    return null;
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.monitor-settings-row > * {
    flex: 250px;
}
`);

export { MonitorSettingsForm };
