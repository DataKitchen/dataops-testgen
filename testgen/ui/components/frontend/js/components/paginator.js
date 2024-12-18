/**
 * @typedef Properties
 * @type {object}
 * @property {number} count
 * @property {number} pageSize
 * @property {number} pageIndex
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, loadStylesheet } from '../utils.js';

const { div, span, i, button } = van.tags;

const Paginator = (/** @type Properties */ props) => {
    loadStylesheet('paginator', stylesheet);

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(32);
    }

    const { count, pageSize } = props;
    const pageIndexState = van.state(props.pageIndex.val || 0);

    return div(
        { class: 'tg-paginator' },
        span(
            { class: 'tg-paginator--label' },
            () => {
                const pageIndex = pageIndexState.val;
                return `${pageSize.val * pageIndex + 1} - ${Math.min(count.val, pageSize.val * (pageIndex + 1))} of ${count.val}`;
            },
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => {
                    pageIndexState.val = 0;
                    changePage(pageIndexState.val);
                },
                disabled: () => pageIndexState.val === 0,
            },
            i({class: 'material-symbols-rounded'}, 'first_page')
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => {
                    pageIndexState.val--;
                    changePage(pageIndexState.val);
                },
                disabled: () => pageIndexState.val === 0,
            },
            i({class: 'material-symbols-rounded'}, 'chevron_left')
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => {
                    pageIndexState.val++;
                    changePage(pageIndexState.val);
                },
                disabled: () => pageIndexState.val === Math.ceil(count.val / pageSize.val) - 1,
            },
            i({class: 'material-symbols-rounded'}, 'chevron_right')
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => {
                    pageIndexState.val = Math.ceil(count.val / pageSize.val) - 1;
                    changePage(pageIndexState.val);
                },
                disabled: () => pageIndexState.val === Math.ceil(count.val / pageSize.val) - 1,
            },
            i({class: 'material-symbols-rounded'}, 'last_page')
        ),
    );
};

function changePage(/** @type number */page_index) {
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
    cursor: default;
}
`);

export { Paginator };
