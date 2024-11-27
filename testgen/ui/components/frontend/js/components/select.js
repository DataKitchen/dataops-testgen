/**
 * @typedef Option
 * @type {object}
 * @property {string} label
 * @property {string} value
 * @property {boolean} selected
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {Array.<Option>} options
 * @property {Function|null} onChange
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { getRandomId, getValue, loadStylesheet } from '../utils.js';

const { div, label, option, select } = van.tags;

const Select = (/** @type {Properties} */ props) => {
    loadStylesheet('select', stylesheet);
    Streamlit.setFrameHeight();

    const domId = getRandomId();
    const changeHandler = props.onChange || post;
    return div(
        {class: 'tg-select'},
        label({for: domId, class: 'tg-select--label'}, props.label),
        () => {
            const options = getValue(props.options) || [];
            return select(
                {id: domId, class: 'tg-select--field', onchange: changeHandler},
                options.map(op => option({class: 'tg-select--field--option', value: op.value, selected: op.selected}, op.label)),
            );
        },
    );
};

function post(/** @type string */ value) {
    Streamlit.sendData({ value: value });
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
div.tg-select {
    display: flex;
    flex-direction: column;
}

div.tg-select > .tg-select--label {
    color: var(--secondary-text-color);
    margin-bottom: 4px;
}

div.tg-select > .tg-select--field {
    border: unset;
    border-bottom: 1px solid var(--field-underline-color);

    font-size: inherit;
    font-family: inherit;
    color: var(--primary-text-color);

    background-color: inherit;
}

div.tg-select > .tg-select--field:focus-visible {
    outline: unset;
    border-bottom-color: var(--primary-color);
}
`);

export { Select };
