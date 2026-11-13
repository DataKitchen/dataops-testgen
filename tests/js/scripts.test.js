// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// scripts.js registers a window message listener and replaces window.testgen when imported, so each test
// imports a fresh copy and removes the listener that copy added.
let messageHandlers;

beforeEach(async () => {
    messageHandlers = [];
    const addEventListener = window.addEventListener.bind(window);
    vi.spyOn(window, 'addEventListener').mockImplementation((type, handler, options) => {
        if (type === 'message') {
            messageHandlers.push(handler);
        }
        addEventListener(type, handler, options);
    });
    vi.resetModules();
    await import('../../testgen/ui/static/js/scripts.js');
});

afterEach(() => {
    messageHandlers.forEach((handler) => window.removeEventListener('message', handler));
    vi.restoreAllMocks();
    delete window.isSecureContext;
    delete document.execCommand;
    document.body.innerHTML = '';
});

const post = (data) => window.dispatchEvent(new MessageEvent('message', { data }));

const stubSecureContext = (isSecure) => {
    Object.defineProperty(window, 'isSecureContext', { value: isSecure, configurable: true });
};

const stubClipboard = () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(navigator, 'clipboard', 'get').mockReturnValue({ writeText });
    return writeText;
};

it('exposes van on window', () => {
    expect(window.van.state).toBeTypeOf('function');
});

it('initializes window.testgen', () => {
    expect(window.testgen).toEqual({
        states: {},
        components: {},
        loadedStylesheets: {},
        portals: {},
        changeLocation: expect.any(Function),
    });
});

describe('TestgenCopyToClipboard', () => {
    it('copies through navigator.clipboard in a secure context', async () => {
        stubSecureContext(true);
        const writeText = stubClipboard();

        post({ type: 'TestgenCopyToClipboard', text: 'hi' });

        await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('hi'));
    });

    it('copies an empty string when no text is given', async () => {
        stubSecureContext(true);
        const writeText = stubClipboard();

        post({ type: 'TestgenCopyToClipboard' });

        await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith(''));
    });

    it('falls back to a hidden textarea and execCommand otherwise', async () => {
        stubSecureContext(false);
        const writeText = stubClipboard();
        let copiedText = null;
        document.execCommand = vi.fn(() => {
            copiedText = document.body.querySelector('textarea')?.value;
        });

        post({ type: 'TestgenCopyToClipboard', text: 'hi' });

        await vi.waitFor(() => expect(document.execCommand).toHaveBeenCalledWith('copy'));
        expect(copiedText).toBe('hi');
        expect(document.body.querySelector('textarea')).toBeNull();
        expect(writeText).not.toHaveBeenCalled();
    });

    it('removes the textarea even when execCommand throws', async () => {
        stubSecureContext(false);
        document.execCommand = vi.fn(() => {
            throw new Error('copy failed');
        });

        // Called directly rather than dispatched, so the rejection is awaited here instead of going unhandled.
        const result = messageHandlers[0]({ data: { type: 'TestgenCopyToClipboard', text: 'hi' } });

        await expect(result).rejects.toThrow('copy failed');
        expect(document.body.querySelector('textarea')).toBeNull();
    });
});

describe('TestgenLogout', () => {
    it('clears states and expires the named cookie', async () => {
        const setCookie = vi.spyOn(document, 'cookie', 'set');
        window.testgen.states = { a: 1 };

        post({ type: 'TestgenLogout', cookie: 'tg_auth' });

        await vi.waitFor(() => expect(setCookie).toHaveBeenCalledOnce());
        const cookie = setCookie.mock.calls[0][0];
        expect(window.testgen.states).toEqual({});
        expect(cookie).toMatch(/^tg_auth=-;expires=.+;path=\/$/);
        const expires = new Date(cookie.match(/expires=([^;]+)/)[1]);
        expect(expires.getTime()).toBeLessThan(Date.now());
    });
});

it('ignores unrelated messages', async () => {
    stubSecureContext(true);
    const writeText = stubClipboard();
    const setCookie = vi.spyOn(document, 'cookie', 'set');
    window.testgen.states = { a: 1 };

    post({ type: 'SomethingElse', text: 'hi', cookie: 'tg_auth' });
    await Promise.resolve();

    expect(writeText).not.toHaveBeenCalled();
    expect(setCookie).not.toHaveBeenCalled();
    expect(window.testgen.states).toEqual({ a: 1 });
});
