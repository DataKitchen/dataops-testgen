/**
 * @typedef Properties
 * @type {object}
 * @property {(string|null)} icon
 * @property {(string|null)} class
 * @property {(Function|null)} onclick
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';

const { button, i, span } = van.tags;

const Button = (/** @type Properties */ props, /** @type string */ text) => {
    Streamlit.setFrameHeight();

    if (!window.testgen.loadedStylesheets.button) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets.button = true;
    }

    return button(
        {
            class: `tg-button ${props.icon ? 'tg-icon-button' : ''} ${props.class ?? ''}`,
            onclick: props.onclick,
        },
        props.icon ? i({class: 'material-symbols-rounded'}, props.icon) : undefined,
        span(text),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
button.tg-button {
    position: relative;
    overflow: hidden;

    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;

    outline: 0;
    border: unset;
    background: transparent;
    border-radius: 4px;
    padding: 8px 16px;

    color: var(--primary-text-color);
    cursor: pointer;

    font-size: 14px;

    transition: background 400ms;
}

button.tg-button:hover {
    background: rgba(0, 0, 0, 0.04);
}

button.tg-button.tg-icon-button > i {
    font-size: 18px;
    margin-right: 8px;
}
`);

export { Button };
