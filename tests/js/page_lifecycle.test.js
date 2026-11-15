import { describe, expect, it } from 'vitest';
import { enterPage, exitPage, getPageSignal } from '../../testgen/ui/static/js/page_lifecycle.js';

// The module's registry outlives each test, so every test uses its own page keys.
const newKey = () => `page-${crypto.randomUUID()}`;

describe('page lifecycle', () => {
    it('getPageSignal returns null for an unknown page', () => {
        expect(getPageSignal(newKey())).toBeNull();
    });

    it('enterPage returns a live signal that getPageSignal also returns', () => {
        const key = newKey();

        const signal = enterPage(key);

        expect(signal.aborted).toBe(false);
        expect(getPageSignal(key)).toBe(signal);
    });

    it('exitPage aborts the signal and unregisters it', () => {
        const key = newKey();
        const signal = enterPage(key);

        exitPage(key);

        expect(signal.aborted).toBe(true);
        expect(getPageSignal(key)).toBeNull();
    });

    it('exitPage on an unknown page is a no-op', () => {
        expect(() => exitPage(newKey())).not.toThrow();
    });

    it('re-entering a page aborts the previous signal', () => {
        const key = newKey();
        const first = enterPage(key);

        const second = enterPage(key);

        expect(first.aborted).toBe(true);
        expect(second.aborted).toBe(false);
        expect(getPageSignal(key)).toBe(second);
    });

    it('pages are independent', () => {
        const keyA = newKey();
        const keyB = newKey();
        enterPage(keyA);
        const signalB = enterPage(keyB);

        exitPage(keyA);

        expect(signalB.aborted).toBe(false);
        expect(getPageSignal(keyB)).toBe(signalB);
    });
});
