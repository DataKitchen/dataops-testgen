/**
 * @typedef Properties
 * @type {object}
 * @property {string?} id
 * @property {string?} name
 * @property {string?} label
 * @property {string?} help
 * @property {TooltipProperties['position']} helpPlacement
 * @property {(string | number)?} value
 * @property {string?} placeholder
 * @property {string?} icon
 * @property {boolean?} disabled
 * @property {function(string, InputState)?} onChange
 * @property {string?} style
 * @property {string?} class
 * @property {string?} testId
 */
import van from '../van.min.js';
import { debounce, getValue, loadStylesheet, getRandomId } from '../utils.js';
import { Icon } from './icon.js';
import { withTooltip } from './tooltip.js';

const { div, label, textarea } = van.tags;
const defaultHeight = 64;

const Textarea = (/** @type Properties */ props) => {
    loadStylesheet('textarea', stylesheet);

    const domId = van.derive(() => getValue(props.id) ?? getRandomId());
    const value = van.derive(() => getValue(props.value) ?? '');

    const onChange = props.onChange?.val ?? props.onChange;
    if (onChange) {
        onChange(value.val);
    }
    van.derive(() => {
        const onChange = props.onChange?.val ?? props.onChange;
        if (onChange && value.val !== value.oldVal) {
            onChange(value.val);
        }
    });

    return label(
        {
            id: domId,
            class: () => `flex-column fx-gap-1 ${getValue(props.class) ?? ''}`,
            style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}; ${getValue(props.style)}`,
            'data-testid': props.testId ?? props.name ?? '',
        },
        div(
            { class: 'flex-row fx-gap-1 text-caption' },
            props.label,
            () => getValue(props.help)
                ? withTooltip(
                    Icon({ size: 16, classes: 'text-disabled' }, 'help'),
                    { text: props.help, position: getValue(props.helpPlacement) ?? 'top', width: 200 }
                )
                : null,
        ),
        textarea({
            class: () => `tg-textarea--field ${getValue(props.disabled) ? 'tg-textarea--disabled' : ''}`,
            style: () => `min-height: ${getValue(props.height) || defaultHeight}px;`,
            value,
            name: props.name ?? '',
            disabled: props.disabled,
            placeholder: () => getValue(props.placeholder) ?? '',
            oninput: debounce((/** @type Event */ event) => value.val = event.target.value, 300),
        }),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-textarea--field {
    box-sizing: border-box;
    width: 100%;
    border-radius: 8px;
    border: 1px solid transparent;
    transition: border-color 0.3s;
    background-color: var(--form-field-color);
    padding: 4px 8px;
    color: var(--primary-text-color);
    font-size: 14px;
    resize: vertical;
}

.tg-textarea--field::placeholder {
    font-style: italic;
    color: var(--disabled-text-color);
}

.tg-textarea--field:focus,
.tg-textarea--field:focus-visible {
    outline: none;
    border-color: var(--primary-color);
}
`);

export { Textarea };
