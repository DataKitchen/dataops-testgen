/**
* @typedef Option
 * @type {object}
 * @property {string} label
 * @property {string} help
 * @property {string | number | boolean | null} value
 *
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {Option[]} options
 * @property {string | number | boolean | null} value
 * @property {function(string | number | boolean | null)?} onChange
 * @property {number?} width
 * @property {('default' | 'inline' | 'vertical')?} layout
 */
import van from '../van.min.js';
import { getRandomId, getValue, loadStylesheet } from '../utils.js';
import { withTooltip } from './tooltip.js';
import { Icon } from './icon.js';

const { div, input, label, span } = van.tags;

const RadioGroup = (/** @type Properties */ props) => {
    loadStylesheet('radioGroup', stylesheet);

    const groupName = getRandomId();
    const layout = getValue(props.layout) ?? 'default';

    return div(
        { class: () => `tg-radio-group--wrapper ${layout}`, style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}` },
        div(
            { class: 'text-caption tg-radio-group--label' },
            props.label,
        ),
        () => div(
            { class: 'tg-radio-group' },
            getValue(props.options).map(option => label(
                { class: `flex-row fx-gap-2 clickable ${layout === 'vertical' ? 'fx-align-flex-start' : ''}` },
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
                layout === 'vertical'
                    ? div(
                        { class: 'flex-column fx-gap-1' },
                        option.label,
                        span(
                            { class: 'text-caption tg-radio-group--help' },
                            option.help,
                        ),
                    )
                    : option.label,
                layout !== 'vertical' && option.help
                    ? withTooltip(
                        Icon({ size: 16, classes: 'text-disabled' }, 'help'),
                        { text: option.help, position: 'top', width: 200 }
                    )
                    : null,
            )),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-radio-group--wrapper.inline {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
}

.tg-radio-group--wrapper.default .tg-radio-group--label,
.tg-radio-group--wrapper.vertical .tg-radio-group--label {
    margin-bottom: 4px;
}

.tg-radio-group--wrapper.vertical .tg-radio-group--label {
    margin-bottom: 12px;
}

.tg-radio-group--wrapper.default .tg-radio-group,
.tg-radio-group--wrapper.inline .tg-radio-group {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 16px;
    height: 32px;
}

.tg-radio-group--wrapper.vertical .tg-radio-group {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.tg-radio-group--input {
    flex: 0 0 auto;
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

.tg-radio-group--help {
    white-space: pre-wrap;
    line-height: 16px;
}
`);

export { RadioGroup };
