/**
 * @typedef Properties
 * @type {object}
 * @property {number} count
 * @property {number} pageSize
 * @property {number} pageIndex
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';

const { div, span, i, button } = van.tags;

const Paginator = (/** @type Properties */ props) => {
    const count = props.count.val;
    const pageSize = props.pageSize.val;

    Streamlit.setFrameHeight(32);

    if (!window.testgen.loadedStylesheets.expanderToggle) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets.expanderToggle = true;
    }

    const pageIndexState = van.state(props.pageIndex.val || 0);

    return div(
        { class: 'tg-paginator' },
        span(
            { class: 'tg-paginator--label' },
            () => {
                const pageIndex = pageIndexState.val;
                return `${pageSize * pageIndex + 1} - ${Math.min(count, pageSize * (pageIndex + 1))} of ${count}`
            },
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => {
                    pageIndexState.val = 0;
                    Streamlit.sendData(pageIndexState.val);
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
                    Streamlit.sendData(pageIndexState.val);
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
                    Streamlit.sendData(pageIndexState.val);
                },
                disabled: () => pageIndexState.val === Math.ceil(count / pageSize) - 1,
            },
            i({class: 'material-symbols-rounded'}, 'chevron_right')
        ),
        button(
            {
                class: 'tg-paginator--button',
                onclick: () => {
                    pageIndexState.val = Math.ceil(count / pageSize) - 1;
                    Streamlit.sendData(pageIndexState.val);
                },
                disabled: () => pageIndexState.val === Math.ceil(count / pageSize) - 1,
            },
            i({class: 'material-symbols-rounded'}, 'last_page')
        ),
    );
};

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
