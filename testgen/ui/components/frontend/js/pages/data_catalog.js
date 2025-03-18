/**
 * @import { Column, Table } from '../data_profiling/data_profiling_utils.js';
 * @import { TreeNode } from '../components/tree.js';
 *
 * @typedef ColumnPath
 * @type {object}
 * @property {string} column_id
 * @property {string} table_id
 * @property {string} column_name
 * @property {string} table_name
 * @property {'A' | 'B' | 'D' | 'N' | 'T' | 'X'} general_type
 * @property {string} functional_data_type
 * @property {number} drop_date
 * @property {number} table_drop_date
 * @property {boolean} critical_data_element
 * @property {boolean} table_critical_data_element
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 * @property {boolean} can_navigate
 *
 * @typedef Properties
 * @type {object}
 * @property {ColumnPath[]} columns
 * @property {Table | Column} selected
 * @property {Object.<string, string[]>} tag_values
 * @property {string} last_saved_timestamp
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { Tree } from '../components/tree.js';
import { EditableCard } from '../components/editable_card.js';
import { Attribute } from '../components/attribute.js';
import { Input } from '../components/input.js';
import { Icon } from '../components/icon.js';
import { withTooltip } from '../components/tooltip.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { ColumnDistributionCard } from '../data_profiling/column_distribution.js';
import { DataCharacteristicsCard } from '../data_profiling/data_characteristics.js';
import { PotentialPIICard, HygieneIssuesCard, TestIssuesCard } from '../data_profiling/data_issues.js';
import { getColumnIcon, TABLE_ICON, LatestProfilingTime } from '../data_profiling/data_profiling_utils.js';
import { RadioGroup } from '../components/radio_group.js';
import { Checkbox } from '../components/checkbox.js';
import { Select } from '../components/select.js';
import { capitalize } from '../display_utils.js';
import { TableSizeCard } from '../data_profiling/table_size.js';
import { Card } from '../components/card.js';
import { Button } from '../components/button.js';

const { div, h2, span, i } = van.tags;

// https://www.sam.today/blog/html5-dnd-globe-icon
const EMPTY_IMAGE = new Image(1, 1);
EMPTY_IMAGE.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==';

const TAG_KEYS = [
    'data_source',
    'source_system',
    'source_process',
    'business_domain',
    'stakeholder_group',
    'transform_level',
    'aggregation_level',
    'data_product',
];
const TAG_HELP = {
    data_source: 'Original source of the dataset',
    source_system: 'Enterprise system source for the dataset',
    source_process: 'Process, program, or data flow that produced the dataset',
    business_domain: 'Business division responsible for the dataset, e.g., Finance, Sales, Manufacturing',
    stakeholder_group: 'Data owners or stakeholders responsible for the dataset',
    transform_level: 'Data warehouse processing stage, e.g., Raw, Conformed, Processed, Reporting, or Medallion level (bronze, silver, gold)',
    aggregation_level: 'Data granularity of the dataset, e.g. atomic, historical, snapshot, aggregated, time-rollup, rolling, summary',
    data_product: 'Data domain that comprises the dataset',
};


const DataCatalog = (/** @type Properties */ props) => {
    loadStylesheet('data-catalog', stylesheet);
    Streamlit.setFrameHeight(1); // Non-zero value is needed to render
    window.frameElement.style.setProperty('height', 'calc(100vh - 175px)');
    window.testgen.isPage = true;

    /** @type TreeNode[] */
    const treeNodes = van.derive(() => {
        let columns = [];
        try {
            columns = JSON.parse(getValue(props.columns));
        } catch { }

        const tables = {};
        columns.forEach((item) => {
            const { column_id, table_id, column_name, table_name, drop_date, table_drop_date } = item;
            if (!tables[table_id]) {
                tables[table_id] = {
                    id: table_id,
                    label: table_name,
                    classes: table_drop_date ? 'text-disabled' : '',
                    ...TABLE_ICON,
                    criticalDataElement: !!item.table_critical_data_element,
                    children: [],
                };
                TAG_KEYS.forEach(key => tables[table_id][key] = item[`table_${key}`]);
            }
            const columnNode = {
                id: column_id,
                label: column_name,
                classes: drop_date ? 'text-disabled' : '',
                ...getColumnIcon(item),
                criticalDataElement: !!(item.critical_data_element ?? item.table_critical_data_element),
            };
            TAG_KEYS.forEach(key => columnNode[key] = item[key] ?? item[`table_${key}`]);
            tables[table_id].children.push(columnNode);
        });
        return Object.values(tables);
    });

    const selectedItem = van.derive(() => {
        try {
            return JSON.parse(getValue(props.selected));
        } catch (e) {
            console.error(e)
            return null;
        }
    });

    // Reset to false after saving
    const multiEditMode = van.derive(() => getValue(props.last_saved_timestamp) && false);
    const multiSelectedItems = van.state(null);

    const treeDomId = 'data-catalog-tree';
    const dragState = van.state(null);
    const dragConstraints = { min: 250, max: 600 };
    const dragResize = (/** @type Event */ event) => {
        // https://stackoverflow.com/questions/36308460/why-is-clientx-reset-to-0-on-last-drag-event-and-how-to-solve-it
        if (event.screenX && dragState.val) {
            const dragWidth = dragState.val.startWidth + event.screenX - dragState.val.startX;
            const constrainedWidth = Math.min(dragConstraints.max, Math.max(dragWidth, dragConstraints.min));
            document.getElementById(treeDomId).style.minWidth = `${constrainedWidth}px`;
        }
    };

    const filters = { criticalDataElement: van.state(false) };
    TAG_KEYS.forEach(key => filters[key] = van.state(null));

    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;

    return div(
        {
            class: 'flex-row tg-dh',
            ondragover: (event) => event.preventDefault(),
        },
        Tree(
            {
                id: treeDomId,
                classes: 'tg-dh--tree',
                nodes: treeNodes,
                // Use .rawVal, so only initial value from query params is passed to tree
                selected: selectedItem.rawVal ? `${selectedItem.rawVal.type}_${selectedItem.rawVal.id}` : null,
                onSelect: (/** @type string */ selected) => emitEvent('ItemSelected', { payload: selected }),
                multiSelect: multiEditMode,
                multiSelectToggle: userCanEdit,
                onMultiSelect: (/** @type string[] | null */ selected) => multiSelectedItems.val = selected,
                isNodeHidden: (/** @type TreeNode */ node) => {
                    let hidden = ![ node.criticalDataElement, false ].includes(filters.criticalDataElement.val);
                    hidden = hidden || TAG_KEYS.some(key => ![ node[key], null ].includes(filters[key].val));
                    return hidden;
                },
                hasActiveFilters: () => filters.criticalDataElement.val || TAG_KEYS.some(key => !!filters[key].val),
                onResetFilters: () => {
                    filters.criticalDataElement.val = false;
                    TAG_KEYS.forEach(key => filters[key].val = null);
                },
            },
            // Pass as a function that will be called when the filter portal is opened
            // Otherwise state bindings get garbage collected and Select dropdowns won't open
            // https://vanjs.org/advanced#gc
            () => div(
                Checkbox({
                    label: 'Only critical data elements (CDEs)',
                    checked: filters.criticalDataElement,
                    onChange: (checked) => filters.criticalDataElement.val = checked,
                }),
                div(
                    {
                        class: 'flex-row fx-flex-wrap fx-gap-4 fx-justify-space-between mt-4',
                        style: 'max-width: 420px;',
                    },
                    TAG_KEYS.map(key => Select({
                        id: `data-catalog-${key}`,
                        label: capitalize(key.replaceAll('_', ' ')),
                        height: 32,
                        value: filters[key],
                        options: getValue(props.tag_values)?.[key]?.map(key => ({ label: key, value: key })),
                        allowNull: true,
                        disabled: !getValue(props.tag_values)?.[key]?.length,
                        onChange: v => filters[key].val = v,
                    })),
                ),
            ),
        ),
        div(
            {
                class: 'tg-dh--dragger',
                draggable: true,
                ondragstart: (event) => {
                    event.dataTransfer.effectAllowed = 'move';
                    event.dataTransfer.setDragImage(EMPTY_IMAGE, 0, 0);
                    dragState.val = { startX: event.screenX, startWidth: document.getElementById(treeDomId).offsetWidth };
                },
                ondragend: (event) => {
                    dragResize(event);
                    dragState.val = null;
                },
                ondrag: van.derive(() => dragState.val ? dragResize : null),
            },
        ),
        () => multiEditMode.val
            ? MultiEdit(props, multiSelectedItems, multiEditMode)
            : SelectedDetails(props, selectedItem.val),
    );
};

const SelectedDetails = (/** @type Properties */ props, /** @type Table | Column */ item) => {
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;
    const userCanNavigate = getValue(props.permissions)?.can_navigate ?? false;

    return item
        ? div(
            { class: 'tg-dh--details' },
            div(
                { class: 'mb-2' },
                h2(
                    { class: 'tg-dh--title' },
                    item.type === 'column' ? [
                        span(
                            { class: 'text-secondary' },
                            `${item.table_name} > `,
                        ),
                        item.column_name,
                    ] : item.table_name,
                ),
                LatestProfilingTime({ noLinks: !userCanNavigate }, item),
            ),
            DataCharacteristicsCard({ scores: true }, item),
            item.type === 'column'
                ? ColumnDistributionCard({ dataPreview: true }, item)
                : TableSizeCard({}, item),
            TagsCard({ tagOptions: getValue(props.tag_values), editable: userCanEdit }, item),
            PotentialPIICard({ noLinks: !userCanNavigate }, item),
            HygieneIssuesCard({ noLinks: !userCanNavigate }, item),
            TestIssuesCard({ noLinks: !userCanNavigate }, item),
        )
        : EmptyState(
            'Select a table or column on the left to view its details.',
            'quick_reference_all',
        );
};

/**
* @typedef TagProperties
* @type {object}
* @property {Object.<string, string[]>} tagOptions
* @property {boolean} editable
*/
const TagsCard = (/** @type TagProperties */ props, /** @type Table | Column */ item) => {
    const title = `${item.type} Tags `;
    const attributes = [
        'description',
        'critical_data_element',
        ...TAG_KEYS,
    ].map(key => ({
        key,
        help: TAG_HELP[key],
        label: capitalize(key.replaceAll('_', ' ')),
        state: van.state(item[key]),
        inheritTableGroup: item[`table_group_${key}`] ?? null, // Table group values inherited by table or column
        inheritTable: item[`table_${key}`] ?? null, // Table values inherited by column
    }));

    const InheritedIcon = (/** @type string */ inheritedFrom) => withTooltip(
        Icon({ size: 18, classes: 'text-disabled' }, 'layers'),
        { text: `Inherited from ${inheritedFrom} tags`, position: 'top-right'},
    );
    const width = 300;
    const descriptionWidth = 932;

    const content = div(
        { class: 'flex-row fx-flex-wrap fx-gap-4' },
        attributes.map(({ key, label, help, state, inheritTable, inheritTableGroup }) => {
            let value = state.rawVal ?? inheritTable ?? inheritTableGroup;

            if (key === 'critical_data_element') {
                return span(
                    { class: 'flex-row fx-gap-1', style: `width: ${width}px` },
                    Icon(
                        { classes: value ? 'text-green' : 'text-disabled' },
                        value ? 'check_circle' : 'cancel',
                    ),
                    span(
                        { class: value ? 'text-capitalize' : 'text-secondary' },
                        value ? label : `Not a ${label}`,
                    ),
                    (item.type === 'column' && state.rawVal === null) ? InheritedIcon('table') : null,
                );
            }

            const inheritedFrom = state.rawVal !== null ? null
                : inheritTable !== null ? 'table'
                : inheritTableGroup !== null ? 'table group'
                : null;

            if (inheritedFrom && value) {
                value = span(
                    { class: 'flex-row fx-gap-1' },
                    InheritedIcon(inheritedFrom),
                    value,
                );
            }
            return Attribute({ label, help, value, width: key === 'description' ? descriptionWidth : width });
        }),
    );

    if (!props.editable) {
        return Card({ title, content });
    }

    // Define as function so the block is re-rendered with reset values when re-editing after a cancel
    const editingContent = () => div(
        { class: 'flex-row fx-flex-wrap fx-gap-4' },
        attributes.map(({ key, label, help, state, inheritTable, inheritTableGroup }) => {
            if (key === 'critical_data_element') {
                const options = [
                    { label: 'Yes', value: true },
                    { label: 'No', value: false },
                    { label: 'Inherit', value: null },
                ];
                return RadioGroup({
                    label, width, options,
                    value: state.rawVal,
                    onChange: (value) => state.val = value,
                });
            };

            return Input({
                label, help,
                width: key === 'description' ? descriptionWidth : width,
                value: state.rawVal,
                placeholder: (inheritTable || inheritTableGroup) ? `Inherited: ${inheritTable ?? inheritTableGroup}` : null,
                autocompleteOptions: props.tagOptions?.[key],
                onChange: (value) => state.val = value || null,
            });
        }),
    );

    return EditableCard({
        title: `${item.type} Tags `,
        content, editingContent,
        onSave: () => {
            const items = [{ type: item.type, id: item.id }];
            const tags = attributes.reduce((object, { key, state }) => {
                object[key] = state.rawVal;
                return object;
            }, {});
            emitEvent('TagsChanged', { payload: { items, tags } });
        },
        // Reset states to original values on cancel
        onCancel: () => attributes.forEach(({ key, state }) => state.val = item[key]),
        hasChanges: () => attributes.some(({ key, state }) => state.val !== item[key]),
    });
};

const MultiEdit = (/** @type Properties */ props, /** @type Object */ selectedItems, /** @type Object */ multiEditMode) => {
    const hasSelection = van.derive(() => selectedItems.val?.length);
    const columnCount = van.derive(() => selectedItems.val?.reduce((count, { children }) => count + children.length, 0));

    const attributes = [
        'description',
        'critical_data_element',
        ...TAG_KEYS,
    ].map(key => ({
        key,
        help: TAG_HELP[key],
        label: capitalize(key.replaceAll('_', ' ')),
        checkedState: van.state(null),
        valueState: van.state(null),
    }));

    const cdeOptions = [
        { label: 'Yes', value: true },
        { label: 'No', value: false },
        { label: 'Inherit', value: null },
    ];
    const tagOptions = getValue(props.tag_values) ?? {};
    const width = 400;
    const descriptionWidth = 800;

    return div(
        { class: 'tg-dh--details flex-column' },
        () => hasSelection.val
            ? Card({
                title: 'Edit Tags for Selection',
                actionContent: span(
                    { class: 'text-secondary mr-4' },
                    span({ style: 'font-weight: 500' }, columnCount),
                    () => ` column${columnCount.val > 1 ? 's' : ''} selected`
                ),
                content: div(
                    { class: 'flex-column' },
                    attributes.map(({ key, label, help, checkedState, valueState }) => div(
                        { class: 'flex-row fx-gap-3' },
                        Checkbox({
                            checked: checkedState,
                            onChange: (checked) => checkedState.val = checked,
                        }),
                        div(
                            {
                                class: 'pb-4 flex-row',
                                style: `min-width: ${width}px`,
                                onclick: () => checkedState.val = true,
                            },
                            key === 'critical_data_element'
                                ? RadioGroup({
                                    label, width,
                                    options: cdeOptions,
                                    onChange: (value) => valueState.val = value,
                                })
                                : Input({
                                    label, help,
                                    width: key === 'description' ? descriptionWidth : width,
                                    placeholder: () => checkedState.val ? null : '(keep current values)',
                                    autocompleteOptions: tagOptions[key],
                                    onChange: (value) => valueState.val = value || null,
                                }),
                        ),
                    )),
                    div(
                        { class: 'flex-row fx-justify-content-flex-end fx-gap-3 mt-4' },
                        Button({
                            type: 'stroked',
                            label: 'Cancel',
                            width: 'auto',
                            onclick: () => multiEditMode.val = false,
                        }),
                        Button({
                            type: 'stroked',
                            color: 'primary',
                            label: 'Save',
                            width: 'auto',
                            disabled: () => attributes.every(({ checkedState }) => !checkedState.val),
                            onclick: () => {
                                const items = selectedItems.val.reduce((array, table) => {
                                    if (table.all) {
                                        const [ type, id ] = table.id.split('_');
                                        array.push({ type, id });
                                    } else {
                                        const columns = table.children.map(column => {
                                            const [ type, id ] = column.id.split('_');
                                            return { type, id };
                                        });
                                        array.push(...columns);
                                    }
                                    return array;
                                }, []);

                                const tags = attributes.reduce((object, { key, checkedState, valueState }) => {
                                    if (checkedState.val) {
                                        object[key] = valueState.rawVal;
                                    }
                                    return object;
                                }, {});

                                emitEvent('TagsChanged', { payload: { items, tags } });
                                // Don't set multiEditMode to false here
                                // Otherwise this event gets superseded by the ItemSelected event
                                // Let the Streamlit rerun handle the state reset with 'last_saved_timestamp'
                            },
                        }),
                    ),
                ),
            })
            : EmptyState(
                'Select tables or columns on the left to edit their tags.',
                'edit_document',
            ),
    );
};

const EmptyState = (/** @type string */ message, /** @type string */ icon) => {
    return div(
        { class: 'flex-column fx-align-flex-center fx-justify-center tg-dh--no-selection' },
        Icon({ size: 80, classes: 'text-disabled mb-5' }, icon),
        span({ class: 'text-secondary' }, message),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-dh {
    height: 100%;
    align-items: stretch;
}

.tg-dh--dragger {
    min-width: 16px;
    cursor: col-resize;
}

.tg-dh--tree {
    min-width: 250px;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    background-color: var(--sidebar-background-color);
}

.tg-dh--details {
    padding-top: 8px;
    overflow: auto;
    flex-grow: 1;
}

.tg-dh--title {
    margin: 0;
    color: var(--primary-text-color);
    font-size: 20px;
    font-weight: 500;
}

.tg-dh--details > .tg-card {
    min-width: 400px;
}

.tg-dh--no-selection {
    flex: auto;
    max-height: 400px;
    padding: 16px;
}

.tg-dh--no-selection > span {
    font-size: 18px;
    text-align: center;
}
`);

export { DataCatalog };
