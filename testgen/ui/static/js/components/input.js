/**
 * @import { Properties as TooltipProperties } from './tooltip.js';
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
 * @property {string[]?} autocompleteOptions
 * @property {string?} icon
 * @property {boolean?} clearable
 * @property {('value' | 'always')?} clearableCondition
 * @property {boolean?} passwordSuggestions
 * @property {function(string, InputState)?} onChange
 * @property {boolean?} disabled
 * @property {boolean?} readonly
 * @property {function(string, InputState)?} onClear
 * @property {number?} width
 * @property {number?} height
 * @property {string?} style
 * @property {string?} type
 * @property {string?} class
 * @property {string?} testId
 * @property {any?} prefix
 * @property {number} step
 * @property {Array<Validator>?} validators
 */
import van from '../van.min.js';
import { debounce, getValue, loadStylesheet, getRandomId, checkIsRequired } from '../utils.js';
import { Icon } from './icon.js';
import { withTooltip } from './tooltip.js';
import { Portal } from './portal.js';
import { caseInsensitiveIncludes } from '../display_utils.js';

const { div, input, label, i, small, span } = van.tags;
const defaultHeight = 38;
const iconSize = 22;
const addonIconSize = 20;
const passwordFieldTypeSwitch = {
    password: 'text',
    text: 'password',
};

const Input = (/** @type Properties */ props) => {
    loadStylesheet('input', stylesheet);

    const domId = van.derive(() => getValue(props.id) ?? getRandomId());
    const value = van.derive(() => getValue(props.value) ?? '');
    const errors = van.derive(() => {
        const validators = getValue(props.validators) ?? [];
        return validators.map(v => v(value.val)).filter(error => error);
    });
    const firstError = van.derive(() => {
        return errors.val[0] ?? '';
    });
    const originalInputType = van.derive(() => getValue(props.type) ?? 'text');
    const inputType = van.state(originalInputType.rawVal);

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

    const onClear = props.onClear?.val ?? props.onClear ?? (() => value.val = '');

    const autocompleteOpened = van.state(false);
    const autocompleteOptions = van.derive(() => {
        const filtered = getValue(props.autocompleteOptions)?.filter(option => caseInsensitiveIncludes(option, value.val));
        if (!filtered?.length) {
            autocompleteOpened.val = false;
        }
        return filtered;
    });
    const onAutocomplete = (/** @type string */ option) => {
        autocompleteOpened.val = false;
        value.val = option;
    };

    return label(
        {
            id: domId,
            class: () => `flex-column fx-gap-1 tg-input--label ${getValue(props.class) ?? ''}`,
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
        div(
            {
                class: () => {
                    const sufixIconCount = Number(value.val && originalInputType.val === 'password') + Number(value.val && getValue(props.clearable));
                    return `flex-row tg-input--field ${getValue(props.disabled) ? 'tg-input--disabled' : ''} sufix-padding-${sufixIconCount}`;
                },
                style: () => `height: ${getValue(props.height) || defaultHeight}px;`,
            },
            props.prefix
                ? div(
                    { class: 'tg-input--field-prefix' },
                    props.prefix,
                )
                : undefined,
            input({
                value,
                name: props.name ?? '',
                type: inputType,
                disabled: props.disabled,
                ...(inputType.val === 'number' ? {step: getValue(props.step)} : {}),
                ...(props.readonly ? {readonly: true} : {}),
                ...(props.passwordSuggestions ?? true ? {} : {autocomplete: 'off', 'data-op-ignore': true}),
                placeholder: () => getValue(props.placeholder) ?? '',
                oninput: debounce((/** @type Event */ event) => {
                    isDirty.val = true;
                    value.val = event.target.value;
                }, 300),
                onclick: van.derive(() => autocompleteOptions.val?.length
                    ? () => autocompleteOpened.val = true
                    : null
                ),
            }),
            () => getValue(props.icon) ? i(
                {
                    class: 'material-symbols-rounded tg-input--icon text-secondary',
                    style: `top: ${((getValue(props.height) || defaultHeight) - iconSize) / 2}px`,
                },
                props.icon,
            ) : '',
            () => {
                const clearableCondition = getValue(props.clearableCondition) ?? 'value';
                const showClearable = getValue(props.clearable) && (
                    clearableCondition === 'always'
                    || (clearableCondition === 'value' && value.val)
                );

                return div(
                    { class: 'flex-row tg-input--icon-actions' },
                    originalInputType.val === 'password' && value.val
                        ? i(
                            {
                                class: 'material-symbols-rounded tg-input--visibility clickable text-secondary',
                                style: `top: ${((getValue(props.height) || defaultHeight) - addonIconSize) / 2}px`,
                                onclick: () => inputType.val = passwordFieldTypeSwitch[inputType.val],
                            },
                            inputType.val === 'password' ? 'visibility' : 'visibility_off',
                        )
                        : '',
                    showClearable
                        ? i(
                            {
                                class: () => `material-symbols-rounded tg-input--clear text-secondary clickable`,
                                style: `top: ${((getValue(props.height) || defaultHeight) - addonIconSize) / 2}px`,
                                onclick: onClear,
                            },
                            'clear',
                        )
                        : '',
                );
            },
        ),
        () =>
            isDirty.val && firstError.val
                ? small({ class: 'tg-input--error' }, firstError)
                : '',
        Portal(
            { target: domId.val, targetRelative: true, opened: autocompleteOpened },
            () => div(
                { class: 'tg-input--options-wrapper' },
                autocompleteOptions.val?.map(option =>
                    div(
                        {
                            class: 'tg-input--option',
                            onclick: (/** @type Event */ event) => {
                                // https://stackoverflow.com/questions/61273446/stop-click-event-propagation-on-a-label
                                event.preventDefault();
                                event.stopPropagation();
                                onAutocomplete(option);
                            },
                        },
                        option,
                    )
                ),
            ),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-input--field {
    position: relative;
}

.tg-input--icon {
    position: absolute;
    left: 4px;
    font-size: ${iconSize}px;
}

.tg-input--field:has(.tg-input--icon) {
    padding-left: 28px;
}

.tg-input--icon-actions {
    position: absolute;
    right: 8px;
}

.tg-input--clear,
.tg-input--visibility {
    font-size: ${addonIconSize}px;
}

.tg-input--field.sufix-padding-1 {
    padding-right: ${addonIconSize + 8}px;
}

.tg-input--field.sufix-padding-2 {
    padding-right: ${addonIconSize * 2 + 8 * 2}px;;
}

.tg-input--field {
    box-sizing: border-box;
    width: 100%;
    border-radius: 8px;
    border: 1px solid transparent;
    transition: border-color 0.3s;
    background-color: var(--form-field-color);
    color: var(--primary-text-color);
    font-size: 14px;
}
.tg-input--field > .tg-input--field-prefix {
    padding-left: 8px;
}
.tg-input--field > input {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    font-size: 14px;
    background-color: var(--form-field-color);
    color: var(--primary-text-color);
    border: unset;
    padding: 4px 8px;
    border-radius: 8px;
    outline: none;
}

.tg-input--field > input::placeholder {
    font-style: italic;
    color: var(--disabled-text-color);
}

.tg-input--field:has(input:focus),
.tg-input--field:has(input:focus-visible) {
    border-color: var(--primary-color);
}

.tg-input--options-wrapper {
    border-radius: 8px;
    background: var(--portal-background);
    box-shadow: var(--portal-box-shadow);
    min-height: 40px;
    max-height: 400px;
    overflow: auto;
    z-index: 99;
}

.tg-input--options-wrapper > .tg-input--option:first-child {
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

.tg-input--options-wrapper > .tg-input--option:last-child {
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}

.tg-input--option {
    display: flex;
    align-items: center;
    height: 32px;
    padding: 0px 8px;
    cursor: pointer;
    font-size: 14px;
    color: var(--primary-text-color);
}
.tg-input--option:hover {
    background: var(--select-hover-background);
}

.tg-input--disabled > input {
    cursor: not-allowed;
    color: var(--disabled-text-color);
}

.tg-input--label > .tg-input--error {
    height: 12px;
    color: var(--error-color);
}
`);

export { Input };
