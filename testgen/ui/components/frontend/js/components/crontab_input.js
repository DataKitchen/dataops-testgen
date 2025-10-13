/**
 * @typedef EditOptions
 * @type {object}
 * @property {CronSample?} sample
 * @property {(expr: string) => void} onChange
 * @property {(() => void)?} onClose
 * 
 * @typedef CronSample
 * @type {object}
 * @property {string?} error
 * @property {string[]?} samples
 * @property {string?} readable_expr
 * 
 * @typedef InitialValue
 * @type {object}
 * @property {string} timezone
 * @property {string} expression
 * 
 * @typedef Options
 * @type {object}
 * @property {(string|null)} id
 * @property {string?} testId
 * @property {string?} class
 * @property {CronSample?} sample
 * @property {InitialValue?} value
 * @property {((expr: string) => void)?} onChange
 */
import { getRandomId, getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';
import { Portal } from './portal.js';
import { Button } from './button.js';
import { Input } from './input.js';
import { required } from '../form_validators.js';
import { Select } from './select.js';
import { Checkbox } from './checkbox.js';
import { Link } from './link.js';

const { div, span } = van.tags;

const CrontabInput = (/** @type Options */ props) => {
    loadStylesheet('crontab-input', stylesheet);

    const domId = van.derive(() => props.id?.val ?? `tg-crontab-wrapper-${getRandomId()}`);
    const opened = van.state(false);
    const expression = van.state(props.value?.rawVal?.expression ?? props.value?.expression ?? '');
    const readableSchedule = van.state(null);
    const timezone = van.derive(() => getValue(props.value)?.timezone);
    const disabled = van.derive(() => !timezone.val);
    const placeholder = van.derive(() => !timezone.val ? 'Select a timezone first' : 'Click to select schedule');

    const onEditorChange = (cronExpr) => {
        expression.val = cronExpr;
        const onChange = props.onChange?.val ?? props.onChange;
        if (onChange && cronExpr) {
            onChange(cronExpr);
        }
    };

    van.derive(() => {
        const sample = getValue(props.sample) ?? {};
        if (!sample.error && sample.readable_expr) {
            readableSchedule.val = `${sample.readable_expr} (${timezone.val})`;
        }
    });

    return div(
        {
            id: domId,
            class: () => `tg-crontab-input ${getValue(props.class) ?? ''}`,
            'data-testid': getValue(props.testId) ?? null,
        },
        div(
            {onclick: () => {
                if (!disabled.val) {
                    opened.val = true;
                }
            }},
            Input({
                label: 'Schedule',
                icon: 'calendar_clock',
                readonly: true,
                disabled: disabled,
                placeholder: placeholder,
                value: readableSchedule,
            }),
        ),
        Portal(
            {target: domId.val, align: 'right', style: 'width: 500px;', opened},
            () => CrontabEditorPortal(
                {
                    onChange: onEditorChange,
                    onClose: () => opened.val = false,
                    sample: props.sample,
                },
                expression,
            ),
        ),
  );
};

/**
 * @param {EditOptions} options
 * @param {import('../van.min.js').VanState<string>} expr
 * @returns {HTMLElement}
 */
const CrontabEditorPortal = ({sample, ...options}, expr) => {
    const mode = van.state(expr.rawVal ? determineMode(expr.rawVal) : 'x_hours');

    const xHoursState = {
        hours: van.state(1),
        minute: van.state(0),
    };
    const xDaysState = {
        days: van.state(1),
        hour: van.state(1),
        minute: van.state(0),
    };
    const certainDaysState = {
        sunday: van.state(false),
        monday: van.state(false),
        tuesday: van.state(false),
        wednesday: van.state(false),
        thursday: van.state(false),
        friday: van.state(false),
        saturday: van.state(false),
        hour: van.state(1),
        minute: van.state(0),
    };

    // Populate initial state based on the initial mode and expression
    populateInitialModeState(expr.rawVal, mode.rawVal, xHoursState, xDaysState, certainDaysState);

    van.derive(() => {
        if (mode.val === 'x_hours') {
            const hours = xHoursState.hours.val;
            const minute = xHoursState.minute.val;
            options.onChange(`${minute ?? 0} ${(hours && hours !== 1) ? '*/' + hours : '*'} * * *`);
        } else if (mode.val === 'x_days') {
            const days = xDaysState.days.val;
            const hour = xDaysState.hour.val;
            const minute = xDaysState.minute.val;
            options.onChange(`${minute ?? 0} ${hour ?? 0} ${(days && days !== 1) ? '*/' + days : '*'} * *`);
        } else if (mode.val === 'certain_days') {
            const days = [];
            const dayMap = [
                { key: 'sunday', val: certainDaysState.sunday.val, label: 'SUN' },
                { key: 'monday', val: certainDaysState.monday.val, label: 'MON' },
                { key: 'tuesday', val: certainDaysState.tuesday.val, label: 'TUE' },
                { key: 'wednesday', val: certainDaysState.wednesday.val, label: 'WED' },
                { key: 'thursday', val: certainDaysState.thursday.val, label: 'THU' },
                { key: 'friday', val: certainDaysState.friday.val, label: 'FRI' },
                { key: 'saturday', val: certainDaysState.saturday.val, label: 'SAT' },
            ];
            // Collect selected days
            dayMap.forEach(d => { if (d.val) days.push(d.label); });
            // If days are consecutive, use range notation
            let dayField = '*';
            if (days.length > 0) {
                // Find ranges
                const indices = days.map(d => dayMap.findIndex(dm => dm.label === d)).sort((a,b) => a-b);
                let ranges = [], rangeStart = null, prev = null;
                indices.forEach((idx, i) => {
                    if (rangeStart === null) rangeStart = idx;
                    if (prev !== null && idx !== prev + 1) {
                        ranges.push([rangeStart, prev]);
                        rangeStart = idx;
                    }
                    prev = idx;
                    if (i === indices.length - 1) ranges.push([rangeStart, idx]);
                });
                // Convert ranges to crontab format
                dayField = ranges.map(([start, end]) => {
                    if (start === end) return dayMap[start].label;
                    return `${dayMap[start].label}-${dayMap[end].label}`;
                }).join(',');
            }
            const hour = certainDaysState.hour.val;
            const minute = certainDaysState.minute.val;
            options.onChange(`${minute ?? 0} ${hour ?? 0} * * ${dayField}`);
        }
    });

    return div(
        { class: 'tg-crontab-editor flex-column border-radius-1 mt-1' },
        div(
            { class: 'tg-crontab-editor-content flex-row' },
            div(
                { class: 'tg-crontab-editor-left flex-column' },
                span(
                    {
                        class: () => `tg-crontab-editor-mode p-4 ${mode.val === 'x_hours' ? 'selected' : ''}`,
                        onclick: () => mode.val = 'x_hours',
                    },
                    'Every x hours',
                ),
                span(
                    {
                        class: () => `tg-crontab-editor-mode p-4 ${mode.val === 'x_days' ? 'selected' : ''}`,
                        onclick: () => mode.val = 'x_days',
                    },
                    'Every x days',
                ),
                span(
                    {
                        class: () => `tg-crontab-editor-mode p-4 ${mode.val === 'certain_days' ? 'selected' : ''}`,
                        onclick: () => mode.val = 'certain_days',
                    },
                    'On certain days',
                ),
                span(
                    {
                        class: () => `tg-crontab-editor-mode p-4 ${mode.val === 'custom' ? 'selected' : ''}`,
                        onclick: () => mode.val = 'custom',
                    },
                    'Custom',
                ),
            ),
            div(
                { class: 'tg-crontab-editor-right flex-column p-4 fx-flex' },
                div(
                    { class: () => `${mode.val === 'x_hours' ? '' : 'hidden'}`},
                    div(
                        {class: 'flex-row fx-gap-2 mb-2'},
                        span({}, 'Every'),
                        () => Select({
                            label: "",
                            options: Array.from({length: 24}, (_, i) => i).map(i => ({label: i.toString(), value: i})),
                            triggerStyle: 'inline',
                            portalClass: 'tg-crontab--select-portal',
                            value: xHoursState.hours,
                            onChange: (value) => xHoursState.hours.val = value,
                        }),
                        span({}, 'hours'),
                    ),
                    div(
                        {class: 'flex-row fx-gap-2'},
                        span({}, 'on'),
                        span({}, 'minute'),
                        () => Select({
                            label: "",
                            options: Array.from({length: 60}, (_, i) => i).map(i => ({label: i.toString().padStart(2, '0'), value: i})),
                            triggerStyle: 'inline',
                            portalClass: 'tg-crontab--select-portal',
                            value: xHoursState.minute,
                            onChange: (value) => xHoursState.minute.val = value,
                        }),
                    ),
                ),
                div(
                    { class: () => `${mode.val === 'x_days' ? '' : 'hidden'}`},
                    div(
                        {class: 'flex-row fx-gap-2 mb-2'},
                        span({}, 'Every'),
                        () => Select({
                            label: "",
                            options: Array.from({length: 31}, (_, i) => i + 1).map(i => ({label: i.toString(), value: i})),
                            triggerStyle: 'inline',
                            portalClass: 'tg-crontab--select-portal',
                            value: xDaysState.days,
                            onChange: (value) => xDaysState.days.val = value,
                        }),
                        span({}, 'days'),
                    ),
                    div(
                        {class: 'flex-row fx-gap-2'},
                        span({}, 'at'),
                        () => Select({
                            label: "",
                            options: Array.from({length: 24}, (_, i) => i).map(i => ({label: i.toString(), value: i})),
                            triggerStyle: 'inline',
                            portalClass: 'tg-crontab--select-portal',
                            value: xDaysState.hour,
                            onChange: (value) => xDaysState.hour.val = value,
                        }),
                        () => Select({
                            label: "",
                            options: Array.from({length: 60}, (_, i) => i).map(i => ({label: i.toString().padStart(2, '0'), value: i})),
                            triggerStyle: 'inline',
                            portalClass: 'tg-crontab--select-portal',
                            value: xDaysState.minute,
                            onChange: (value) => xDaysState.minute.val = value,
                        }),
                    ),
                ),
                div(
                    { class: () => `${mode.val === 'certain_days' ? '' : 'hidden'}`},
                    div(
                        {class: 'flex-row fx-gap-2 mb-2'},
                        Checkbox({
                            label: 'Monday',
                            checked: certainDaysState.monday,
                            onChange: (v) => certainDaysState.monday.val = v,
                        }),
                        Checkbox({
                            label: 'Tuesday',
                            checked: certainDaysState.tuesday,
                            onChange: (v) => certainDaysState.tuesday.val = v,
                        }),
                        Checkbox({
                            label: 'Wednesday',
                            checked: certainDaysState.wednesday,
                            onChange: (v) => certainDaysState.wednesday.val = v,
                        }),
                    ),
                    div(
                        {class: 'flex-row fx-gap-2 mb-2'},
                        
                        Checkbox({
                            label: 'Thursday',
                            checked: certainDaysState.thursday,
                            onChange: (v) => certainDaysState.thursday.val = v,
                        }),
                        Checkbox({
                            label: 'Friday',
                            checked: certainDaysState.friday,
                            onChange: (v) => certainDaysState.friday.val = v,
                        }),
                        Checkbox({
                            label: 'Saturday',
                            checked: certainDaysState.saturday,
                            onChange: (v) => certainDaysState.saturday.val = v,
                        }),
                        Checkbox({
                            label: 'Sunday',
                            checked: certainDaysState.sunday,
                            onChange: (v) => certainDaysState.sunday.val = v,
                        }),
                    ),
                    div(
                        {class: 'flex-row fx-gap-2'},
                        span({}, 'at'),
                        () => Select({
                            label: "",
                            options: Array.from({length: 24}, (_, i) => i).map(i => ({label: i.toString(), value: i})),
                            triggerStyle: 'inline',
                            portalClass: 'tg-crontab--select-portal shorter',
                            value: certainDaysState.hour,
                            onChange: (value) => certainDaysState.hour.val = value,
                        }),
                        () => Select({
                            label: "",
                            options: Array.from({length: 60}, (_, i) => i).map(i => ({label: i.toString().padStart(2, '0'), value: i})),
                            triggerStyle: 'inline',
                            portalClass: 'tg-crontab--select-portal shorter',
                            value: certainDaysState.minute,
                            onChange: (value) => certainDaysState.minute.val = value,
                        }),
                    ),
                ),
                div(
                    { class: () => `${mode.val === 'custom' ? '' : 'hidden'}`},
                    () => Input({
                        name: 'cron_expr',
                        label: 'Cron Expression',
                        value: expr,
                        validators: [
                            required,
                            ((sampleState) => {
                                return () => {
                                    const sample = getValue(sampleState) ?? {};
                                    return sample.error || null;
                                };
                            })(sample),
                        ],
                        onChange: (value, state) => mode.val === 'custom' && options.onChange(value),
                    }),
                ),
                span({class: 'fx-flex'}, ''),
                div(
                    {class: 'flex-column fx-gap-1 mt-3 text-secondary'},
                    () => span(
                        { class: mode.val === 'custom' ? 'hidden': '' },
                        `Cron Expression: ${expr.val ?? ''}`,
                    ),
                    () => div(
                        { class: 'flex-column' },
                        span('Next Runs:'),
                        (getValue(sample) ?? {})?.samples?.map(item => span({ class: 'text-caption' }, item)),
                    ),
                    () => div(
                        {class: `flex-row fx-gap-1 text-caption ${mode.val === 'custom' ? '': 'hidden'}`},
                        span({}, 'Learn more about'),
                        Link({
                            open_new: true,
                            label: 'cron expressions',
                            href: 'https://crontab.guru/',
                            right_icon: 'open_in_new',
                            right_icon_size: 13,
                        }),
                    ),
                ),
            ),
        ),
        div(
            { class: 'flex-row fx-justify-space-between p-3' },
            span({class: 'fx-flex'}, ''),
            div(
                { class: 'flex-row fx-gap-2' },
                Button({
                    type: 'stroked',
                    color: 'primary',
                    label: 'Close',
                    style: 'width: auto;',
                    onclick: options?.onClose,
                }),
            ),
        ),
    );
};

/**
 * Populates the state variables for the initial mode based on the cron expression
 * @param {string} expr
 * @param {string} mode
 * @param {object} xHoursState
 * @param {object} xDaysState
 * @param {object} certainDaysState
 */
function populateInitialModeState(expr, mode, xHoursState, xDaysState, certainDaysState) {
    const parts = (expr || '').trim().split(/\s+/);
    if (mode === 'x_hours' && parts.length === 5) {
        // e.g. "M */H * * *" or "M * * * *"
        xHoursState.minute.val = Number(parts[0]) || 0;
        if (parts[1].startsWith('*/')) {
            xHoursState.hours.val = Number(parts[1].slice(2)) || 1;
        } else {
            xHoursState.hours.val = 1;
        }
    } else if (mode === 'x_days' && parts.length === 5) {
        // e.g. "M H */D * *" or "M H * * *"
        xDaysState.minute.val = Number(parts[0]) || 0;
        xDaysState.hour.val = Number(parts[1]) || 0;
        if (parts[2].startsWith('*/')) {
            xDaysState.days.val = Number(parts[2].slice(2)) || 1;
        } else {
            xDaysState.days.val = 1;
        }
    } else if (mode === 'certain_days' && parts.length === 5) {
        // e.g. "M H * * DAY[,DAY...]"
        certainDaysState.minute.val = Number(parts[0]) || 0;
        certainDaysState.hour.val = Number(parts[1]) || 0;
        const days = parts[4].split(',');
        const dayKeys = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];
        const dayLabels = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
        dayKeys.forEach((key, idx) => {
            certainDaysState[key].val = days.some(d => {
                if (d.includes('-')) {
                    // Range, e.g. MON-WED
                    const [start, end] = d.split('-');
                    const startIdx = dayLabels.indexOf(start);
                    const endIdx = dayLabels.indexOf(end);
                    return idx >= startIdx && idx <= endIdx;
                }
                return d === dayLabels[idx];
            });
        });
    }
}

/**
 * @param {string} expression
 * @returns {'x_hours'|'x_days'|'certain_days'|'custom'}
 */
function determineMode(expression) {
    // Normalize whitespace
    const expr = (expression || '').trim().replace(/\s+/g, ' ');
    // x_hours: "M */H * * *" or "M * * * *"
    if (/^\d{1,2} \*\/\d+ \* \* \*$/.test(expr) || /^\d{1,2} \* \* \* \*$/.test(expr)) {
        return 'x_hours';
    }
    // x_days: "M H */D * *" or "M H * * *"
    if (/^\d{1,2} \d{1,2} \*\/\d+ \* \*$/.test(expr) || /^\d{1,2} \d{1,2} \* \* \*$/.test(expr)) {
        return 'x_days';
    }
    // certain_days: "M H * * DAY[,DAY...]" (DAY = SUN,MON,...)
    if (/^\d{1,2} \d{1,2} \* \* ((SUN|MON|TUE|WED|THU|FRI|SAT)(-(SUN|MON|TUE|WED|THU|FRI|SAT))?(,)?)+$/.test(expr)) {
        return 'certain_days';
    }
    return 'custom';
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-crontab-display {
  border-bottom: 1px dashed var(--border-color);
}

.tg-crontab-editor {
  border-radius: 8px;
  background: var(--portal-background);
  box-shadow: var(--portal-box-shadow);
  overflow: auto;
}

.tg-crontab-editor-content {
  border-bottom: 1px solid var(--border-color);
}

.tg-crontab-editor-left {
    border-right: 1px solid var(--border-color);
}

.tg-crontab-editor-right {
    place-self: stretch;
}

.tg-crontab-editor-mode {
    cursor: pointer;
}

.tg-crontab-editor-mode.selected,
.tg-crontab-editor-mode:hover {
  background: var(--select-hover-background);
}

.tg-crontab--select-portal {
    max-height: 150px;
    -ms-overflow-style: none;  /* Internet Explorer 10+ */
    scrollbar-width: none;  /* Firefox, Safari 18.2+, Chromium 121+ */
}
.tg-crontab--select-portal::-webkit-scrollbar { 
    display: none;  /* Older Safari and Chromium */
}

.tg-crontab--select-portal.shorter {
    max-height: 120px;
}
`);

export { CrontabInput };
