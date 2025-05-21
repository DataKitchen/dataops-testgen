/**
 * @typedef Properties
 * @type {object}
 * @property {boolean} default
 * @property {string?} expandLabel
 * @property {string?} collapseLabel
 * @property {string?} style
 * @property {Function?} onExpand
 * @property {Function?} onCollapse
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { getValue, loadStylesheet } from '../utils.js';

const { div, span, i } = van.tags;

const ExpanderToggle = (/** @type Properties */ props) => {
    loadStylesheet('expanderToggle', stylesheet);

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(24);
    }

    const expandedState = van.state(!!getValue(props.default));
    const expandLabel = getValue(props.expandLabel) || 'Expand';
    const collapseLabel = getValue(props.collapseLabel) || 'Collapse';

    return div(
        {
            class: 'expander-toggle',
            style: () => getValue(props.style) ?? '',
            onclick: () => {
                expandedState.val = !expandedState.val;
                const handler = (expandedState.val ? props.onExpand : props.onCollapse) ?? Streamlit.sendData;
                handler(expandedState.val);
            }
        },
        span(
            { class: 'expander-toggle--label' },
            () => expandedState.val ? collapseLabel : expandLabel,
        ),
        i(
            { class: 'material-symbols-rounded' },
            () => expandedState.val ? 'keyboard_arrow_up' : 'keyboard_arrow_down',
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.expander-toggle {
    display: flex;
    flex-flow: row nowrap;
    justify-content: flex-end;
    align-items: center;
    cursor: pointer;
    color: #1976d2;
}
`);

export { ExpanderToggle };
