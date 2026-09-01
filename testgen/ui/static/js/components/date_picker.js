/**
 * @typedef Properties
 * @type {object}
 * @property {Date?} value
 * @property {function(Date)?} onChange
 * @property {string?} class
 */
import van from '../van.min.js';
import { getValue, isState, loadStylesheet } from '../utils.js';
import { daysInMonth } from '../time_range_utils.js';
import { Button } from './button.js';

const { div, span } = van.tags;

const WEEKDAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
const MONTH_LABEL = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' });

const startOfMonth = (/** @type Date */ date) => new Date(date.getFullYear(), date.getMonth(), 1);

const DatePicker = (/** @type Properties */ props) => {
    loadStylesheet('datePicker', stylesheet);

    const value = isState(props.value) ? props.value : van.state(getValue(props.value) ?? null);
    const visibleMonth = van.state(startOfMonth(value.rawVal ?? new Date()));

    van.derive(() => {
        const selected = value.val;
        if (selected) {
            visibleMonth.val = startOfMonth(selected);
        }
    });

    const shiftMonth = (/** @type number */ delta) => {
        const current = visibleMonth.rawVal;
        visibleMonth.val = new Date(current.getFullYear(), current.getMonth() + delta, 1);
    };

    const selectDay = (/** @type number */ day) => {
        const month = visibleMonth.rawVal;
        const previous = value.rawVal;
        const selected = new Date(
            month.getFullYear(),
            month.getMonth(),
            day,
            previous?.getHours() ?? 0,
            previous?.getMinutes() ?? 0,
        );
        value.val = selected;
        (props.onChange?.val ?? props.onChange)?.(selected);
    };

    return div(
        { class: () => `tg-date-picker ${getValue(props.class) ?? ''}`, 'data-testid': 'date-picker' },
        div(
            { class: 'flex-row fx-justify-space-between fx-align-flex-center' },
            Button({
                type: 'icon',
                icon: 'chevron_left',
                onclick: () => shiftMonth(-1),
            }),
            span(
                { class: 'tg-date-picker--month', 'data-testid': 'date-picker-month' },
                () => MONTH_LABEL.format(visibleMonth.val),
            ),
            Button({
                type: 'icon',
                icon: 'chevron_right',
                onclick: () => shiftMonth(1),
            }),
        ),
        div(
            { class: 'tg-date-picker--grid' },
            WEEKDAYS.map((weekday) => span({ class: 'tg-date-picker--weekday' }, weekday)),
        ),
        () => {
            const month = visibleMonth.val;
            const selected = value.val;
            const leadingBlanks = new Date(month.getFullYear(), month.getMonth(), 1).getDay();
            const total = daysInMonth(month.getFullYear(), month.getMonth() + 1);

            const cells = [];
            for (let blank = 0; blank < leadingBlanks; blank++) {
                cells.push(span({ class: 'tg-date-picker--blank' }));
            }
            for (let day = 1; day <= total; day++) {
                const isSelected = !!selected
                    && selected.getFullYear() === month.getFullYear()
                    && selected.getMonth() === month.getMonth()
                    && selected.getDate() === day;
                cells.push(span(
                    {
                        class: `tg-date-picker--day clickable ${isSelected ? 'selected' : ''}`,
                        'data-testid': 'date-picker-day',
                        'data-day': day,
                        onclick: () => selectDay(day),
                    },
                    day,
                ));
            }
            return div({ class: 'tg-date-picker--grid' }, cells);
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-date-picker {
    width: 232px;
}

.tg-date-picker--month {
    font-size: 13px;
    font-weight: 500;
    color: var(--primary-text-color);
}

.tg-date-picker--grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 2px;
}

.tg-date-picker--weekday {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 24px;
    font-size: 11px;
    color: var(--caption-text-color);
}

.tg-date-picker--day {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 28px;
    border-radius: 4px;
    font-size: 13px;
    color: var(--primary-text-color);
}

.tg-date-picker--day:hover {
    background-color: var(--select-hover-background);
}

.tg-date-picker--day.selected {
    background-color: var(--primary-color);
    color: white;
}
`);

export { DatePicker };
