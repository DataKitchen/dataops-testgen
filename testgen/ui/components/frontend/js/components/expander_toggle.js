/**
 * @typedef Properties
 * @type {object}
 * @property {boolean} default
 * @property {string} expandLabel
 * @property {string} collapseLabel
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';

const { div, span, i } = van.tags;

const ExpanderToggle = (/** @type Properties */ props) => {
    Streamlit.setFrameHeight(24);

    if (!window.testgen.loadedStylesheets.expanderToggle) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets.expanderToggle = true;
    }

    const expandedState = van.state(!!props.default.val);
    const expandLabel = props.expandLabel.val || 'Expand';
    const collapseLabel = props.collapseLabel.val || 'Collapse';
    
    return div(
        {
            class: 'expander-toggle',
            onclick: () => {
                expandedState.val = !expandedState.val;
                Streamlit.sendData(expandedState.val);
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
