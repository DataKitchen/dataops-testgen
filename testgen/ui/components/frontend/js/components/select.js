/**
 * @typedef Option
 * @type {object}
 * @property {string} label
 * @property {string} value
 * @property {boolean} selected
 *
 * @typedef Properties
 * @type {object}
 * @property {string?} id
 * @property {string} label
 * @property {string?} value
 * @property {Array.<Option>} options
 * @property {boolean} allowNull
 * @property {Function|null} onChange
 * @property {boolean?} disabled
 * @property {number?} width
 * @property {number?} height
 * @property {string?} style
 */
import van from '../van.min.js';
import { getRandomId, getValue, loadStylesheet, isState, isEqual } from '../utils.js';
import { Portal } from './portal.js';

const { div, i, label, span } = van.tags;

const Select = (/** @type {Properties} */ props) => {
    loadStylesheet('select', stylesheet);

    const domId = van.derive(() => props.id?.val ?? getRandomId());
    const opened = van.state(false);
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
    const value = isState(props.value) ? props.value : van.state(props.value ?? null);
    const valueLabel = van.derive(() => {
        const currentOptions = getValue(options);
        const currentValue = getValue(value);
        return currentOptions?.find((op) => op.value === currentValue)?.label ?? '';
    });

    const changeSelection = (/** @type Option */ option) => {
        opened.val = false;
        value.val = option.value;
    };

    van.derive(() => {
        const currentOptions = getValue(options);

        let currentValue = getValue(value);
        let previousValue = value.oldVal;
        if (currentOptions.find((op) => op.value === currentValue) === undefined) {
            currentValue = value.val = null;
        }

        if (!isEqual(currentValue, previousValue)) {
            props.onChange?.(currentValue);
        }
    });

    return label(
        {
            id: domId,
            class: () => `flex-column fx-gap-1 text-caption tg-select--label ${getValue(props.disabled) ? 'disabled' : ''}`,
            style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}; ${getValue(props.style)}`,
            onclick: van.derive(() => !getValue(props.disabled) ? () => opened.val = !opened.val : null),
        },
        props.label,
        div(
            {
                class: () => `flex-row tg-select--field ${opened.val ? 'opened' : ''}`,
                style: () => getValue(props.height) ? `height: ${getValue(props.height)}px;` : '',
            },
            div(
                { class: 'tg-select--field--content' },
                valueLabel,
            ),
            div(
                { class: 'tg-select--field--icon' },
                i(
                    { class: 'material-symbols-rounded' },
                    'expand_more',
                ),
            ),
        ),
        Portal(
            {target: domId.val, targetRelative: true, opened},
            () => div(
                { class: 'tg-select--options-wrapper mt-1' },
                getValue(options).map(option =>
                    div(
                        {
                            class: () => `tg-select--option ${getValue(value) === option.value ? 'selected' : ''}`,
                            onclick: (/** @type Event */ event) => {
                                changeSelection(option);
                                event.stopPropagation();
                            },
                        },
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
    height: 32px;
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
`);

export { Select };
