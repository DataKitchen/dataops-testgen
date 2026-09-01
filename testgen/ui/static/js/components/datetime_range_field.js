/**
 * @typedef Properties
 * @type {object}
 * @property {Date?} start
 * @property {Date?} end
 * @property {function({start: Date?, end: Date?, valid: boolean, error: string?})?} onChange
 * @property {{ms: number, label: string}?} maxSpan Longest permitted start-to-end distance
 * @property {string?} class
 */
import van from '../van.min.js';
import { getValue, isState, loadStylesheet } from '../utils.js';
import {
    DATE_TIME_PARTS,
    PART_LIMITS,
    applyDigit,
    composeDateTime,
    decomposeDateTime,
    stepPart,
} from '../time_range_utils.js';

const { div, small, span } = van.tags;

const BOUNDS = ['start', 'end'];
const PART_PLACEHOLDER = { month: 'MM', day: 'DD', year: 'YYYY', hour: 'hh', minute: 'mm', meridiem: '--' };
const SEPARATOR_BEFORE = { day: '/', year: '/', hour: ' ', minute: ':', meridiem: ' ' };
const ORDER_ERROR = 'Start must be before end.';
const SPAN_ERROR = (/** @type string */ label) => `Range cannot be longer than ${label}.`;

const DateTimeRangeField = (/** @type Properties */ props) => {
    loadStylesheet('datetimeRangeField', stylesheet);

    const bounds = {
        start: isState(props.start) ? props.start : van.state(getValue(props.start) ?? null),
        end: isState(props.end) ? props.end : van.state(getValue(props.end) ?? null),
    };
    const parts = {
        start: van.state(decomposeDateTime(bounds.start.rawVal)),
        end: van.state(decomposeDateTime(bounds.end.rawVal)),
    };
    const error = van.state('');

    // Segment currently being typed into, and the digits typed so far. Cleared on focus change.
    let typing = { key: '', buffer: '' };
    const segmentKeys = BOUNDS.flatMap((bound) => DATE_TIME_PARTS.map((part) => `${bound}.${part}`));
    /** @type {Object.<string, HTMLElement>} */
    const segmentElements = {};

    const rangeError = (/** @type Date? */ start, /** @type Date? */ end) => {
        if (!start || !end) {
            return '';
        }
        if (start >= end) {
            return ORDER_ERROR;
        }
        const maxSpan = getValue(props.maxSpan);
        return maxSpan && end - start > maxSpan.ms ? SPAN_ERROR(maxSpan.label) : '';
    };

    // Re-runs validation and reports outward. Writes no bound, so a derive may call it.
    const notify = () => {
        const start = composeDateTime(parts.start.rawVal);
        const end = composeDateTime(parts.end.rawVal);

        error.val = rangeError(start, end);
        (props.onChange?.val ?? props.onChange)?.({
            start,
            end,
            valid: !!start && !!end && !error.rawVal,
            error: error.rawVal || null,
        });
    };

    const publish = () => {
        const start = composeDateTime(parts.start.rawVal);
        const end = composeDateTime(parts.end.rawVal);

        if (bounds.start.rawVal?.getTime() !== start?.getTime()) {
            bounds.start.val = start;
        }
        if (bounds.end.rawVal?.getTime() !== end?.getTime()) {
            bounds.end.val = end;
        }
        notify();
    };

    const setParts = (/** @type string */ bound, /** @type object */ next) => {
        parts[bound].val = next;
        publish();
    };

    // An external write (a calendar click) rebuilds this bound's segments and re-runs validation.
    // This must call notify rather than publish: VanJS drops any state a derive both reads and
    // writes during the same run from that derive's dependencies, so writing bounds[bound] back
    // here would leave the derive dead after its first run. Declared after notify so the derive can
    // reach it on that first, eager run.
    for (const bound of BOUNDS) {
        van.derive(() => {
            const incoming = bounds[bound].val;
            if (incoming?.getTime() !== composeDateTime(parts[bound].rawVal)?.getTime()) {
                parts[bound].val = decomposeDateTime(incoming);
                notify();
            }
        });
    }

    const focusSegment = (/** @type string */ key) => {
        typing = { key, buffer: '' };
        segmentElements[key]?.focus();
    };

    const moveFocus = (/** @type string */ key, /** @type number */ delta) => {
        const next = segmentKeys[segmentKeys.indexOf(key) + delta];
        if (next) {
            focusSegment(next);
        }
    };

    const onKeyDown = (/** @type string */ bound, /** @type string */ part, /** @type KeyboardEvent */ event) => {
        const key = `${bound}.${part}`;
        const current = parts[bound].rawVal;

        if (event.key === 'ArrowRight') {
            moveFocus(key, 1);
        } else if (event.key === 'ArrowLeft') {
            moveFocus(key, -1);
        } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
            typing = { key, buffer: '' };
            setParts(bound, stepPart(part, current, event.key === 'ArrowUp' ? 1 : -1));
        } else if (event.key === 'Backspace') {
            typing = { key, buffer: '' };
            setParts(bound, { ...current, [part]: null });
        } else if (part === 'meridiem' && ['a', 'p'].includes(event.key.toLowerCase())) {
            setParts(bound, { ...current, meridiem: event.key.toLowerCase() === 'a' ? 'AM' : 'PM' });
        } else if (part !== 'meridiem' && /^[0-9]$/.test(event.key)) {
            const buffer = typing.key === key ? typing.buffer : '';
            const result = applyDigit(part, current, buffer, event.key);
            typing = { key, buffer: result.buffer };
            setParts(bound, result.parts);
            if (result.advance) {
                moveFocus(key, 1);
            }
        } else {
            return;
        }

        event.preventDefault();
    };

    const displayPart = (/** @type string */ bound, /** @type string */ part) => {
        const key = `${bound}.${part}`;
        const value = parts[bound].val[part];

        if (part === 'meridiem') {
            return value ?? PART_PLACEHOLDER.meridiem;
        }
        if (typing.key === key && typing.buffer) {
            return typing.buffer.padStart(PART_LIMITS[part].length, '0');
        }
        if (value == null) {
            return PART_PLACEHOLDER[part];
        }
        return String(value).padStart(PART_LIMITS[part].length, '0');
    };

    // Segment elements are built once. Rebuilding them inside a reactive closure would blow away
    // focus on every keystroke; only their text child is reactive.
    const buildSegment = (/** @type string */ bound, /** @type string */ part) => {
        const key = `${bound}.${part}`;
        const element = span(
            {
                class: 'tg-datetime-segment',
                tabindex: 0,
                'data-testid': 'datetime-segment',
                'data-part': key,
                onkeydown: (/** @type KeyboardEvent */ event) => onKeyDown(bound, part, event),
                onfocus: () => {
                    if (typing.key !== key) {
                        typing = { key, buffer: '' };
                    }
                },
            },
            () => displayPart(bound, part),
        );
        segmentElements[key] = element;
        return element;
    };

    const buildBound = (/** @type string */ bound) => DATE_TIME_PARTS.flatMap((part) => [
        SEPARATOR_BEFORE[part] ? span({ class: 'tg-datetime-separator' }, SEPARATOR_BEFORE[part]) : '',
        buildSegment(bound, part),
    ]);

    publish();

    return div(
        {
            class: () => `flex-column fx-gap-1 ${getValue(props.class) ?? ''}`,
            'data-testid': 'datetime-range-field',
        },
        div(
            { class: 'flex-row fx-align-flex-center tg-datetime-range--field' },
            ...buildBound('start'),
            span({ class: 'tg-datetime-range--arrow' }, '→'),
            ...buildBound('end'),
        ),
        () => error.val
            ? small({ class: 'tg-datetime-range--error', 'data-testid': 'datetime-range-error' }, error.val)
            : '',
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-datetime-range--field {
    display: flex;
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 13px;
    color: var(--primary-text-color);
}

.tg-datetime-range--field:focus-within {
    border-color: var(--primary-color);
}

.tg-datetime-range--arrow {
    margin: 0 8px;
    color: var(--secondary-text-color);
}

.tg-datetime-segment {
    padding: 0 2px;
    border-radius: 2px;
    outline: none;
    cursor: default;
}

.tg-datetime-segment:focus,
.tg-datetime-segment:focus-visible {
    background-color: var(--primary-color);
    color: white;
}

.tg-datetime-separator {
    color: var(--secondary-text-color);
}

.tg-datetime-range--error {
    color: var(--error-color);
}
`);

export { DateTimeRangeField };
