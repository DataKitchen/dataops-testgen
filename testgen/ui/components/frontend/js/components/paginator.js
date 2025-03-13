/**
 * @typedef Properties
 * @type {object}
 * @property {number} count
 * @property {number} pageSize
 * @property {number?} pageIndex
 * @property {function(number)?} onChange
 */

import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';

const { div, span, i, button } = van.tags;

const Paginator = (/** @type Properties */ props) => {
    loadStylesheet('paginator', stylesheet);

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(32);
    }

    const { count, pageSize } = props;
    const pageIndexState = van.state(getValue(props.pageIndex) ?? 0);
    van.derive(() => {
        const onChange = props.onChange?.val ?? props.onChange ?? changePage;
        onChange(pageIndexState.val);
    });

    return div(
        { class: 'tg-paginator' },
        span(
            { class: 'tg-paginator--label' },
            () => {
                const pageIndex = pageIndexState.val;
                const countValue = getValue(count);
                const pageSizeValue = getValue(pageSize);
                return `${pageSizeValue * pageIndex + 1} - ${Math.min(countValue, pageSizeValue * (pageIndex + 1))} of ${countValue}`;
            },
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => pageIndexState.val = 0,
                disabled: () => pageIndexState.val === 0,
            },
            i({class: 'material-symbols-rounded'}, 'first_page')
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => pageIndexState.val--,
                disabled: () => pageIndexState.val === 0,
            },
            i({class: 'material-symbols-rounded'}, 'chevron_left')
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => pageIndexState.val++,
                disabled: () => pageIndexState.val === Math.ceil(getValue(count) / getValue(pageSize)) - 1,
            },
            i({class: 'material-symbols-rounded'}, 'chevron_right')
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => pageIndexState.val = Math.ceil(getValue(count) / getValue(pageSize)) - 1,
                disabled: () => pageIndexState.val === Math.ceil(getValue(count) / getValue(pageSize)) - 1,
            },
            i({class: 'material-symbols-rounded'}, 'last_page')
        ),
    );
};

function changePage(/** @type number */ page_index) {
    emitEvent('PageChanged', { page_index })
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-paginator {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
}

.tg-paginator--label {
    margin-right: 20px;
    color: var(--secondary-text-color);
}

.tg-paginator--button {
    background-color: transparent;
    border: none;
    height: 32px;
    padding: 4px;
    color: var(--secondary-text-color);
    cursor: pointer;
}

.tg-paginator--button[disabled] {
    color: var(--disabled-text-color);
    cursor: not-allowed;
}
`);

export { Paginator };
