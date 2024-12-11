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
 * @property {Array.<Option>} options
 * @property {boolean} allowNull
 * @property {Function|null} onChange
 * @property {number?} width
 * @property {number?} height
 * @property {string?} style
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { getRandomId, getValue, getParents, loadStylesheet } from '../utils.js';

const { div, i, label, span } = van.tags;

const Select = (/** @type {Properties} */ props) => {
    loadStylesheet('select', stylesheet);

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight();
    }

    const domId = van.derive(() => props.id?.val ?? getRandomId());
    const opened = van.state(false);
    const options = van.derive(() => {
        const allowNull = getValue(props.allowNull);
        const options = getValue(props.options) ?? [];
        const isOptionSelected = options.filter(option => option.selected).length > 0;

        if (allowNull) {
            return [{label: "---", value: null, selected: !isOptionSelected}, ...options];
        }

        return options;
    });
    const selected = van.state(getValue(options).find(option => option.selected) ?? null);
    const changeHandler = props.onChange || post;

    const closeHandler = (/** @type MouseEvent*/ event) => {
        const selectElement = document.getElementById(domId.val);
        if (event?.target?.id !== domId.val && event?.target?.id !== `${domId.val}-portal` && !getParents(event.target).includes(selectElement)) {
            opened.val = false;
        }
    };
    van.derive(() => {
        const isOpened = opened.val;
        document.removeEventListener('click', closeHandler);
        if (isOpened) {
            document.addEventListener('click', closeHandler);
        }
    });

    const changeSelection = (/** @type Option */ option) => {
        opened.val = false;
        selected.val = option;
        changeHandler(option.value);
    };

    return label(
        {
            id: domId,
            class: 'flex-column fx-gap-1 text-caption tg-select--label',
            style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}; ${getValue(props.style)}`,
            onclick: () => opened.val = true,
        },
        props.label,
        div(
            {
                class: () => `flex-row tg-select--field ${opened.val ? 'opened' : ''}`,
                style: () => getValue(props.height) ? `height: ${getValue(props.height)}px;` : '',
            },
            div(
                { class: 'tg-select--field--content' },
                () => selected?.val?.label,
            ),
            div(
                { class: 'tg-select--field--icon' },
                i(
                    { class: 'material-symbols-rounded' },
                    'expand_more',
                ),
            ),
        ),
        () => opened.val
            ? SelectOptionsPortal(domId.val, getValue(options), changeSelection, getValue(selected))
            : '',
    );
};

const SelectOptionsPortal = (
    /** @type string */ selectId,
    /** @type Array.<Option> */ options,
    /** @type Function */ onChange,
    /** @type Option? */ selectedOption,
) => {
    const domId = `${selectId}-portal`;
    const select = document.getElementById(selectId);
    const selectRect = select.getBoundingClientRect();

    const width = `${selectRect.width}px`;
    const height = `${((options.length ?? 0) * 40)}px`;
    const top = `${selectRect.top + selectRect.height}px`;
    const left = `${selectRect.left}px`;

    return div(
        {
            id: domId,
            class: 'tg-select--portal',
            style: `width: ${width}; height: ${height}; top: ${top}; left: ${left}`,
        },
        options.map(option => div(
            { class: `tg-select--option ${selectedOption.value === option.value ? 'selected' : ''}`, onclick: (/** @type Event */ event) => {
                onChange(option);
                event.stopPropagation();
            } },
            span(option.label)
        )),
    );
};

function post(/** @type string */ value) {
    Streamlit.sendData({ value: value });
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
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

.tg-select--portal {
    position: absolute;
    border-radius: 8px;
    background: var(--select-portal-background);
    box-shadow: rgba(0, 0, 0, 0.16) 0px 4px 16px;
    min-height: 40px;
}

.tg-select--portal > .tg-select--option:first-child {
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

.tg-select--portal > .tg-select--option:last-child {
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
