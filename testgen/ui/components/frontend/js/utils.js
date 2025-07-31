import van from './van.min.js';
import { Streamlit } from './streamlit.js';

function enforceElementWidth(
    /** @type Element */element,
    /** @type number */width,
) {
    const observer = new ResizeObserver(() => {
        element.width = width;
    });

    observer.observe(element);
}

function resizeFrameHeightToElement(/** @type string */elementId) {
    const observer = new ResizeObserver(() => {
        const element = document.getElementById(elementId);
        if (element) {
            const height = element.offsetHeight;
            if (height) {
                Streamlit.setFrameHeight(height);
            }
        }
    });
    observer.observe(window.frameElement);
}

function resizeFrameHeightOnDOMChange(/** @type string */elementId) {
    const observer = new MutationObserver(() => {
        const element = document.getElementById(elementId);
        if (element) {
            const height = element.offsetHeight;
            if (height) {
                Streamlit.setFrameHeight(height);
            }
        }
    });
    observer.observe(window.frameElement.contentDocument.body, {subtree: true, childList: true});
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

function emitEvent(
    /** @type string */event,
    /** @type object */data = {},
) {
    Streamlit.sendData({ event, ...data, _id: Math.random() }) // Identify the event so its handler is called once
}

// Replacement for van.val()
// https://github.com/vanjs-org/van/discussions/280
const stateProto = Object.getPrototypeOf(van.state());
/**
 * Get value from van.state
 * @template T
 * @param {T} prop
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

export { afterMount, debounce, emitEvent, enforceElementWidth, getRandomId, getValue, getParents, isEqual, isState, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange, friendlyPercent, slugify, isDataURL };
