/**
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {string?} name
 * @property {boolean?} checked
 * @property {function(boolean)?} onChange
 */
import van from '../van.min.js';
import { loadStylesheet } from '../utils.js';

const { input, label } = van.tags;

const Toggle = (/** @type Properties */ props) => {
    loadStylesheet('toggle', stylesheet);

    return label(
        { class: 'flex-row fx-gap-2 clickable', 'data-testid': props.name ?? '' },
        input({
            type: 'checkbox',
            role: 'switch',
            class: 'tg-toggle--input clickable',
            name: props.name ?? '',
            checked: props.checked,
            onchange: van.derive(() => {
                const onChange = props.onChange?.val ?? props.onChange;
                return onChange ? (/** @type Event */ event) => onChange(event.target.checked) : null;
            }),
        }),
        props.label,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-toggle--input {
    appearance: none;
    margin: 0;
    width: 28px;
    height: 16px;
    flex-shrink: 0;
    border-radius: 8px;
    background-color: var(--disabled-text-color);
    position: relative;
    transition-property: background-color;
    transition-duration: 0.3s;
}

.tg-toggle--input::after {
    content: '';
    position: absolute;
    top: 2px;
    left: 2px;
    width: 12px;
    height: 12px;
    border-radius: 6px;
    background-color: #fff;
    transition-property: left;
    transition-duration: 0.3s;
}

.tg-toggle--input:focus,
.tg-toggle--input:focus-visible {
    outline: none;
}

.tg-toggle--input:focus-visible::before {
    content: '';
    box-sizing: border-box;
    position: absolute;
    top: -3px;
    left: -3px;
    width: 34px;
    height: 22px;
    border: 3px solid var(--border-color);
    border-radius: 11px;
}

.tg-toggle--input:checked {
    background-color: var(--primary-color);
}

.tg-toggle--input:checked::after {
    left: 14px;
}
`);

export { Toggle };
