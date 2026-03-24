/**
 * @typedef {Object} TabProps
 * @property {string} label
 */
import { getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';

const { div, button, span } = van.tags;

/**
 * @param {TabProps} props
 * @param {...any} children
 * @returns {{label: string, children: van.ChildDom[]}}
 */
const Tab = ({ label }, ...children) => ({
    label,
    children,
});

/**
 * @typedef {Object} TabsProps
 * @property {string?} testId
 * @property {string?} class
 *
 * @param {TabsProps} props
 * @param {...Tab} tabs
 */
const Tabs = (props, ...tabs) => {
    loadStylesheet('tabs', stylesheet);

    const { testId: testIdProp, ...restProps } = props;
    const testId = getValue(testIdProp) ?? '';

    const activeTab = van.state(0);

    let labelsContainerEl;
    const highlightEl = span({ class: "tg-tabs--highlight" });

    const updateHighlight = () => {
        if (!labelsContainerEl?.isConnected || !labelsContainerEl.children.length) return;

        const activeLabel = labelsContainerEl.children[activeTab.val];
        if (!activeLabel) return;

        highlightEl.style.width = `${activeLabel.offsetWidth}px`;
        highlightEl.style.left = `${activeLabel.offsetLeft}px`;
        highlightEl.style.opacity = '1';
    };

    labelsContainerEl = div(
        { class: "tg-tabs--labels" },
        ...tabs.map((tab, i) =>
            button({
                class: () => `tg-tabs--tab--label ${i === activeTab.val ? 'active' : ''}`,
                'data-testid': testId ? `${testId}-tab-${i}` : '',
                onclick: () => (activeTab.val = i),
            },
            tab.label
        )),
        highlightEl,
    );

    const tabsContainerEl = div({ ...restProps, 'data-testid': testId, class: () => `${getValue(restProps.class) ?? ''} tg-tabs--container` },
        labelsContainerEl,
        div({ class: "tg-tabs--content", 'data-testid': testId ? `${testId}-panel` : '' }, () => div({class: "tg-tabs--content-inner"}, tabs[activeTab.val].children)),
    );

    van.derive(() => {
        activeTab.val; 
        requestAnimationFrame(updateHighlight);
    });

    const resizeObserver = new ResizeObserver(() => {
        requestAnimationFrame(updateHighlight);
    });

    tabsContainerEl.onadd = () => {
        resizeObserver.observe(labelsContainerEl);
        updateHighlight();
    };
    
    tabsContainerEl.onremove = () => {
        resizeObserver.disconnect();
    };
    
    return tabsContainerEl;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-tabs--container {
    width: 100%;
}

.tg-tabs--labels {
    position: relative;
    display: flex;
    border-bottom: 1px solid #dddfe2;
}

.tg-tabs--tab--label {
    padding: 12px 20px;
    cursor: pointer;
    background-color: transparent;
    border: none;
    font-size: 0.875rem;
    color: var(--secondary-text-color);
    font-weight: 500;
    transition: color 0.2s ease-in-out;
    white-space: nowrap;
}

.tg-tabs--tab--label:hover {
    color: var(--primary-color);
    border-radius: 6px 6px 0 0;
}

.tg-tabs--tab--label.active {
    color: var(--primary-color);
}

.tg-tabs--highlight {
    position: absolute;
    bottom: -1px;
    height: 2px;
    background-color: var(--primary-color);
    transition: left 0.3s cubic-bezier(0.25, 0.8, 0.25, 1), width 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
    opacity: 0;
}

.tg-tabs--content {
    padding-top: 20px;
}
`);

export { Tabs, Tab };