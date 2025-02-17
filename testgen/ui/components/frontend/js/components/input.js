/**
 * @typedef Properties
 * @type {object}
 * @property {string?} label
 * @property {string?} help
 * @property {(string | number)?} value
 * @property {string?} placeholder
 * @property {string?} icon
 * @property {boolean?} clearable
 * @property {function?} onChange
 * @property {number?} width
 * @property {number?} height
 * @property {string?} style
 */
import van from '../van.min.js';
import { debounce, getValue, loadStylesheet } from '../utils.js';
import { Icon } from './icon.js';
import { withTooltip } from './tooltip.js';

const { div,input, label, i } = van.tags;
const defaultHeight = 32;
const iconSize = 22;
const clearIconSize = 20;

const Input = (/** @type Properties */ props) => {
    loadStylesheet('input', stylesheet);

    const value = van.derive(() => getValue(props.value) ?? '');
    van.derive(() => {
        const onChange = props.onChange?.val ?? props.onChange;
        onChange?.(value.val);
    });

    return label(
        {
            class: 'flex-column fx-gap-1 tg-input--label',
            style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}; ${getValue(props.style)}`,
        },
        div(
            { class: 'flex-row fx-gap-1 text-caption' },
            props.label,
            () => getValue(props.help)
                ? withTooltip(
                    Icon({ size: 16, classes: 'text-disabled' }, 'help'),
                    { text: props.help, position: 'top', width: 200 }
                )
                : null,
        ),
        () => getValue(props.icon) ? i(
            {
                class: 'material-symbols-rounded tg-input--icon',
                style: `bottom: ${((getValue(props.height) || defaultHeight) - iconSize) / 2}px`,
            },
            props.icon,
        ) : '',
        () => getValue(props.clearable) ? i(
            {
                class: () => `material-symbols-rounded tg-input--clear clickable ${value.val ? '' : 'hidden'}`,
                style: `bottom: ${((getValue(props.height) || defaultHeight) - clearIconSize) / 2}px`,
                onclick: () => value.val = '',
            },
            'clear',
        ) : '',
        input({
            class: 'tg-input--field',
            style: () => `height: ${getValue(props.height) || defaultHeight}px;`,
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
    left: 4px;
    font-size: ${iconSize}px;
}

.tg-input--icon ~ .tg-input--field {
    padding-left: 28px;
}

.tg-input--clear {
    position: absolute;
    right: 4px;
    font-size: ${clearIconSize}px;
}

.tg-input--clear ~ .tg-input--field {
    padding-right: 24px;
}

.tg-input--field {
    box-sizing: border-box;
    width: 100%;
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
