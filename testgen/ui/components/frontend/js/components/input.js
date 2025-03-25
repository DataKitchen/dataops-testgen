/**
 * @typedef Properties
 * @type {object}
 * @property {string?} id
 * @property {string?} label
 * @property {string?} help
 * @property {(string | number)?} value
 * @property {string?} placeholder
 * @property {string[]?} autocompleteOptions
 * @property {string?} icon
 * @property {boolean?} clearable
 * @property {function(string)?} onChange
 * @property {number?} width
 * @property {number?} height
 * @property {string?} style
 */
import van from '../van.min.js';
import { debounce, getValue, loadStylesheet, getRandomId } from '../utils.js';
import { Icon } from './icon.js';
import { withTooltip } from './tooltip.js';
import { Portal } from './portal.js';

const { div,input, label, i } = van.tags;
const defaultHeight = 32;
const iconSize = 22;
const clearIconSize = 20;

const Input = (/** @type Properties */ props) => {
    loadStylesheet('input', stylesheet);

    const domId = van.derive(() => getValue(props.id) ?? getRandomId());
    const value = van.derive(() => getValue(props.value) ?? '');
    van.derive(() => {
        const onChange = props.onChange?.val ?? props.onChange;
        if (value.val !== value.oldVal) {
            onChange(value.val);
        }
    });

    const autocompleteOpened = van.state(false);
    const autocompleteOptions = van.derive(() => {
        const filtered = getValue(props.autocompleteOptions)?.filter(option => option.toLowerCase().includes(value.val.toLowerCase()));
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
            oninput: debounce((/** @type Event */ event) => value.val = event.target.value, 300),
            onclick: van.derive(() => autocompleteOptions.val?.length
                ? () => autocompleteOpened.val = true
                : null
            ),
        }),
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
    font-style: italic;
    color: var(--disabled-text-color);
}

.tg-input--field:focus,
.tg-input--field:focus-visible {
    outline: none;
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
`);

export { Input };
