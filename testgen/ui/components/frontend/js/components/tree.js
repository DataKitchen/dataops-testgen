/**
 * @typedef TreeNode
 * @type {object}
 * @property {string} id
 * @property {string} label
 * @property {string?} classes
 * @property {string?} icon
 * @property {number?} iconSize
 * @property {TreeNode[]?} children
 * @property {number?} level
 * @property {boolean?} expanded
 * @property {boolean?} hidden
 * 
 * @typedef Properties
 * @type {object}
 * @property {TreeNode[]} nodes
 * @property {string} selected
 * @property {string} classes
 */
import van from '../van.min.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { Input } from './input.js';
import { Button } from './button.js';

const { div, i } = van.tags;
const levelOffset = 14;

const Tree = (/** @type Properties */ props) => {
    loadStylesheet('tree', stylesheet);

    // Use only initial prop value as default and maintain internal state
    const initialSelection = props.selected?.rawVal || props.selected || null;
    const selected = van.state(initialSelection);

    const treeNodes = van.derive(() => {
        const nodes = getValue(props.nodes) || [];
        const treeSelected = initTreeState(nodes, initialSelection);
        if (!treeSelected) {
            selected.val = null;
        }
        return nodes;
    });

    return div(
        { class: () => `flex-column ${getValue(props.classes)}` },
        div(
            { class: 'flex-row fx-gap-1 tg-tree--actions' },
            Input({
                icon: 'search',
                clearable: true,
                onChange: (value) => searchTree(treeNodes.val, value),
            }),
            Button({
                type: 'icon',
                icon: 'expand_all',
                style: 'width: 24px; height: 24px; padding: 4px;',
                tooltip: 'Expand All',
                tooltipPosition: 'bottom',
                onclick: () => expandOrCollapseTree(treeNodes.val, true),
            }),
            Button({
                type: 'icon',
                icon: 'collapse_all',
                style: 'width: 24px; height: 24px; padding: 4px;',
                tooltip: 'Collapse All',
                tooltipPosition: 'bottom',
                onclick: () => expandOrCollapseTree(treeNodes.val, false),
            }),
        ),
        div(
            { class: 'tg-tree' },
            () => div(
                { class: 'tg-tree--nodes' },
                treeNodes.val.map(node => TreeNode(node, selected)),
            ),
        ),
    );
};

const TreeNode = (
    /** @type TreeNode */ node,
    /** @type string */ selected,
) => {
    const hasChildren = !!node.children?.length;
    return div(
        div(
            {
                class: () => `tg-tree--row flex-row clickable ${node.classes || ''}
                    ${selected.val === node.id ? 'selected' : ''}
                    ${node.hidden.val ? 'hidden' : ''}`,
                style: `padding-left: ${levelOffset * node.level}px;`,
                onclick: () => {
                    selected.val = node.id;
                    emitEvent('TreeNodeSelected', { payload: node.id });
                },
            },
            i(
                {
                    class: `material-symbols-rounded text-secondary ${hasChildren ? '' : 'invisible'}`,
                    onclick: () => {
                        node.expanded.val = hasChildren ? !node.expanded.val : false;
                    },
                },
                () => node.expanded.val ? 'arrow_drop_down' : 'arrow_right',
            ),
            node.icon ? i(
                {
                    class: 'material-symbols-rounded tg-tree--row-icon',
                    style: `font-size: ${node.iconSize || 24}px;`,
                },
                node.icon,
            ) : null,
            node.label,
        ),
        hasChildren ? div(
            { class: () => node.expanded.val ? '' : 'hidden' },
            node.children.map(node => TreeNode(node, selected)),
        ) : null,
    );
};

const initTreeState = (
    /** @type TreeNode[] */ nodes,
    /** @type string */ selected,
    /** @type number */ level = 0,
) => {
    let treeExpanded = false;
    nodes.forEach(node => {
        node.level = level;
        // Expand node if it is initial selection
        let expanded = node.id === selected;
        if (node.children) {
            // Expand node if initial selection is a descendent
            expanded = initTreeState(node.children, selected, level + 1) || expanded;
        }
        node.expanded = van.state(expanded);
        node.hidden = van.state(false);
        treeExpanded = treeExpanded || expanded;
    });
    return treeExpanded;
};

const searchTree = (
    /** @type TreeNode[] */ nodes,
    /** @type string */ search,
) => {
    nodes.forEach(node => {
        let hidden = !node.label.includes(search);
        if (node.children) {
            searchTree(node.children, search);
            hidden = hidden && node.children.every(child => child.hidden.rawVal);
        }
        node.hidden.val = hidden;
    });
};

const expandOrCollapseTree = (
    /** @type TreeNode[] */ nodes,
    /** @type boolean */ expanded,
) => {
    nodes.forEach(node => {
        if (node.children) {
            expandOrCollapseTree(node.children, expanded);
            node.expanded.val = expanded;
        }
    });
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-tree {
    overflow: auto;
}

.tg-tree--actions {
    margin: 4px;
}

.tg-tree--nodes {
    width: fit-content;
    min-width: 100%;
}

.tg-tree--row {
    box-sizing: border-box;
    width: auto;
    min-width: fit-content;
    border: solid transparent;
    border-width: 1px 0;
    padding-right: 8px;
    transition: background-color 0.3s;
}

.tg-tree--row:hover {
    background-color: var(--sidebar-item-hover-color);
}

.tg-tree--row.selected {
    background-color: #06a04a17;
    font-weight: 500;
}

.tg-tree--row-icon {
    margin-right: 4px;
    width: 24px;
    color: #B0BEC5;
    text-align: center;
}
`);

export { Tree };
