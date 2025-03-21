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
 * @property {boolean?} selected
 *
 * @typedef SelectedNode
 * @type {object}
 * @property {string} id
 * @property {boolean} all
 * @property {SelectedNode[]?} children
 *
 * @typedef Properties
 * @type {object}
 * @property {string} id
 * @property {string} classes
 * @property {TreeNode[]} nodes
 * @property {string} selected
 * @property {function(string)?} onSelect
 * @property {boolean?} multiSelect
 * @property {boolean?} multiSelectToggle
 * @property {function(SelectedNode[] | null)?} onMultiSelect
 * @property {(function(TreeNode): boolean) | null} isNodeHidden
 * @property {(function(): boolean) | null} hasActiveFilters
 * @property {function()?} onResetFilters
 */
import van from '../van.min.js';
import { getValue, loadStylesheet, getRandomId, isState } from '../utils.js';
import { Input } from './input.js';
import { Button } from './button.js';
import { Portal } from './portal.js';
import { Icon } from './icon.js';
import { Checkbox } from './checkbox.js';
import { Toggle } from './toggle.js';

const { div, h3, span } = van.tags;
const levelOffset = 14;

const Tree = (/** @type Properties */ props, /** @type any? */ filtersContent) => {
    loadStylesheet('tree', stylesheet);

    // Use only initial prop value as default and maintain internal state
    const initialSelection = props.selected?.rawVal || props.selected || null;
    const selected = van.state(initialSelection);

    const treeNodes = van.derive(() => {
        const nodes = getValue(props.nodes) || [];
        const treeSelected = initTreeState(nodes, selected.rawVal);
        if (!treeSelected) {
            selected.val = null;
        }
        return nodes;
    });

    const multiSelect = isState(props.multiSelect) ? props.multiSelect : van.state(!!props.multiSelect);
    const noMatches = van.derive(() => treeNodes.val.every(node => node.hidden.val));

    van.derive(() => {
        const onSelect = props.onSelect?.val ?? props.onSelect;
        if (!multiSelect.val && onSelect) {
            onSelect(selected.val);
        }
    });

    van.derive(() => {
        if (!multiSelect.val) {
            selectTree(treeNodes.val, false);
        }
        props.onMultiSelect(multiSelect.val ? [] : null);
    });

    return div(
        {
            id: props.id,
            class: () => `flex-column ${getValue(props.classes)}`,
        },
        Toolbar(treeNodes, props, filtersContent),
        props.multiSelectToggle
            ? div(
                { class: 'mt-1 mb-2 ml-1 text-secondary' },
                Toggle({
                    label: 'Select multiple',
                    checked: multiSelect,
                    onChange: (/** @type boolean */ checked) => multiSelect.val = checked,
                }),
            )
            : null,
        div(
            { class: 'tg-tree' },
            () => div(
                {
                    class: 'tg-tree--nodes',
                    onclick: van.derive(() => multiSelect.val ? () => props.onMultiSelect(getMultiSelection(treeNodes.val)) : null),
                },
                treeNodes.val.map(node => TreeNode(node, selected, multiSelect.val)),
            ),
        ),
        () => noMatches.val
            ? span({ class: 'tg-tree--empty mt-7 mb-7 text-secondary' }, 'No matching itens found')
            : '',
    );
};

const Toolbar = (
    /** @type { val: TreeNode[] } */ nodes,
    /** @type Properties */ props,
    /** @type any? */ filtersContent,
) => {
    const search = van.state('');
    const filterDomId = `tree-filters-${getRandomId()}`;
    const filtersOpened = van.state(false);
    const filtersActive = van.state(false);
    const isNodeHidden = (/** @type TreeNode */ node) => !node.label.includes(search.val) || props.isNodeHidden?.(node);

    return div(
        { class: 'flex-row fx-gap-1 tg-tree--actions' },
        Input({
            icon: 'search',
            clearable: true,
            onChange: (/** @type string */ value) => {
                search.val = value;
                filterTree(nodes.val, isNodeHidden);
                if (value) {
                    expandOrCollapseTree(nodes.val, true);
                }
            },
        }),
        filtersContent ? [
            div(
                { class: () => `tg-tree--filter-button ${filtersActive.val ? 'active' : ''}` },
                Button({
                    id: filterDomId,
                    type: 'icon',
                    icon: 'filter_list',
                    style: 'width: 24px; height: 24px; padding: 4px;',
                    tooltip: () => filtersActive.val ? 'Filters active' : 'Filters',
                    tooltipPosition: 'bottom',
                    onclick: () => filtersOpened.val = !filtersOpened.val,
                }),
            ),
            Portal(
                { target: filterDomId, opened: filtersOpened },
                () => div(
                    { class: 'tg-tree--filters' },
                    h3(
                        { class: 'flex-row fx-justify-space-between'},
                        'Filters',
                        Button({
                            type: 'icon',
                            icon: 'close',
                            iconSize: 22,
                            onclick: () => filtersOpened.val = false,
                        }),
                    ),
                    filtersContent,
                    div(
                        { class: 'flex-row fx-justify-space-between mt-4' },
                        Button({
                            label: 'Reset filters',
                            width: '110px',
                            disabled: () => !props.hasActiveFilters(),
                            onclick: props.onResetFilters,
                        }),
                        Button({
                            type: 'stroked',
                            color: 'primary',
                            label: 'Apply',
                            width: '80px',
                            onclick: () => {
                                filterTree(nodes.val, isNodeHidden);
                                filtersActive.val = props.hasActiveFilters();
                                filtersOpened.val = false;
                            },
                        }),
                    ),
                ),
            )
        ] : null,
        Button({
            type: 'icon',
            icon: 'expand_all',
            style: 'width: 24px; height: 24px; padding: 4px;',
            tooltip: 'Expand All',
            tooltipPosition: 'bottom',
            onclick: () => expandOrCollapseTree(nodes.val, true),
        }),
        Button({
            type: 'icon',
            icon: 'collapse_all',
            style: 'width: 24px; height: 24px; padding: 4px;',
            tooltip: 'Collapse All',
            tooltipPosition: 'bottom',
            onclick: () => expandOrCollapseTree(nodes.val, false),
        }),
    );
};

const TreeNode = (
    /** @type TreeNode */ node,
    /** @type string */ selected,
    /** @type boolean */ multiSelect,
) => {
    const hasChildren = !!node.children?.length;
    return div(
        {
            onclick: multiSelect
                ? (/** @type Event */ event) => {
                    if (hasChildren) {
                        if (!event.fromChild) {
                            // Prevent the default behavior of toggling the "checked" property - we want to control it
                            event.preventDefault();
                            selectTree(
                                node.children,
                                node.selected.val ? false : node.children.some(child => !child.hidden.val && !child.selected.val),
                            );
                        }
                        node.selected.val = node.children.every(child => child.selected.val);
                    } else {
                        node.selected.val = !node.selected.val;
                        event.fromChild = true;
                    }
                }
                : null,
        },
        div(
            {
                class: () => `tg-tree--row flex-row clickable ${node.classes || ''}
                    ${selected.val === node.id ? 'selected' : ''}
                    ${node.hidden.val ? 'hidden' : ''}`,
                style: `padding-left: ${levelOffset * node.level}px;`,
                onclick: () => selected.val = node.id,
            },
            Icon(
                {
                    classes: hasChildren ? '' : 'invisible',
                    onclick: (/** @type Event */ event) => {
                        event.stopPropagation();
                        node.expanded.val = hasChildren ? !node.expanded.val : false;
                    },
                },
                () => node.expanded.val ? 'arrow_drop_down' : 'arrow_right',
            ),
            multiSelect
                ? [
                    Checkbox({
                        checked: () => node.selected.val,
                        indeterminate: hasChildren ? () => !node.selected.val && node.children.some(({ selected }) => selected.val) : false,
                    }),
                    span({ class: 'mr-1' }),
                ]
                : null,
            node.icon ? Icon({ size: 24, classes: 'tg-tree--row-icon' }, node.icon) : null,
            node.label,
        ),
        hasChildren ? div(
            { class: () => node.expanded.val ? '' : 'hidden' },
            node.children.map(node => TreeNode(node, selected, multiSelect)),
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
        node.selected = van.state(false);
        treeExpanded = treeExpanded || expanded;
    });
    return treeExpanded;
};

const filterTree = (
    /** @type TreeNode[] */ nodes,
    /** @type function(TreeNode): boolean */ isNodeHidden,
) => {
    nodes.forEach(node => {
        let hidden = isNodeHidden(node);
        if (node.children) {
            filterTree(node.children, isNodeHidden);
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
};

const selectTree = (
    /** @type TreeNode[] */ nodes,
    /** @type boolean */ selected,
) => {
    nodes.forEach(node => {
        if (!selected || !node.hidden.val) {
            node.selected.val = selected;
            if (node.children) {
                selectTree(node.children, selected);
            }
        }
    });
};

/**
 * @param {TreeNode[]} nodes
 * @returns {SelectedNode[]}
 */
const getMultiSelection = (nodes) => {
    const selected = [];
    nodes.forEach(node => {
        if (node.children) {
            const selectedChildren = getMultiSelection(node.children);
            if (selectedChildren.length) {
                selected.push({
                    id: node.id,
                    all: selectedChildren.length === node.children.length,
                    children: selectedChildren,
                });
            }
        } else if (node.selected.val) {
            selected.push({ id: node.id });
        }
    });
    return selected;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-tree {
    overflow: auto;
}

.tg-tree--empty {
    text-align: center;
}

.tg-tree--actions {
    margin: 4px;
}

.tg-tree--actions > label {
    flex: auto;
}

.tg-tree--filter-button {
    position: relative;
    border-radius: 4px;
    border: 1px solid transparent;
    transition: 0.3s;
}

.tg-tree--filter-button.active {
    border-color: var(--primary-color);
}

.tg-tree--filters {
    border-radius: 8px;
    background: var(--dk-card-background);
    box-shadow: var(--portal-box-shadow);
    padding: 16px;
    overflow: visible;
    z-index: 99;
}

.tg-tree--filters > h3 {
    margin: 0 0 12px;
    font-size: 18px;
    font-weight: 500;
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
