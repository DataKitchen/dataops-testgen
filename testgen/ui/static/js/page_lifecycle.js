/**
 * Per-page AbortController registry. Pages call enterPage() on mount to obtain
 * an AbortSignal, then exitPage() on teardown to abort any side effects tied
 * to that signal (intervals, fetches, event listeners).
 */

const controllers = new Map();

/**
 * Begin a page's lifetime. If a controller is still registered for this key
 * (previous teardown never ran), abort it before creating a new one.
 * @param {string} pageKey
 * @returns {AbortSignal}
 */
function enterPage(pageKey) {
    controllers.get(pageKey)?.abort();
    const controller = new AbortController();
    controllers.set(pageKey, controller);
    return controller.signal;
}

/**
 * End a page's lifetime: abort all listeners attached to the signal and
 * drop the controller. Safe to call if no controller is registered.
 * @param {string} pageKey
 */
function exitPage(pageKey) {
    const controller = controllers.get(pageKey);
    if (!controller) {
        return;
    }
    controller.abort();
    controllers.delete(pageKey);
}

/**
 * Read the current signal for a page, or null if the page isn't active.
 * Lets descendant components register cleanup without prop drilling.
 * @param {string} pageKey
 * @returns {AbortSignal | null}
 */
function getPageSignal(pageKey) {
    return controllers.get(pageKey)?.signal ?? null;
}

export { enterPage, exitPage, getPageSignal };
