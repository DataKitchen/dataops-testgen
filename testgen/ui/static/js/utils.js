import van from './van.min.js';

/**
 * @param {string} elementId
 * @param {((rect: DOMRect, element: HTMLElement) => void)} callback
 * @returns {ResizeObserver}
 */
function onFrameResized(elementId, callback) {
    const observer = new ResizeObserver(() => {
        const element = document.getElementById(elementId);
        if (element) {
            callback(element.getBoundingClientRect(), element);
        }
    });
    observer.observe(window.frameElement);

    return observer;
}

function loadStylesheet(
    /** @type string */key,
    /** @type CSSStyleSheet */stylesheet,
) {
    if (!window.testgen.loadedStylesheets[key]) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets[key] = true;
    }
}

// Replacement for van.val()
// https://github.com/vanjs-org/van/discussions/280
const stateProto = Object.getPrototypeOf(van.state());
/**
 * Get value from van.state
 * @template T
 * @param {(import('./van.min.js').VanState<T> | T)} prop
 * @returns {T}
 */
function getValue(prop) { // van state or static value
    const proto = Object.getPrototypeOf(prop ?? 0);
    if (proto === stateProto) {
        return prop.val;
    }
    if (proto === Function.prototype) {
        return prop();
    }
    return prop;
}

function isState(/** @type object */ value) {
    return Object.getPrototypeOf(value ?? 0) == stateProto;
}

function getRandomId() {
    return Math.random().toString(36).substring(2);
}

// https://stackoverflow.com/a/75988895
function debounce(
    /** @type function */ callback,
    /** @type number */ wait,
) {
    let timeoutId = null;
    return (...args) => {
        window.clearTimeout(timeoutId);
        timeoutId = window.setTimeout(() => callback(...args), wait);
    };
}

function getParents(/** @type HTMLElement*/ element) {
    const parents = [];

    let currentParent = element.parentElement; 
    do {
        if (currentParent !== null) {
            parents.push(currentParent);
            currentParent = currentParent.parentElement;
        }
    }
    while (currentParent !== null && currentParent.tagName !== 'iframe');

    return parents;
}

function friendlyPercent(/** @type number */ value) {
    if (Number.isNaN(value)) {
        return 0;
    }
    const rounded = Math.round(value);
    if (rounded === 0 && value > 0) {
        return '< 1';
    }
    if (rounded === 100 && value < 100) {
        return '> 99';
    }
    return rounded;
}

function isEqual(value, other) {
    if (typeof value !== 'object' && typeof other !== 'object') {
        return Object.is(value, other);
    }
    
    if (value === null && other === null) {
        return true;
    }

    if ((value === null || other === null) && (value !== null || other !== null)) {
        return false;
    }

    if (typeof value !== typeof other) {
        return false;
    }

    if (value === other) {
        return true;
    }

    if (Array.isArray(value) && Array.isArray(other)) {
        if (value.length !== other.length) {
            return false;
        }

        for (let i = 0; i < value.length; i++) {
            if (!isEqual(value[i], other[i])) {
                return false;
            }
        }

        return true;
    }

    if (Array.isArray(value) || Array.isArray(other)) {
        return false;
    }

    if (Object.keys(value).length !== Object.keys(other).length) {
        return false;
    }

    for (const [k, v] of Object.entries(value)) {
        if (!(k in other)) {
            return false;
        }

        if (!isEqual(v, other[k])) {
            return false;
        }
    }

    return true;
}

/**
 * Makes an element fill the viewport height from its current top position.
 * Sets `height: calc(100vh - <top>px - <bottomPadding>px)` and re-applies on resize.
 * @param {HTMLElement} element
 * @param {{ bottomPadding?: number }} [options]
 * @returns {() => void} Cleanup function that disconnects the observer
 */
function fillViewportHeight(element, { bottomPadding = 16 } = {}) {
    const apply = () => {
        const top = element.getBoundingClientRect().top;
        if (top > 0) {
            element.style.height = `calc(100vh - ${top + bottomPadding}px)`;
        }
    };
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(document.body);
    return () => observer.disconnect();
}

function afterMount(/** @ype Function */ callback) {
    const trigger = van.state(false);
    van.derive(() => trigger.val && callback());
    trigger.val = true;
}

function slugify(/** @type string */ str) {
    return str
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '');
}

function isDataURL(/** @type string */ url) {
    return url.startsWith('data:');
}

function checkIsRequired(validators) {
    let isRequired = validators.some(v => v.name === 'required');
    if (!isRequired) {
        isRequired = validators
            .filter((v) => v.args?.name === 'requiredIf')
            .some((v) => v.args?.condition?.())
    }
    return isRequired;
}

/**
 * 
 * @param {(string|number)} value 
 * @returns {number}
 */
function parseDate(value) {
    if (typeof value === 'string') {
        return Date.parse(value);
    } else if (typeof value === 'number') {
        return value * 1000;
    }

    return value;
}

/**
 * Create a component-scoped emit function bound to a specific V2 component's
 * setTriggerValue.  Use this instead of the global Streamlit singleton so that
 * events always route to the correct widget.
 *
 * @param {Function} setTriggerValue - The setTriggerValue provided by Streamlit to the V2 component
 * @returns {Function}
 */
function createEmitter(setTriggerValue) {
    return (event, data = {}) => {
        setTriggerValue(event, { ...data, _id: Math.random() });
    };
}

export { afterMount, createEmitter, debounce, fillViewportHeight, getRandomId, getValue, getParents, isEqual, isState, loadStylesheet, friendlyPercent, slugify, isDataURL, checkIsRequired, onFrameResized, parseDate };
