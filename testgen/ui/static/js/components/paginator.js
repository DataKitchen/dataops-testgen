/**
 * @typedef Properties
 * @type {object}
 * @property {number} count
 * @property {number} pageSize
 * @property {number?} pageIndex
 * @property {function(number)?} onChange
 */

import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { div, span, i, button } = van.tags;

const Paginator = (/** @type Properties */ props) => {
    const emit = props.emit;
    loadStylesheet('paginator', stylesheet);

    const { count, pageSize } = props;
    const pageIndexState = van.derive(() => getValue(props.pageIndex) ?? 0);

    van.derive(() => {
        const onChange = props.onChange?.val ?? props.onChange ?? changePage;
        onChange(pageIndexState.val);
    });

    return div(
        { class: 'tg-paginator', 'data-testid': 'paginator' },
        span(
            { class: 'tg-paginator--label', 'data-testid': 'paginator-info' },
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
                'aria-label': 'First page',
                onclick: () => pageIndexState.val = 0,
                disabled: () => pageIndexState.val === 0,
            },
            i({class: 'material-symbols-rounded'}, 'first_page')
        ),
        button(
            {
                class: 'tg-paginator--button',
                'aria-label': 'Previous page',
                onclick: () => pageIndexState.val--,
                disabled: () => pageIndexState.val === 0,
            },
            i({class: 'material-symbols-rounded'}, 'chevron_left')
        ),
        button(
            {
                class: 'tg-paginator--button',
                'aria-label': 'Next page',
                onclick: () => pageIndexState.val++,
                disabled: () => pageIndexState.val === Math.ceil(getValue(count) / getValue(pageSize)) - 1,
            },
            i({class: 'material-symbols-rounded'}, 'chevron_right')
        ),
        button(
            {
                class: 'tg-paginator--button',
                'aria-label': 'Last page',
                onclick: () => pageIndexState.val = Math.ceil(getValue(count) / getValue(pageSize)) - 1,
                disabled: () => pageIndexState.val === Math.ceil(getValue(count) / getValue(pageSize)) - 1,
            },
            i({class: 'material-symbols-rounded'}, 'last_page')
        ),
    );
};

function changePage(/** @type number */ page_index) {
    emit('PageChanged', { page_index })
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
