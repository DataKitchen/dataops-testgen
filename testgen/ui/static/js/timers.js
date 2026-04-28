/**
 * Timer helpers that integrate with AbortSignal so callers can tear down
 * long-lived timers through a single controller.
 */

/**
 * setInterval that clears itself when the given signal aborts.
 * Returns null if the signal is already aborted.
 * @param {Function} fn
 * @param {number} ms
 * @param {AbortSignal} [signal]
 * @returns {(number | null)}
 */
function setIntervalWithSignal(fn, ms, signal) {
    if (signal?.aborted) {
        return null;
    }
    const id = setInterval(fn, ms);
    signal?.addEventListener('abort', () => clearInterval(id), { once: true });
    return id;
}

export { setIntervalWithSignal };
