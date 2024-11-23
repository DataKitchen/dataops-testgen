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
        const height = document.getElementById(elementId).offsetHeight;
        if (height) {
            Streamlit.setFrameHeight(height);
        }
    });
    observer.observe(window.frameElement);
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
function getValue(/** @type object */ prop) { // van state or static value
    const proto = Object.getPrototypeOf(prop ?? 0);
    if (proto === stateProto) {
        return prop.val;
    }
    if (proto === Function.prototype) {
        return prop();
    }
    return prop;
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
    const rounded = Math.round(value);
    if (rounded === 0 && value > 0) {
        return '< 0';
    }
    if (rounded === 100 && value < 100) {
        return '> 99';
    }
    return rounded;
}

export { debounce, emitEvent, enforceElementWidth, getRandomId, getValue, getParents, loadStylesheet, resizeFrameHeightToElement, friendlyPercent };
