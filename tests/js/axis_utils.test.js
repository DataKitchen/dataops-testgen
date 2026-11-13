import { describe, expect, it } from 'vitest';
import {
    formatSmartTimeTicks,
    getAdaptiveTimeTicks,
    getAdaptiveTimeTicksV2,
    niceBounds,
    niceTicks,
    scale,
    screenToSvgCoordinates,
} from '../../testgen/ui/static/js/axis_utils.js';

const HOUR = 3600000;
const DAY = 86400000;
const t0 = Date.UTC(2024, 0, 1);
const iso = (dates) => dates.map((date) => date.toISOString());

describe('niceBounds', () => {
    it.each([
        [0, 100, { min: 0, max: 100, step: 50, range: 100 }],
        [5, 5, { min: 4.5, max: 5.5, step: 0.5, range: 1 }],
        [0.1, 0.9, { min: 0, max: 1, step: 0.5, range: 1 }],
        [-37, 512, { min: -500, max: 1000, step: 500, range: 1500 }],
    ])('rounds [%s, %s] out to nice bounds', (start, end, expected) => {
        const bounds = niceBounds(start, end);

        expect(bounds).toEqual(expected);
        expect(bounds.min).toBeLessThanOrEqual(start);
        expect(bounds.max).toBeGreaterThanOrEqual(end);
    });
});

describe('niceTicks', () => {
    it.each([
        [0, 100, [0, 50, 100]],
        [0.1, 0.9, [0, 0.5, 1]],
    ])('ticks [%s, %s] as %j', (start, end, expected) => {
        expect(niceTicks(start, end)).toEqual(expected);
    });

    it('keeps fractional steps close to their nominal values', () => {
        const ticks = niceTicks(0, 1, 11);

        expect(ticks).toHaveLength(11);
        ticks.forEach((tick, i) => expect(tick).toBeCloseTo(i / 10));
    });

    it('drops the top tick when the accumulated step overshoots max (pinned)', () => {
        expect(niceBounds(0, 0.101, 8).max).toBe(0.12);
        expect(niceTicks(0, 0.101, 8)).toEqual([0, 0.02, 0.04, 0.06, 0.08, 0.1]);
    });
});

describe('scale', () => {
    it('maps a value between ranges', () => {
        expect(scale(5, { old: { min: 0, max: 10 }, new: { min: 0, max: 100 } })).toBe(50);
    });

    it('maps onto a reversed range', () => {
        expect(scale(15, { old: { min: 0, max: 10 }, new: { min: 100, max: 0 } })).toBe(-50);
    });

    it('returns 0 for a zero-width source range', () => {
        expect(scale(5, { old: { min: 3, max: 3 }, new: { min: 0, max: 100 } })).toBe(0);
    });

    it('returns the given zero for a zero-width source range', () => {
        expect(scale(5, { old: { min: 3, max: 3 }, new: { min: 0, max: 100 } }, 42)).toBe(42);
    });
});

describe('screenToSvgCoordinates', () => {
    it("maps the event's client point through the inverse screen matrix", () => {
        const svg = {
            createSVGPoint() {
                const point = {
                    x: 0,
                    y: 0,
                    matrixTransform: (matrix) => ({ x: point.x - matrix.e, y: point.y - matrix.f }),
                };
                return point;
            },
            getScreenCTM: () => ({ inverse: () => ({ e: 10, f: 20 }) }),
        };

        expect(screenToSvgCoordinates(svg, { clientX: 50, clientY: 70 })).toEqual({ x: 40, y: 50 });
    });
});

describe('getAdaptiveTimeTicks', () => {
    it.each([[[]], [null]])('returns no ticks for %j', (dates) => {
        expect(getAdaptiveTimeTicks(dates, 2, 5)).toEqual([]);
    });

    it('ticks a one-day span daily', () => {
        expect(iso(getAdaptiveTimeTicks([t0, t0 + DAY], 3, 8))).toEqual([
            '2024-01-01T00:00:00.000Z',
            '2024-01-02T00:00:00.000Z',
            '2024-01-03T00:00:00.000Z',
        ]);
    });

    it('ticks a 30-day span weekly', () => {
        expect(iso(getAdaptiveTimeTicks([t0, t0 + 30 * DAY], 3, 8))).toEqual([
            '2023-12-28T00:00:00.000Z',
            '2024-01-04T00:00:00.000Z',
            '2024-01-11T00:00:00.000Z',
            '2024-01-18T00:00:00.000Z',
            '2024-01-25T00:00:00.000Z',
            '2024-02-01T00:00:00.000Z',
        ]);
    });

    it('ticks a two-year span yearly', () => {
        expect(iso(getAdaptiveTimeTicks([t0, Date.UTC(2026, 0, 1)], 2, 5))).toEqual([
            '2024-01-01T00:00:00.000Z',
            '2025-01-01T00:00:00.000Z',
            '2026-01-01T00:00:00.000Z',
        ]);
    });

    it('treats Date input like timestamps', () => {
        const timestamps = [t0, t0 + 6 * HOUR];

        expect(getAdaptiveTimeTicks(timestamps.map((t) => new Date(t)), 2, 8))
            .toEqual(getAdaptiveTimeTicks(timestamps, 2, 8));
    });

    it('ticks a zero-width span weekly around the instant (pinned)', () => {
        expect(iso(getAdaptiveTimeTicks([t0, t0], 2, 5))).toEqual([
            '2023-12-28T00:00:00.000Z',
            '2024-01-04T00:00:00.000Z',
        ]);
    });
});

describe('getAdaptiveTimeTicksV2', () => {
    it('returns no ticks for no dates', () => {
        expect(getAdaptiveTimeTicksV2([], 800, 100)).toEqual([]);
    });

    it('ticks one day every 4 hours when 8 ticks fit', () => {
        expect(iso(getAdaptiveTimeTicksV2([t0, t0 + DAY], 800, 100))).toEqual([
            '2024-01-01T00:00:00.000Z',
            '2024-01-01T04:00:00.000Z',
            '2024-01-01T08:00:00.000Z',
            '2024-01-01T12:00:00.000Z',
            '2024-01-01T16:00:00.000Z',
            '2024-01-01T20:00:00.000Z',
            '2024-01-02T00:00:00.000Z',
        ]);
    });

    it('ticks one day every 8 hours when 4 ticks fit', () => {
        expect(iso(getAdaptiveTimeTicksV2([t0, t0 + DAY], 400, 100))).toEqual([
            '2024-01-01T00:00:00.000Z',
            '2024-01-01T08:00:00.000Z',
            '2024-01-01T16:00:00.000Z',
            '2024-01-02T00:00:00.000Z',
        ]);
    });

    it('ticks six months on the first of each month', () => {
        expect(iso(getAdaptiveTimeTicksV2([t0, Date.UTC(2024, 6, 1)], 800, 100))).toEqual([
            '2024-01-01T00:00:00.000Z',
            '2024-02-01T00:00:00.000Z',
            '2024-03-01T00:00:00.000Z',
            '2024-04-01T00:00:00.000Z',
            '2024-05-01T00:00:00.000Z',
            '2024-06-01T00:00:00.000Z',
            '2024-07-01T00:00:00.000Z',
        ]);
    });

    it('ticks a ten-minute span with a nice millisecond step', () => {
        const ticks = getAdaptiveTimeTicksV2([t0 + 10 * 60000, t0 + 20 * 60000], 600, 100);

        expect(iso(ticks)[0]).toBe('2024-01-01T00:10:00.000Z');
        expect(ticks).toHaveLength(7);
        expect(ticks[1] - ticks[0]).toBe(100000);
    });

    it.each([
        [[t0, t0 + DAY], 800],
        [[t0, Date.UTC(2024, 6, 1)], 800],
        [[t0 + 10 * 60000, t0 + 20 * 60000], 600],
    ])('keeps every tick within the data range %#', (dates, width) => {
        getAdaptiveTimeTicksV2(dates, width, 100).forEach((tick) => {
            expect(tick.getTime()).toBeGreaterThanOrEqual(dates[0]);
            expect(tick.getTime()).toBeLessThanOrEqual(dates[1]);
        });
    });

    it('never picks the year step for a multi-year span (pinned)', () => {
        expect(iso(getAdaptiveTimeTicksV2([t0, Date.UTC(2029, 0, 1)], 600, 100))).toEqual([
            '2025-06-15T15:06:40.000Z',
            '2027-01-15T08:00:00.000Z',
            '2028-08-16T00:53:20.000Z',
        ]);
    });
});

describe('formatSmartTimeTicks', () => {
    it.each([[[]], [null]])('returns no labels for %j', (ticks) => {
        expect(formatSmartTimeTicks(ticks)).toEqual([]);
    });

    it('labels a single tick with its date and year', () => {
        expect(formatSmartTimeTicks([new Date(t0)])).toEqual([['Jan 1', '2024']]);
    });

    it('shows times, and the date only where it changes, for sub-day steps', () => {
        const ticks = [0, 6, 12, 24].map((hours) => new Date(t0 + hours * HOUR));

        expect(formatSmartTimeTicks(ticks)).toEqual([
            ['00:00', 'Jan 1 2024'],
            '06:00',
            '12:00',
            ['00:00', 'Jan 2'],
        ]);
    });

    it('shows the year only where it changes for daily steps', () => {
        const ticks = [Date.UTC(2023, 11, 31), t0, t0 + DAY].map((t) => new Date(t));

        expect(formatSmartTimeTicks(ticks)).toEqual([
            ['Dec 31', '2023'],
            ['Jan 1', '2024'],
            'Jan 2',
        ]);
    });
});
