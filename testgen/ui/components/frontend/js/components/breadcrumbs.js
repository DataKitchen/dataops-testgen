/**
 * @typedef Breadcrumb
 * @type {object}
 * @property {string} path
 * @property {object} params
 * @property {string} label
 * 
 * @typedef Properties
 * @type {object}
 * @property {Array.<Breadcrumb>} breadcrumbs
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { loadStylesheet } from '../utils.js';

const { a, div, span } = van.tags;

const Breadcrumbs = (/** @type Properties */ props) => {
    loadStylesheet('breadcrumbs', stylesheet);

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(24);
    }

    return div(
        {class: 'tg-breadcrumbs-wrapper'},
        () => {
            const breadcrumbs = van.val(props.breadcrumbs);

            return div(
                { class: 'tg-breadcrumbs' },
                breadcrumbs.reduce((items, b, idx) => {
                    const isLastItem = idx === breadcrumbs.length - 1;
                    items.push(a({ class: `tg-breadcrumbs--${ isLastItem ? 'current' : 'active'}`, href: `#/${b.path}`, onclick: () => emiEvent(b.path, b.params) }, b.label))
                    if (!isLastItem) {
                        items.push(span({class: 'tg-breadcrumbs--arrow'}, '>'));
                    }
                    return items;
                }, [])
            );
        }
    )
};

function emiEvent(/** @type string */ href, /** @type object */ params) {
    Streamlit.sendData({ event: 'LinkClicked', href, params });
    return false;
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-breadcrumbs-wrapper {
    height: 100%;
}

.tg-breadcrumbs {
    display: flex;
    align-items: center;
    color: var(--secondary-text-color);
    height: 100%;
}

.tg-breadcrumbs > a {
    text-decoration: unset;
}

.tg-breadcrumbs--arrow {
    margin-left: 4px;
    margin-right: 4px;
}

.tg-breadcrumbs--active {
    cursor: pointer;
    color: var(--secondary-text-color);
}

.tg-breadcrumbs--active:hover {
    text-decoration: underline;
}

.tg-breadcrumbs--current {
    pointer-events: none;
    color: var(--secondary-text-color);
}
`);

export { Breadcrumbs };
