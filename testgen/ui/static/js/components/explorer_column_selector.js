/**
 * @typedef FilterValue
 * @type {object}
 * @property {string} field
 * @property {string} value
 * @property {Array<FilterValue>?} others
 * 
 * @typedef Selection
 * @type {Array<FilterValue>}
 * 
 * @typedef Column
 * @type {object}
 * @property {string} name
 * @property {string} table
 * @property {string} table_group
 * @property {boolean?} selected
 * 
 * @typedef Properties
 * @type {object}
 * @property {Array<Column>} columns
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, isEqual, loadStylesheet, slugify } from '../utils.js';
import { Tree } from './tree.js';
import { Icon } from './icon.js';
import { Button } from './button.js';

const { div, i, span } = van.tags;
const tableGroupFieldName = 'table_groups_name';
const tableFieldName = 'table_name';
const columnFieldName = 'column_name';

const TRANSLATIONS = {
    table_groups_name: 'Table Group',
    table_name: 'Table',
    column_name: 'Column',
};

const ColumnSelector = (/** @type Properties */ props) => {
    loadStylesheet('column-selector', stylesheet);

    window.testgen.isPage = true;
    Streamlit.setFrameHeight(400);

    const initialSelection = van.state([]);
    const selection = van.state([]);
    const valueById = van.state({});
    const treeNodes = van.state([]);
    const changed = van.derive(() => {
        const current = selection.val;
        const initial = initialSelection.val;
        return !isEqual(current, initial);
    });

    van.derive(() => {
        const initialization = initlialize(getValue(props.columns) ?? []);

        valueById.val = initialization.valueById;
        treeNodes.val = initialization.treeNodes;
        selection.val = initialization.selection;
        initialSelection.val = initialization.selection;
    });

    return div(
        {class: 'flex-column fx-gap-2 column-selector-wrapper'},
        div(
            {class: 'flex-row column-selector'},
            Tree({
                id: 'column-selector-tree',
                classes: 'column-selector--tree',
                multiSelect: true,
                onMultiSelect: (selected) => {
                    if (!selected) {
                        selection.val = [];
                        return;
                    }
    
                    selection.val = getSelectionFromTreeNodes(selected, getValue(valueById));
                },
                nodes: treeNodes,
            }),
            span({class: 'column-selector--divider'}),
            () => {
                const selection_ = getValue(selection);
                return div(
                    {class: 'flex-row fx-flex-wrap fx-align-flex-start fx-flex-align-content fx-gap-2 column-selector--selected'},
                    selection_.map((item) => ColumnFilter(item)),
                );
            },
        ),
        div(
            {class: 'flex-row fx-justify-content-flex-end'},
            Button({
                type: 'stroked',
                color: 'primary',
                label: 'Apply',
                width: 'auto',
                disabled: van.derive(() => !changed.val),
                onclick: () => emitEvent('ColumnFiltersUpdated', {payload: selection.val}),
            }),
        )
    );
};

function initlialize(/** @type Array<Column> */ columns) {
    const valueById = {};
    const treeNodesMapping = {};

    for (const columnObject of columns) {
        const tableGroup = slugify(columnObject.table_group);
        const table = slugify(columnObject.table);
        const column = slugify(columnObject.name);

        const tableGroupId = `${tableGroupFieldName}:${tableGroup}`
        const tableId =  `${tableFieldName}:${tableGroup}:${table}`
        const columnId =  `${columnFieldName}:${tableGroup}:${table}:${column}`

        valueById[tableGroupId] = columnObject.table_group;
        valueById[tableId] = columnObject.table;
        valueById[columnId] = columnObject.name;

        treeNodesMapping[tableGroupId] = treeNodesMapping[tableGroupId] ?? {
            id: tableGroupId,
            label: columnObject.table_group,
            icon: 'dataset',
            selected: false,
            children: {},
        };
        treeNodesMapping[tableGroupId].children[tableId] = treeNodesMapping[tableGroupId].children[tableId] ?? {
            id: tableId,
            label: columnObject.table,
            icon: 'table',
            selected: false,
            children: {},
        };
        treeNodesMapping[tableGroupId].children[tableId].children[columnId] = {
            id: columnId,
            label: columnObject.name,
            icon: 'abc',
            selected: columnObject.selected ?? false,
        };
    }

    const treeNodes = Object.values(treeNodesMapping);
    for (const tableGroup of treeNodes) {
        tableGroup.children = Object.values(tableGroup.children);
        for (const table of tableGroup.children) {
            table.children = Object.values(table.children);
            table.selected = table.children.every(child => child.selected);
        }
        tableGroup.selected = tableGroup.children.every(child => child.selected);
    }

    return { treeNodes, valueById, selection: getSelectionFromTreeNodes(treeNodes, valueById) };
}

function getSelectionFromTreeNodes(treeNodes, valueById) {
    if (!treeNodes || treeNodes.length === 0) {
        return [];
    }

    const selection = [];
    const isFromUserAction = treeNodes[0].all !== undefined;
    const propertyToCheck = isFromUserAction ? 'all' : 'selected';
    for (const tableGroup of treeNodes) {
        if (tableGroup[propertyToCheck]) {
            selection.push({field: tableGroupFieldName, value: valueById[tableGroup.id]});
            continue;
        }

        for (const table of tableGroup.children) {
            if (table[propertyToCheck]) {
                selection.push({
                    field: tableFieldName,
                    value: valueById[table.id],
                    others: [
                        {field: tableGroupFieldName, value: valueById[tableGroup.id]},
                    ],
                });
                continue;
            }

            for (const column of table.children) {
                if (isFromUserAction || column.selected) {
                    selection.push({
                        field: columnFieldName,
                        value: valueById[column.id],
                        others: [
                            {field: tableFieldName, value: valueById[table.id]},
                            {field: tableGroupFieldName, value: valueById[tableGroup.id]},
                        ],
                    });
                }
            }
        }
    }

    return selection;
}

const ColumnFilter = (
    /** @type FilterValue */ filter,
) => {
    const expanded = van.state(false);
    const expandIcon = van.derive(() => expanded.val ? 'keyboard_arrow_up' : 'keyboard_arrow_down');

    return div(
        {
            class: 'flex-row column-selector--filter',
            'data-testid': 'column-selector-filter',
            style: 'background: var(--form-field-color); border-radius: 8px; padding: 8px 12px;',
        },
        div(
            {class: 'flex-column'},
            div(
                { class: 'flex-row', 'data-testid': 'column-selector-filter' },
                span({ class: 'text-secondary mr-1', 'data-testid': 'column-selector-filter-label' }, `${TRANSLATIONS[filter.field] ?? filter.field} =`),
                span({'data-testid': 'column-selector-filter-value'}, filter.value),
            ),
            () => {
                const expanded_ = getValue(expanded);
                if (!expanded_) {
                    return '';
                }
    
                return div(
                    {class: 'flex-column', 'data-testid': 'column-selector-filter-others'},
                    filter.others.map((item) => ColumnFilterLine(item.field, item.value)),
                );
            },
        ),
        filter.others?.length > 0
            ? Icon(
                {
                    size: 16,
                    classes: 'clickable text-secondary ml-1',
                    'data-testid': 'column-selector-filter-expand',
                    onclick: () => expanded.val = !expanded.val,
                },
                expandIcon,
            )
            : '',
    );
};

const ColumnFilterLine = (/** @type string */ field, /** @type string */ value) => {
    return div(
        { class: 'flex-row', 'data-testid': 'column-selector-filter' },
        span({ class: 'text-secondary mr-1', 'data-testid': 'column-selector-filter-label' }, `${TRANSLATIONS[field] ?? field} =`),
        span({'data-testid': 'column-selector-filter-value'}, value),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.column-selector-wrapper {
    height: 100%;
    overflow-y: hidden;
}

.column-selector {
    height: calc(100% - 48px);
    align-items: stretch;
}

.column-selector--tree {
    flex: 1;
}

.column-selector--divider {
    width: 1px;
    background-color: var(--grey);
    margin: 0 10px;
}

.column-selector--selected {
    flex: 2;
    overflow-y: auto;
}
`);

export { ColumnSelector, ColumnFilter };
