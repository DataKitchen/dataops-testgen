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

function wrapProps(/** @type object */props) {
    for (const [key, value] of Object.entries(props)) {
        props[key] = van.state(value);
    }
    return props;
}

function emitEvent(
    /** @type string */event,
    /** @type object */data = {},
) {
    Streamlit.sendData({ event, ...data, _id: Math.random() }) // Identify the event so its handler is called once
}

export { emitEvent, enforceElementWidth, loadStylesheet, resizeFrameHeightToElement, wrapProps };
