// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import van from '../../testgen/ui/static/js/van.min.js';
import { maxLength, required, requiredIf } from '../../testgen/ui/static/js/form_validators.js';
import {
    afterMount,
    checkIsRequired,
    createEmitter,
    debounce,
    fillViewportHeight,
    friendlyPercent,
    getParents,
    getRandomId,
    getValue,
    isDataURL,
    isEqual,
    isHttpUrl,
    isState,
    loadStylesheet,
    onFrameResized,
    parseDate,
    slugify,
} from '../../testgen/ui/static/js/utils.js';

afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    document.body.innerHTML = '';
});

describe('isEqual', () => {
    it.each([
        [1, 1, true],
        [1, '1', false],
        ['a', 'a', true],
        [NaN, NaN, true],
        [null, null, true],
        [null, {}, false],
        [{}, null, false],
        [{}, [], false],
        [[1, [2, 3]], [1, [2, 3]], true],
        [[1, [2, 3]], [1, [2, 4]], false],
        [[1, 2], [1, 2, 3], false],
        [{ a: { b: [1] } }, { a: { b: [1] } }, true],
        [{ a: { b: [1] } }, { a: { b: [2] } }, false],
        [{ a: 1 }, { a: 1, b: 2 }, false],
        [{ a: 1 }, { b: 1 }, false],
        [{ a: undefined }, { b: 1 }, false],
    ])('isEqual(%j, %j) is %s', (value, other, expected) => {
        expect(isEqual(value, other)).toBe(expected);
    });

    it('treats 0 and -0 as different (pinned)', () => {
        expect(isEqual(0, -0)).toBe(false);
    });
});

describe('slugify', () => {
    it.each([
        ['Hello World!', 'hello-world'],
        ['--a__b--', 'a-b'],
        ['', ''],
        ['Ünïcode', 'n-code'],
    ])('slugifies %j as %j', (text, expected) => {
        expect(slugify(text)).toBe(expected);
    });

    it('throws on null', () => {
        expect(() => slugify(null)).toThrow(TypeError);
    });
});

describe('friendlyPercent', () => {
    it.each([
        [NaN, 0],
        [0, 0],
        [0.4, '< 1'],
        [50.5, 51],
        [99.6, '> 99'],
        [100, 100],
        [null, 0],
    ])('shows %j as %j', (value, expected) => {
        expect(friendlyPercent(value)).toBe(expected);
    });
});

describe('isDataURL', () => {
    it('recognizes a data URL', () => {
        expect(isDataURL('data:image/png;base64,x')).toBe(true);
    });

    it('rejects an http URL', () => {
        expect(isDataURL('https://x')).toBe(false);
    });

    it('throws on null', () => {
        expect(() => isDataURL(null)).toThrow(TypeError);
    });
});

describe('isHttpUrl', () => {
    it.each(['http://x', 'HTTPS://x', '  https://x'])('allows %j', (value) => {
        expect(isHttpUrl(value)).toBe(true);
    });

    it.each(['javascript:alert(1)', 'data:text/html,x', 'ftp://x', '//x', '', null, 42])('blocks %j', (value) => {
        expect(isHttpUrl(value)).toBe(false);
    });
});

describe('parseDate', () => {
    it('parses an ISO string to epoch milliseconds', () => {
        expect(parseDate('2024-01-01T00:00:00Z')).toBe(1704067200000);
    });

    it('reads a number as epoch seconds', () => {
        expect(parseDate(1704067200)).toBe(1704067200000);
    });

    it('returns NaN for an unparseable string', () => {
        expect(parseDate('garbage')).toBeNaN();
    });

    it.each([null, undefined])('returns %j unchanged', (value) => {
        expect(parseDate(value)).toBe(value);
    });

    it('returns a Date unchanged', () => {
        const date = new Date();

        expect(parseDate(date)).toBe(date);
    });
});

describe('checkIsRequired', () => {
    it.each([
        ['required', [required], true],
        ['no validators', [], false],
        ['requiredIf with a true condition', [requiredIf(() => true)], true],
        ['requiredIf with a false condition', [requiredIf(() => false)], false],
        ['an unrelated validator', [maxLength(3)], false],
    ])('%s → %s', (_, validators, expected) => {
        expect(checkIsRequired(validators)).toBe(expected);
    });
});

describe('getRandomId', () => {
    it('returns a non-empty base-36 string', () => {
        expect(getRandomId()).toMatch(/^[a-z0-9]+$/);
    });

    it('returns a different id on each call', () => {
        expect(getRandomId()).not.toBe(getRandomId());
    });
});

describe('getValue and isState', () => {
    it('unwraps a van state', () => {
        const state = van.state(3);

        expect(getValue(state)).toBe(3);
        expect(isState(state)).toBe(true);
    });

    it('calls a function', () => {
        const fn = () => 4;

        expect(getValue(fn)).toBe(4);
        expect(isState(fn)).toBe(false);
    });

    it.each([5, 'a', null, undefined])('returns the static value %j', (value) => {
        expect(getValue(value)).toBe(value);
        expect(isState(value)).toBe(false);
    });

    it('returns a plain object unchanged', () => {
        const value = {};

        expect(getValue(value)).toBe(value);
        expect(isState(value)).toBe(false);
    });
});

describe('createEmitter', () => {
    it('forwards the event and data with a fresh _id', () => {
        const setTriggerValue = vi.fn();

        createEmitter(setTriggerValue)('evt', { a: 1 });

        expect(setTriggerValue).toHaveBeenCalledWith('evt', { a: 1, _id: expect.any(Number) });
    });

    it('defaults the data to an empty payload', () => {
        const setTriggerValue = vi.fn();

        createEmitter(setTriggerValue)('evt');

        expect(setTriggerValue).toHaveBeenCalledWith('evt', { _id: expect.any(Number) });
    });

    it("does not mutate the caller's data", () => {
        const data = { a: 1 };

        createEmitter(vi.fn())('evt', data);

        expect(data).toEqual({ a: 1 });
    });
});

describe('debounce', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    it('collapses calls within the wait into one call with the last arguments', () => {
        const callback = vi.fn();
        const debounced = debounce(callback, 100);

        debounced(1);
        debounced(2);
        debounced(3);
        vi.advanceTimersByTime(100);

        expect(callback).toHaveBeenCalledTimes(1);
        expect(callback).toHaveBeenCalledWith(3);
    });

    it('calls again once the wait has passed between calls', () => {
        const callback = vi.fn();
        const debounced = debounce(callback, 100);

        debounced(1);
        vi.advanceTimersByTime(150);
        debounced(2);
        vi.advanceTimersByTime(150);

        expect(callback.mock.calls).toEqual([[1], [2]]);
    });
});

describe('afterMount', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    it('runs the callback once, after the current task', () => {
        const callback = vi.fn();

        afterMount(callback);
        expect(callback).not.toHaveBeenCalled();

        vi.runAllTimers();
        vi.runAllTimers();
        expect(callback).toHaveBeenCalledTimes(1);
    });
});

describe('loadStylesheet', () => {
    it('adopts each key once', () => {
        // adoptedStyleSheets outlives the per-test window.testgen reset, so assert the delta.
        const before = document.adoptedStyleSheets.length;

        loadStylesheet('a', new CSSStyleSheet());
        loadStylesheet('a', new CSSStyleSheet());

        expect(document.adoptedStyleSheets.length).toBe(before + 1);
        expect(window.testgen.loadedStylesheets.a).toBe(true);
    });

    it('adopts a different key separately', () => {
        const before = document.adoptedStyleSheets.length;

        loadStylesheet('a', new CSSStyleSheet());
        loadStylesheet('b', new CSSStyleSheet());

        expect(document.adoptedStyleSheets.length).toBe(before + 2);
    });
});

describe('getParents', () => {
    it('lists ancestors from nearest to the document root', () => {
        const div = document.createElement('div');
        const section = document.createElement('section');
        const span = document.createElement('span');
        section.append(span);
        div.append(section);
        document.body.append(div);

        expect(getParents(span)).toEqual([section, div, document.body, document.documentElement]);
    });

    it('returns no parents for a detached element', () => {
        expect(getParents(document.createElement('span'))).toEqual([]);
    });

    it('does not stop at an iframe ancestor (pinned)', () => {
        // Detached, because happy-dom tries to load an attached iframe.
        const div = document.createElement('div');
        const iframe = document.createElement('iframe');
        const span = document.createElement('span');
        iframe.append(span);
        div.append(iframe);

        expect(getParents(span)).toEqual([iframe, div]);
    });
});

describe('fillViewportHeight', () => {
    const elementAt = (top) => {
        const element = document.createElement('div');
        vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({ top });
        return element;
    };

    it('fills the viewport below the element with the default padding', () => {
        const element = elementAt(100);

        fillViewportHeight(element);

        expect(element.style.height).toBe('calc(100vh - 116px)');
    });

    it('applies a custom bottom padding', () => {
        const element = elementAt(100);

        fillViewportHeight(element, { bottomPadding: 0 });

        expect(element.style.height).toBe('calc(100vh - 100px)');
    });

    it('leaves the height alone when the element is at the top', () => {
        const element = elementAt(0);

        fillViewportHeight(element);

        expect(element.style.height).toBe('');
    });

    it('returns a cleanup that disconnects the observer', () => {
        const disconnect = vi.spyOn(ResizeObserver.prototype, 'disconnect');

        fillViewportHeight(elementAt(100))();

        expect(disconnect).toHaveBeenCalledOnce();
    });
});

describe('onFrameResized', () => {
    let observers;

    beforeEach(() => {
        observers = [];
        vi.stubGlobal('ResizeObserver', class {
            constructor(callback) {
                this.callback = callback;
                this.observe = vi.fn();
                observers.push(this);
            }
        });
        Object.defineProperty(window, 'frameElement', {
            value: document.createElement('iframe'),
            configurable: true,
        });
    });

    afterEach(() => {
        delete window.frameElement;
    });

    it('observes the frame element and returns the observer', () => {
        const observer = onFrameResized('target', vi.fn());

        expect(observer).toBe(observers[0]);
        expect(observer.observe).toHaveBeenCalledWith(window.frameElement);
    });

    it("reports the element's rect and the element on resize", () => {
        const element = document.createElement('div');
        element.id = 'target';
        document.body.append(element);
        const rect = { top: 1, height: 2 };
        vi.spyOn(element, 'getBoundingClientRect').mockReturnValue(rect);
        const callback = vi.fn();

        onFrameResized('target', callback).callback();

        expect(callback).toHaveBeenCalledWith(rect, element);
    });

    it('does nothing when the element is absent', () => {
        const callback = vi.fn();

        onFrameResized('missing', callback).callback();

        expect(callback).not.toHaveBeenCalled();
    });
});
