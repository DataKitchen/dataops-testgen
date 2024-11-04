/**
 * @typedef Properties
 * @type {object}
 * @property {string?} label
 * @property {(string | number)?} value
 * @property {string?} placeholder
 * @property {string?} icon
 * @property {boolean?} clearable
 * @property {function?} onChange
 * @property {number?} width
 */
import van from '../van.min.js';
import { debounce, getValue, loadStylesheet } from '../utils.js';

const { input, label, i } = van.tags;

const Input = (/** @type Properties */ props) => {
    loadStylesheet('input', stylesheet);

    const value = van.derive(() => getValue(props.value) ?? '');
    van.derive(() => {
        const onChange = props.onChange?.val ?? props.onChange;
        onChange?.(value.val);
    });

    return label(
        {
            class: 'flex-column fx-gap-1 text-caption text-capitalize tg-input--label',
            style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}`,
        },
        props.label,
        () => getValue(props.icon) ? i(
            { class: 'material-symbols-rounded tg-input--icon' },
            props.icon,
        ) : '',
        () => getValue(props.clearable) ? i(
            {
                class: () => `material-symbols-rounded tg-input--clear clickable ${value.val ? '' : 'hidden'}`,
                onclick: () => value.val = '',
            },
            'clear',
        ) : '',
        input({
            class: 'tg-input--field',
            value,
            placeholder: () => getValue(props.placeholder) ?? '',
            oninput: debounce(event => value.val = event.target.value, 300),
        }),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-input--label {
    position: relative;
}

.tg-input--icon {
    position: absolute;
    bottom: 5px;
    left: 4px;
    font-size: 22px;
}

.tg-input--icon ~ .tg-input--field {
    padding-left: 28px;
}

.tg-input--clear {
    position: absolute;
    bottom: 6px;
    right: 4px;
    font-size: 20px;
}

.tg-input--clear ~ .tg-input--field {
    padding-right: 24px;
}

.tg-input--field {
    box-sizing: border-box;
    width: 100%;
    height: 32px;
    border-radius: 8px;
    border: 1px solid transparent;
    transition: border-color 0.3s;
    background-color: var(--form-field-color);
    padding: 4px 8px;
    color: var(--primary-text-color);
    font-size: 14px;
}

.tg-input--field::placeholder {
    color: var(--disabled-text-color);
}

.tg-input--field:focus,
.tg-input--field:focus-visible {
    outline: none;
    border-color: var(--primary-color);
}
`);

export { Input };
