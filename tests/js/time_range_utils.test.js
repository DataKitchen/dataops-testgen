import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    CUSTOM_RANGE,
    DEFAULT_RANGE,
    EMPTY_PARTS,
    TREND_RANGE_PRESETS,
    applyDigit,
    clampParts,
    composeDateTime,
    daysInMonth,
    decomposeDateTime,
    partMax,
    relativeRangeToBounds,
    stepPart,
} from '../../testgen/ui/static/js/time_range_utils.js';

afterEach(() => {
    vi.useRealTimers();
});

const parts = (overrides) => ({ ...EMPTY_PARTS, ...overrides });

describe('relativeRangeToBounds', () => {
    const now = new Date(2024, 2, 31, 15, 0);

    it.each([
        ['7d', '2024-03-24T15:00:00.000Z'],
        ['2w', '2024-03-17T15:00:00.000Z'],
        ['1mo', '2024-02-29T15:00:00.000Z'],
        ['3mo', '2023-12-31T15:00:00.000Z'],
        ['1y', '2023-03-31T15:00:00.000Z'],
        ['0d', '2024-03-31T15:00:00.000Z'],
    ])('starts %s back at %s and ends now', (expression, start) => {
        const bounds = relativeRangeToBounds(expression, now);

        expect(new Date(bounds.start).toISOString()).toBe(start);
        expect(bounds.end).toBe(now.getTime());
    });

    it('snaps a year back from a leap day to Feb 28', () => {
        const bounds = relativeRangeToBounds('1y', new Date(2024, 1, 29));

        expect(new Date(bounds.start).toISOString()).toBe('2023-02-28T00:00:00.000Z');
    });

    it.each([DEFAULT_RANGE, CUSTOM_RANGE, null, undefined, '', '7', 'd7', '7h', '-1d'])(
        'returns null for %j',
        (expression) => {
            expect(relativeRangeToBounds(expression, now)).toBeNull();
        },
    );

    it('ends at the current time by default', () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date(2024, 5, 15, 9, 30));

        expect(relativeRangeToBounds('1d').end).toBe(Date.now());
    });
});

describe('daysInMonth', () => {
    it.each([
        [2024, 2, 29],
        [2023, 2, 28],
        [1900, 2, 28],
        [2000, 2, 29],
        [2024, 12, 31],
    ])('%s-%s has %s days', (year, month, days) => {
        expect(daysInMonth(year, month)).toBe(days);
    });
});

describe('partMax', () => {
    it.each([
        ['day', { month: 2, year: 2023 }, 28],
        ['day', { month: 2, year: 202 }, 29],
        ['day', { month: 2, year: null }, 29],
        ['day', { month: null }, 31],
        ['hour', {}, 12],
        ['minute', {}, 59],
    ])('%s with %j is at most %s', (part, partial, max) => {
        expect(partMax(part, partial)).toBe(max);
    });
});

describe('clampParts', () => {
    it('returns parts without a day unchanged', () => {
        const input = parts({ month: 2 });

        expect(clampParts(input)).toBe(input);
    });

    it('clamps a day past the end of the month', () => {
        expect(clampParts(parts({ month: 2, day: 31, year: 2023 })).day).toBe(28);
    });

    it('returns an in-range day unchanged', () => {
        const input = parts({ month: 2, day: 10, year: 2023 });

        expect(clampParts(input)).toBe(input);
    });
});

describe('stepPart', () => {
    it.each([
        ['month', { month: 12 }, 1, 1],
        ['month', { month: 1 }, -1, 12],
        ['minute', { minute: null }, 1, 1],
    ])('steps %s from %j by %s to %s', (part, partial, delta, expected) => {
        expect(stepPart(part, parts(partial), delta)[part]).toBe(expected);
    });

    it.each([
        [null, 'PM'],
        ['PM', 'AM'],
        ['AM', 'PM'],
    ])('toggles meridiem %j to %j', (meridiem, expected) => {
        expect(stepPart('meridiem', parts({ meridiem }), 1).meridiem).toBe(expected);
    });

    it('starts an empty year from the current year', () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date(2024, 5, 15));

        expect(stepPart('year', parts({}), 1).year).toBe(2025);
    });

    it('clamps the day when stepping into a shorter month', () => {
        expect(stepPart('month', parts({ month: 3, day: 31, year: 2023 }), -1)).toEqual(
            parts({ month: 2, day: 28, year: 2023 }),
        );
    });
});

describe('applyDigit', () => {
    it.each([
        ['month', {}, '', '1', { month: 1 }, '1', false],
        ['month', {}, '1', '2', { month: 12 }, '', true],
        ['month', {}, '', '4', { month: 4 }, '4', true],
        ['month', {}, '1', '5', { month: 5 }, '5', true],
        ['month', {}, '', '0', { month: 1 }, '0', false],
        ['month', {}, '12', '3', { month: 3 }, '3', true],
        ['year', {}, '20', '2', { year: 202 }, '202', false],
        ['year', {}, '202', '4', { year: 2024 }, '', true],
        ['day', { month: 2, year: 2023 }, '3', '1', { month: 2, year: 2023, day: 28 }, '', true],
        ['minute', {}, '', '0', { minute: 0 }, '0', false],
    ])('%s %j: buffer %j + %j', (part, partial, buffer, digit, expectedParts, expectedBuffer, advance) => {
        expect(applyDigit(part, parts(partial), buffer, digit)).toEqual({
            parts: parts(expectedParts),
            buffer: expectedBuffer,
            advance,
        });
    });
});

describe('composeDateTime', () => {
    const full = { month: 2, day: 28, year: 2023, hour: 12, minute: 5, meridiem: 'PM' };

    it.each([
        [{ month: 2, day: 29, year: 2024, hour: 12, minute: 0, meridiem: 'AM' }, '2024-02-29T00:00:00.000Z'],
        [full, '2023-02-28T12:05:00.000Z'],
        [{ ...full, hour: 1 }, '2023-02-28T13:05:00.000Z'],
    ])('composes %j', (input, expected) => {
        expect(composeDateTime(input).toISOString()).toBe(expected);
    });

    it.each([
        ['an invalid leap day', { ...full, day: 29 }],
        ['an empty part', { ...full, minute: null }],
        ['no meridiem', { ...full, meridiem: null }],
        ['a year before 1970', { ...full, year: 1969 }],
        ['month 13', { ...full, month: 13 }],
        ['hour 0', { ...full, hour: 0 }],
        ['minute 60', { ...full, minute: 60 }],
    ])('returns null for %s', (_, input) => {
        expect(composeDateTime(input)).toBeNull();
    });

    it('returns null for empty parts', () => {
        expect(composeDateTime(parts({}))).toBeNull();
    });
});

describe('decomposeDateTime', () => {
    it.each([
        [new Date(2024, 0, 5, 0, 7), { month: 1, day: 5, year: 2024, hour: 12, minute: 7, meridiem: 'AM' }],
        [new Date(2024, 0, 5, 12, 0), { month: 1, day: 5, year: 2024, hour: 12, minute: 0, meridiem: 'PM' }],
        [new Date(2024, 0, 5, 13, 0), { month: 1, day: 5, year: 2024, hour: 1, minute: 0, meridiem: 'PM' }],
    ])('decomposes %s', (date, expected) => {
        expect(decomposeDateTime(date)).toEqual(expected);
    });

    it('returns a fresh copy of the empty parts for null', () => {
        const result = decomposeDateTime(null);

        expect(result).toEqual(EMPTY_PARTS);
        expect(result).not.toBe(EMPTY_PARTS);
    });

    it('round-trips through composeDateTime', () => {
        const date = new Date(2024, 6, 4, 18, 45);

        expect(composeDateTime(decomposeDateTime(date)).getTime()).toBe(date.getTime());
    });
});

describe('TREND_RANGE_PRESETS', () => {
    it('lists the presets in order', () => {
        expect(TREND_RANGE_PRESETS.map((preset) => preset.value)).toEqual(['default', '7d', '1mo', '3mo', 'custom']);
    });

    it('gives every relative preset parseable bounds', () => {
        TREND_RANGE_PRESETS
            .filter((preset) => preset.value !== DEFAULT_RANGE && preset.value !== CUSTOM_RANGE)
            .forEach((preset) => expect(relativeRangeToBounds(preset.value)).not.toBeNull());
    });
});
