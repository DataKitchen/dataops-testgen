// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    PII_REDACTED,
    capitalize,
    caseInsensitiveIncludes,
    caseInsensitiveSort,
    formatDuration,
    formatDurationSeconds,
    formatNumber,
    formatTimestamp,
    humanReadableDuration,
    humanReadableSize,
    viewPortUnitsToPixels,
} from '../../testgen/ui/static/js/display_utils.js';

describe('formatTimestamp', () => {
    it('reads a 10-digit number as epoch seconds and shows the year on request', () => {
        expect(formatTimestamp(1700000000, true)).toBe('Nov 14, 2023 at 10:13 PM');
    });

    it('reads a 13-digit number as epoch milliseconds', () => {
        expect(formatTimestamp(1700000000000)).toBe('Nov 14, 10:13 PM');
    });

    it('formats a Date', () => {
        expect(formatTimestamp(new Date('2024-03-05T12:30:00Z'))).toBe('Mar 5, 12:30 PM');
    });

    it('shows midnight as 12 AM and noon as 12 PM', () => {
        expect(formatTimestamp(Date.UTC(2024, 0, 1))).toBe('Jan 1, 12:00 AM');
        expect(formatTimestamp(Date.UTC(2024, 0, 1, 12))).toBe('Jan 1, 12:00 PM');
    });

    it.each([null, undefined, '', 'garbage'])('renders %j as --', (value) => {
        expect(formatTimestamp(value)).toBe('--');
    });

    it('passes the PII placeholder through', () => {
        expect(formatTimestamp(PII_REDACTED)).toBe(PII_REDACTED);
    });

    it('renders the epoch itself as -- (pinned)', () => {
        expect(formatTimestamp(0)).toBe('--');
    });

    it('renders an ISO string as -- (pinned)', () => {
        expect(formatTimestamp('2024-03-05T00:05:00Z')).toBe('--');
    });

    it('reads a 9-digit seconds value as milliseconds (pinned)', () => {
        expect(formatTimestamp(999999999)).toBe('Jan 12, 1:46 PM');
    });
});

describe('formatDuration', () => {
    it('treats numbers as epoch seconds', () => {
        expect(formatDuration(1000, 1000 + 90061)).toBe('1d 1h 1m 1s');
    });

    it('shows a sub-second span as < 1s', () => {
        expect(formatDuration('2024-01-01T00:00:00Z', '2024-01-01T00:00:00.500Z')).toBe('< 1s');
    });

    it.each([[null, 5], [5, null]])('renders a missing bound (%j, %j) as --', (start, end) => {
        expect(formatDuration(start, end)).toBe('--');
    });

    it('renders an end before the start as --', () => {
        expect(formatDuration(10, 5)).toBe('--');
    });
});

describe('formatDurationSeconds', () => {
    it.each([
        [0, '< 1s'],
        [59, '59s'],
        [3600, '1h'],
        [90061, '1d 1h 1m 1s'],
    ])('formats %s as %j', (seconds, expected) => {
        expect(formatDurationSeconds(seconds)).toBe(expected);
    });

    it.each([-1, null, undefined])('renders %j as --', (seconds) => {
        expect(formatDurationSeconds(seconds)).toBe('--');
    });

    it('leaves a double space where a middle unit is zero (pinned)', () => {
        expect(formatDurationSeconds(86461)).toBe('1d  1m 1s');
    });
});

describe('humanReadableDuration', () => {
    it.each([
        ['< 1s', 'Less than 1 second'],
        ['1d 2h 1m 1s', '1 day 2 hours 1 minute 1 second'],
        ['2d 3h', '2 days 3 hours'],
    ])('spells out %j', (duration, expected) => {
        expect(humanReadableDuration(duration)).toBe(expected);
    });

    it.each([
        ['2h 30m', '2 hours'],
        ['1m', '1 minute'],
    ])('keeps only the largest unit of %j when rounding', (duration, expected) => {
        expect(humanReadableDuration(duration, true)).toBe(expected);
    });

    it('throws on a duration with a zero middle unit (pinned)', () => {
        expect(() => humanReadableDuration(formatDurationSeconds(3605))).toThrow(TypeError);
    });

    it('rounds a duration with a zero middle unit without throwing', () => {
        expect(humanReadableDuration(formatDurationSeconds(3605), true)).toBe('1 hour');
    });
});

describe('formatNumber', () => {
    it.each([
        [1234567.891, '1,234,567.891'],
        [1.23456, '1.235'],
        ['42.5', '42.5'],
        [0, '0'],
    ])('formats %j as %j', (value, expected) => {
        expect(formatNumber(value)).toBe(expected);
    });

    it('rounds to the requested decimals', () => {
        expect(formatNumber(1.23456, 1)).toBe('1.2');
    });

    it.each(['abc', null, undefined, NaN, {}])('renders %j as --', (value) => {
        expect(formatNumber(value)).toBe('--');
    });

    it('passes the PII placeholder through', () => {
        expect(formatNumber(PII_REDACTED)).toBe(PII_REDACTED);
    });

    it('renders an empty string as 0 (pinned)', () => {
        expect(formatNumber('')).toBe('0');
    });

    it('renders a tiny negative as -0 (pinned)', () => {
        expect(formatNumber(-0.0004)).toBe('-0');
    });
});

describe('capitalize', () => {
    it.each([
        ['hello WORLD', 'Hello World'],
        ['', ''],
        ['a  b', 'A  B'],
    ])('capitalizes %j as %j', (text, expected) => {
        expect(capitalize(text)).toBe(expected);
    });
});

describe('humanReadableSize', () => {
    it.each([
        [0, '0B'],
        [1025, '1KB'],
        [1536, '2KB'],
        [1048577, '1MB'],
        [5 * 1048576, '5MB'],
    ])('formats %s bytes as %j', (bytes, expected) => {
        expect(humanReadableSize(bytes)).toBe(expected);
    });

    it.each([
        [1024, '1024B'],
        [1048576, '1024KB'],
    ])('keeps exactly %s bytes in the smaller unit (pinned)', (bytes, expected) => {
        expect(humanReadableSize(bytes)).toBe(expected);
    });
});

describe('caseInsensitiveIncludes', () => {
    it.each([
        ['Hello', 'ELL', true],
        ['Hello', 'xyz', false],
        ['Hello', '', true],
        ['', '', true],
        [null, null, true],
        [null, 'x', false],
    ])('(%j, %j) is %s', (value, search, expected) => {
        expect(caseInsensitiveIncludes(value, search)).toBe(expected);
    });
});

describe('caseInsensitiveSort', () => {
    it('sorts ignoring case, lowercase first within a letter', () => {
        expect(['b', 'A', 'a', 'B'].sort(caseInsensitiveSort)).toEqual(['a', 'A', 'b', 'B']);
    });
});

describe('viewPortUnitsToPixels', () => {
    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('converts viewport height units', () => {
        vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(800);

        expect(viewPortUnitsToPixels(50, 'height')).toBe(400);
    });

    it('converts viewport width units', () => {
        vi.spyOn(window, 'innerWidth', 'get').mockReturnValue(1200);

        expect(viewPortUnitsToPixels(25, 'width')).toBe(300);
    });

    it.each(['50', null])('returns 0 for the non-number %j', (value) => {
        expect(viewPortUnitsToPixels(value, 'height')).toBe(0);
    });

    it('falls back to the top window when the current one has no size', () => {
        vi.spyOn(window, 'innerWidth', 'get').mockReturnValue(0);
        vi.spyOn(window, 'top', 'get').mockReturnValue({ innerWidth: 1000 });

        expect(viewPortUnitsToPixels(10, 'width')).toBe(100);
    });
});
