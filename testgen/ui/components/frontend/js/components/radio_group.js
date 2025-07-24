/**
* @typedef Option
 * @type {object}
 * @property {string} label
 * @property {string | number | boolean | null} value
 *
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {Option[]} options
 * @property {string | number | boolean | null} selected
 * @property {function(string | number | boolean | null)?} onChange
 * @property {number?} width
 * @property {boolean?} inline
 */
import van from '../van.min.js';
import { getRandomId, getValue, loadStylesheet } from '../utils.js';

const { div, input, label } = van.tags;

const RadioGroup = (/** @type Properties */ props) => {
    loadStylesheet('radioGroup', stylesheet);

    const groupName = getRandomId();

    return div(
        { class: () => `${getValue(props.inline) ? 'flex-row fx-gap-2' : ''}`, style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}` },
        div(
            { class: () => `text-caption ${getValue(props.inline) ? '' : 'mb-1'}` },
            props.label,
        ),
        () => div(
            { class: 'flex-row fx-gap-4 tg-radio-group' },
            getValue(props.options).map(option => label(
                { class: 'flex-row fx-gap-2 clickable' },
                input({
                    type: 'radio',
                    name: groupName,
                    value: option.value,
                    checked: () => option.value === getValue(props.value),
                    onchange: van.derive(() => {
                        const onChange = props.onChange?.val ?? props.onChange;
                        return onChange ? () => onChange(option.value) : null;
                    }),
                    class: 'tg-radio-group--input',
                }),
                option.label,
            )),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-radio-group {
    height: 32px;
}

.tg-radio-group--input {
    appearance: none;
    box-sizing: border-box;
    margin: 0;
    width: 18px;
    height: 18px;
    border: 1px solid var(--secondary-text-color);
    border-radius: 9px;
    position: relative;
    transition-property: border-color, background-color;
    transition-duration: 0.3s;
}

.tg-radio-group--input:focus,
.tg-radio-group--input:focus-visible {
    outline: none;
}

.tg-radio-group--input:focus-visible::before {
    content: '';
    box-sizing: border-box;
    position: absolute;
    top: -4px;
    left: -4px;
    width: 24px;
    height: 24px;
    border: 3px solid var(--border-color);
    border-radius: 12px;
}

.tg-radio-group--input:checked {
    border-color: var(--primary-color);
}

.tg-radio-group--input:checked::after {
    content: '';
    box-sizing: border-box;
    position: absolute;
    top: 3px;
    left: 3px;
    width: 10px;
    height: 10px;
    background-color: var(--primary-color);
    border-radius: 5px;
}
`);

export { RadioGroup };
