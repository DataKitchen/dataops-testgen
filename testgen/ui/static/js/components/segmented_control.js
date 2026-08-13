/**
 * @typedef Option
 * @type {object}
 * @property {string} label
 * @property {string} value
 *
 * @typedef Properties
 * @type {object}
 * @property {string?} id
 * @property {Option[]} options
 * @property {string} value
 * @property {string?} pendingValue Option shown as awaiting confirmation, not yet selected
 * @property {function(string)?} onChange
 * @property {string?} class
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { button, div } = van.tags;

const SegmentedControl = (/** @type Properties */ props) => {
    loadStylesheet('segmentedControl', stylesheet);

    return div(
        {
            id: getValue(props.id) ?? undefined,
            class: () => `tg-segmented-control ${getValue(props.class) ?? ''}`,
            'data-testid': 'segmented-control',
        },
        () => {
            const selected = getValue(props.value);
            const pending = getValue(props.pendingValue);
            return div(
                { class: 'tg-segmented-control--options' },
                getValue(props.options).map((option) => button(
                    {
                        class: `tg-segmented-control--option ${option.value === selected ? 'active' : ''} `
                            + `${option.value === pending ? 'pending' : ''}`,
                        'data-testid': 'segmented-control-option',
                        'data-value': option.value,
                        onclick: () => props.onChange?.(option.value),
                    },
                    option.label,
                )),
            );
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-segmented-control {
    display: inline-flex;
}

.tg-segmented-control--options {
    display: flex;
    flex-direction: row;
    align-items: stretch;
    height: 32px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    overflow: hidden;
}

.tg-segmented-control--option {
    padding: 0 12px;
    border: unset;
    outline: 0;
    background-color: transparent;
    color: var(--secondary-text-color);
    font-size: 13px;
    white-space: nowrap;
    cursor: pointer;
    transition: background-color 0.2s ease-in-out, color 0.2s ease-in-out;
}

.tg-segmented-control--option + .tg-segmented-control--option {
    border-left: 1px solid var(--border-color);
}

.tg-segmented-control--option:hover:not(.active) {
    background-color: var(--select-hover-background);
}

.tg-segmented-control--option.active {
    background-color: var(--primary-color);
    color: white;
}

.tg-segmented-control--option.pending:not(.active) {
    background-color: var(--select-hover-background);
    color: var(--primary-text-color);
}
`);

export { SegmentedControl };
