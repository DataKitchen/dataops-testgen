/**
 * @typedef Properties
 * @type {object}
 * @property {string?} name
 * @property {string} label
 * @property {string?} help
 * @property {boolean?} checked
 * @property {boolean?} indeterminate
 * @property {function(boolean, Event)?} onChange
 * @property {number?} width
 * @property {string?} testId
 * @property {boolean?} disabled
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { withTooltip } from './tooltip.js';
import { Icon } from './icon.js';

const { input, label, span } = van.tags;

const Checkbox = (/** @type Properties */ props) => {
    loadStylesheet('checkbox', stylesheet);

    return label(
        {
            class: 'flex-row fx-gap-2 clickable',
            'data-testid': props.testId ?? props.name ?? '',
            style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}`,
        },
        input({
            type: 'checkbox',
            name: props.name ?? '',
            class: 'tg-checkbox--input clickable',
            checked: props.checked,
            indeterminate: props.indeterminate,
            onchange: van.derive(() => {
                const onChange = props.onChange?.val ?? props.onChange;
                return onChange ? (/** @type Event */ event) => onChange(event.target.checked, event) : null;
            }),
            disabled: props.disabled ?? false,
        }),
        span({'data-testid': 'checkbox-label'}, props.label),
        () => getValue(props.help)
            ? withTooltip(
                Icon({ size: 16, classes: 'text-disabled' }, 'help'),
                { text: props.help, position: 'top', width: 200 }
            )
            : null,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-checkbox--input {
    appearance: none;
    box-sizing: border-box;
    margin: 0;
    width: 18px;
    height: 18px;
    flex-shrink: 0;
    border: 1px solid var(--secondary-text-color);
    border-radius: 4px;
    position: relative;
    transition-property: border-color, background-color;
    transition-duration: 0.3s;
}

.tg-checkbox--input:focus,
.tg-checkbox--input:focus-visible {
    outline: none;
}

.tg-checkbox--input:focus-visible::before {
    content: '';
    box-sizing: border-box;
    position: absolute;
    top: -4px;
    left: -4px;
    width: 24px;
    height: 24px;
    border: 3px solid var(--border-color);
    border-radius: 7px;
}

.tg-checkbox--input:checked,
.tg-checkbox--input:indeterminate {
    border-color: transparent;
    background-color: var(--primary-color);
}

.tg-checkbox--input:checked:disabled,
.tg-checkbox--input:indeterminate:disabled {
    cursor: not-allowed;
    background-color: var(--disabled-text-color);
}

.tg-checkbox--input:checked::after,
.tg-checkbox--input:indeterminate::after {
    position: absolute;
    top: -4px;
    left: -3px;
    font-family: 'Material Symbols Rounded';
    font-size: 22px;
    color: white;
}

.tg-checkbox--input:checked::after {
    content: 'check';
}

.tg-checkbox--input:indeterminate::after {
    content: 'check_indeterminate_small';
}
`);

export { Checkbox };
