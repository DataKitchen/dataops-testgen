/**
 * @typedef Properties
 * @type {object}
 * @property {boolean} default
 * @property {string?} expandLabel
 * @property {string?} collapseLabel
 * @property {string?} style
 * @property {'left'|'right'?} labelPosition
 * @property {Function?} onExpand
 * @property {Function?} onCollapse
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';

const { div, span, i } = van.tags;

const ExpanderToggle = (/** @type Properties */ props) => {
    loadStylesheet('expanderToggle', stylesheet);

    const expandedState = van.state(!!getValue(props.default));
    const expandLabel = getValue(props.expandLabel) || 'Expand';
    const collapseLabel = getValue(props.collapseLabel) || 'Collapse';
    const labelLeft = getValue(props.labelPosition) === 'left';

    const label = span(
        { class: 'expander-toggle--label' },
        () => expandedState.val ? collapseLabel : expandLabel,
    );
    const icon = i(
        { class: 'material-symbols-rounded' },
        () => expandedState.val ? 'keyboard_arrow_up' : 'keyboard_arrow_down',
    );

    return div(
        {
            class: () => `expander-toggle${labelLeft ? ' expander-toggle--left' : ''}`,
            style: () => getValue(props.style) ?? '',
            onclick: () => {
                expandedState.val = !expandedState.val;
                const handler = expandedState.val ? props.onExpand : props.onCollapse;
                handler(expandedState.val);
            }
        },
        ...(labelLeft ? [icon, label] : [label, icon]),
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

.expander-toggle--left {
    justify-content: flex-start;
}
`);

export { ExpanderToggle };
