/**
 * @import { Validator } from '../form_validators.js';
 *
 * @typedef InputState
 * @type {object}
 * @property {boolean} valid
 * @property {string[]} errors
 *
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
 * @property {number?} width
 * @property {number?} height
 * @property {string?} testId
 * @property {Array<Validator>?} validators
 */
import van from '../van.min.js';
import { debounce, getValue, loadStylesheet, getRandomId, checkIsRequired } from '../utils.js';
import { Icon } from './icon.js';
import { withTooltip } from './tooltip.js';

const { div, label, textarea, small, span } = van.tags;
const defaultHeight = 64;

const Textarea = (/** @type Properties */ props) => {
    loadStylesheet('textarea', stylesheet);

    const domId = van.derive(() => getValue(props.id) ?? getRandomId());
    const value = van.derive(() => getValue(props.value) ?? '');
    const errors = van.derive(() => {
        const validators = getValue(props.validators) ?? [];
        return validators.map(v => v(value.val)).filter(error => error);
    });
    const firstError = van.derive(() => {
        return errors.val[0] ?? '';
    });

    const isRequired = van.state(false);
    const isDirty = van.state(false);
    const onChange = props.onChange?.val ?? props.onChange;
    if (onChange) {
        onChange(value.val, { errors: errors.val, valid: errors.val.length <= 0 });
    }
    van.derive(() => {
        const onChange = props.onChange?.val ?? props.onChange;
        if (onChange && (value.val !== value.oldVal || errors.val.length !== errors.oldVal.length)) {
            onChange(value.val, { errors: errors.val, valid: errors.val.length <= 0 });
        }
    });

    van.derive(() => {
        isRequired.val = checkIsRequired(getValue(props.validators) ?? []);
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
            () => isRequired.val
                ? span({ class: 'text-error' }, '*')
                : '',
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
            oninput: debounce((/** @type Event */ event) => {
                isDirty.val = true;
                value.val = event.target.value;
            }, 300),
        }),
        () =>
            isDirty.val && firstError.val
                ? small({ class: 'tg-textarea--error' }, firstError)
                : '',
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

.tg-textarea--error {
    height: 12px;
    color: var(--error-color);
}
`);

export { Textarea };
