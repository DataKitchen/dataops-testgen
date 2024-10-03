import van from './van.min.js';

function enforceElementWidth(
    /** @type Element */element,
    /** @type number */width,
) {
    const observer = new ResizeObserver(() => {
        element.width = width;
    });

    observer.observe(element);
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

export { enforceElementWidth, loadStylesheet, wrapProps };
