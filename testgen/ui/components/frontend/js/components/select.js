/**
 * @typedef SelectOption
 * @type {object}
 * @property {string} label
 * @property {string} value
 * @property {string?} icon
 *
 * @typedef Properties
 * @type {object}
 * @property {string?} id
 * @property {string} label
 * @property {string?} value
 * @property {Array.<SelectOption>} options
 * @property {boolean} allowNull
 * @property {Function|null} onChange
 * @property {boolean?} disabled
 * @property {boolean?} required
 * @property {number?} width
 * @property {number?} height
 * @property {string?} style
 * @property {string?} testId
 * @property {number?} portalClass
 * @property {boolean?} filterable
 * @property {('normal' | 'inline')?} triggerStyle
 */
import van from '../van.min.js';
import { getRandomId, getValue, loadStylesheet, isState, isEqual } from '../utils.js';
import { Portal } from './portal.js';
import { Icon } from './icon.js';

const { div, i, input, label, span } = van.tags;

const Select = (/** @type {Properties} */ props) => {
    loadStylesheet('select', stylesheet);

    const domId = van.derive(() => props.id?.val ?? getRandomId());
    const opened = van.state(false);
    const optionsFilter = van.state('');
    const options = van.derive(() => {
        const options = getValue(props.options) ?? [];
        const allowNull = getValue(props.allowNull);

        if (allowNull) {
            return [
                {label: "---", value: null},
                ...options,
            ];
        }

        return options;
    });
    const filteredOptions = van.derive(() => {
        const allOptions = getValue(options);
        const isFilterable = getValue(props.filterable);
        const filterTerm = getValue(optionsFilter);
        if (isFilterable && filterTerm.length) {
            const filteredOptions_ = [];
            for (let i = 0; i < allOptions.length; i++) {
                const option = allOptions[i];
                if (option.label === filterTerm) {
                    return allOptions;
                }

                if (option.label.toLowerCase().includes(filterTerm.toLowerCase())) {
                    filteredOptions_.push(option);
                }
            }
            return filteredOptions_;
        }
        return allOptions;
    });

    const value = isState(props.value) ? props.value : van.state(props.value ?? null);
    const initialSelection = options.val?.find((op) => op.value === value.val);
    const valueLabel = van.state(initialSelection?.label ?? '');
    const valueIcon = van.state(initialSelection?.icon ?? undefined);

    const changeSelection = (/** @type SelectOption */ option) => {
        opened.val = false;
        value.val = option.value;
    };

    const filterOptions = (/** @type InputEvent */ event) => {
        optionsFilter.val = event.target.value;
    };

    const showPortal = (/** @type Event */ event) => {
        event.stopPropagation();
        event.stopImmediatePropagation();
        opened.val = getValue(props.disabled) ? false : true;
    };

    van.derive(() => {
        const currentOptions = getValue(options);
        const previousValue = value.oldVal;
        let currentValue = getValue(value);
        const selectedOption = currentOptions.find((op) => op.value === currentValue);

        if (selectedOption === undefined) {
            currentValue = null;
            setTimeout(() => value.val = null, 0.1);
        }

        if (!isEqual(currentValue, previousValue)) {
            valueLabel.val = selectedOption?.label ?? '';
            valueIcon.val = selectedOption?.icon ?? undefined;

            props.onChange?.(currentValue, { valid: !!currentValue || !getValue(props.required) });
        }
    });

    return label(
        {
            id: domId,
            class: () => `flex-column fx-gap-1 text-caption tg-select--label ${getValue(props.disabled) ? 'disabled' : ''}`,
            style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}; ${getValue(props.style)}`,
            'data-testid': getValue(props.testId) ?? '',
            onclick: showPortal,
        },
        span(
            { class: 'flex-row fx-gap-1', 'data-testid': 'select-label' },
            props.label,
            () => getValue(props.required)
                ? span({ class: 'text-error' }, '*')
                : '',
        ),

        () => getValue(props.triggerStyle) === 'inline'
            ? div(
                {class: 'tg-select--inline-trigger flex-row'},
                span({}, valueLabel.val ?? '---'),
                div(
                    { class: 'tg-select--field--icon ', 'data-testid': 'select-input-trigger' },
                    i(
                        { class: 'material-symbols-rounded' },
                        'expand_more',
                    ),
                ),
            )
            : div(
                {
                    class: () => `flex-row tg-select--field ${opened.val ? 'opened' : ''}`,
                    style: () => getValue(props.height) ? `height: ${getValue(props.height)}px;` : '',
                    'data-testid': 'select-input',
                },
                () => {
                    return div(
                        { class: 'tg-select--field--content', 'data-testid': 'select-input-display' },
                        valueIcon.val
                            ? Icon({ classes: 'mr-2' }, valueIcon.val)
                            : undefined,
                        getValue(props.filterable)
                            ? input({
                                id: `tg-select--field--${getRandomId()}`,
                                value: valueLabel.val,
                                onkeyup: filterOptions,
                            })
                            : valueLabel.val,
                    );
                },
                div(
                    { class: 'tg-select--field--icon', 'data-testid': 'select-input-trigger' },
                    i(
                        {
                            class: 'material-symbols-rounded',
                        },
                        'expand_more',
                    ),
                ),
            ),

        Portal(
            {target: domId.val, targetRelative: true, opened},
            () => div(
                {
                    class: () => `tg-select--options-wrapper mt-1 ${getValue(props.portalClass) ?? ''}`,
                    'data-testid': 'select-options',
                },
                getValue(filteredOptions).map(option =>
                    div(
                        {
                            class: () => `tg-select--option ${getValue(value) === option.value ? 'selected' : ''}`,
                            onclick: (/** @type Event */ event) => {
                                changeSelection(option);
                                event.stopPropagation();
                            },
                            'data-testid': 'select-options-item',
                        },
                        option.icon
                            ? Icon({ classes: 'mr-2' }, option.icon)
                            : undefined,
                        span(option.label),
                    )
                ),
            ),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-select--label {
    position: relative;
}
.tg-select--label.disabled {
    cursor: not-allowed;
    color: var(--disabled-text-color);
}

.tg-select--label.disabled .tg-select--field {
    color: var(--disabled-text-color);
}

.tg-select--field {
    box-sizing: border-box;
    width: 100%;
    height: 38px;
    min-width: 200px;
    border: 1px solid transparent;
    transition: border-color 0.3s;
    background-color: var(--form-field-color);
    padding: 4px 8px;
    color: var(--primary-text-color);
    border-radius: 8px;
}

.tg-select--field.opened {
    border-color: var(--primary-color);
}

.tg-select--field--content {
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    height: 100%;
    flex: 1;
    font-weight: 500;
}

.tg-select--field--content > input {
    border: unset !important;
    background: transparent !important;
    outline: none !important;
    width: 100%;
    font-weight: 500;
    font-family: 'Roboto', 'Helvetica Neue', sans-serif;
    color: var(--primary-text-color);
}

.tg-select--field--icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 100%;
}

.tg-select--field--icon i {
    font-size: 20px;
}

.tg-select--options-wrapper {
    border-radius: 8px;
    background: var(--portal-background);
    box-shadow: var(--portal-box-shadow);
    min-height: 40px;
    max-height: 400px;
    overflow: auto;
    z-index: 99;
}

.tg-select--options-wrapper > .tg-select--option:first-child {
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

.tg-select--options-wrapper > .tg-select--option:last-child {
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}

.tg-select--option {
    display: flex;
    align-items: center;
    height: 40px;
    padding: 0px 16px;
    cursor: pointer;
    font-size: 14px;
    color: var(--primary-text-color);
}
.tg-select--option:hover {
    background: var(--select-hover-background);
}

.tg-select--option.selected {
    background: var(--select-hover-background);
    color: var(--primary-color);
}

.tg-select--inline-trigger {
    border-bottom: 1px solid var(--border-color);
}

.tg-select--inline-trigger > span {
    min-width: 24px;
}
`);

export { Select };
