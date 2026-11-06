import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setIntervalWithSignal } from '../../testgen/ui/static/js/timers.js';

describe('setIntervalWithSignal', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('runs fn every ms without a signal', () => {
        const fn = vi.fn();
        const id = setIntervalWithSignal(fn, 1000);

        vi.advanceTimersByTime(3000);

        expect(fn).toHaveBeenCalledTimes(3);
        expect(id).not.toBeNull();
        clearInterval(id);
    });

    it('stops when the signal aborts', () => {
        const fn = vi.fn();
        const controller = new AbortController();
        setIntervalWithSignal(fn, 1000, controller.signal);

        vi.advanceTimersByTime(2000);
        controller.abort();
        vi.advanceTimersByTime(5000);

        expect(fn).toHaveBeenCalledTimes(2);
        expect(vi.getTimerCount()).toBe(0);
    });

    it('returns null and never schedules when the signal is already aborted', () => {
        const fn = vi.fn();
        const controller = new AbortController();
        controller.abort();

        const id = setIntervalWithSignal(fn, 1000, controller.signal);
        vi.advanceTimersByTime(5000);

        expect(id).toBeNull();
        expect(vi.getTimerCount()).toBe(0);
        expect(fn).not.toHaveBeenCalled();
    });
});
