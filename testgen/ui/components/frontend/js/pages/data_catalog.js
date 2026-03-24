/**
 * @import { Column, Table } from '../data_profiling/data_profiling_utils.js';
 * @import { TreeNode, SelectedNode } from '/app/static/js/components/tree.js';
 * @import { FilterOption, ProjectSummary } from '../types.js';
 * 
 * @typedef ColumnPath
 * @type {object}
 * @property {string} column_id
 * @property {string} table_id
 * @property {string} column_name
 * @property {string} table_name
 * @property {'A' | 'B' | 'D' | 'N' | 'T' | 'X'} general_type
 * @property {string} functional_data_type
 * @property {number} record_ct
 * @property {number} value_ct
 * @property {string} add_date
 * @property {string} drop_date
 * @property {string} table_add_date
 * @property {string} table_drop_date
 * @property {boolean} critical_data_element
 * @property {boolean} table_critical_data_element
 * @property {boolean} excluded_data_element
 * @property {boolean} pii_flag
 * @property {string} data_source
 * @property {string} source_system
 * @property {string} source_process
 * @property {string} business_domain
 * @property {string} stakeholder_group
 * @property {string} transform_level
 * @property {string} aggregation_level
 * @property {string} data_product
 * @property {string} table_data_source
 * @property {string} table_source_system
 * @property {string} table_source_process
 * @property {string} table_business_domain
 * @property {string} table_stakeholder_group
 * @property {string} table_transform_level
 * @property {string} table_aggregation_level
 * @property {string} table_data_product
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 * @property {boolean} can_navigate
 * @property {boolean} can_view_pii
 * 
 * @typedef AutoflagSettings
 * @type {object}
 * @property {boolean} profile_flag_cdes
 * @property {boolean} profile_flag_pii
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {FilterOption[]} table_group_filter_options
 * @property {ColumnPath[]} columns
 * @property {Table | Column} selected_item
 * @property {Object.<string, string[]>} tag_values
 * @property {string} last_saved_timestamp
 * @property {Permissions} permissions
 * @property {AutoflagSettings} autoflag_settings
 * @property {object?} run_profiling_dialog
 */
import van from '/app/static/js/van.min.js';
import { Tree } from '/app/static/js/components/tree.js';
import { EditableCard } from '/app/static/js/components/editable_card.js';
import { Attribute } from '/app/static/js/components/attribute.js';
import { Input } from '/app/static/js/components/input.js';
import { Icon } from '/app/static/js/components/icon.js';
import { withTooltip } from '/app/static/js/components/tooltip.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { emitEvent, fillViewportHeight, getRandomId, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { ColumnDistributionCard } from '../data_profiling/column_distribution.js';
import { DataCharacteristicsCard } from '../data_profiling/data_characteristics.js';
import { HygieneIssuesCard, TestIssuesCard } from '../data_profiling/data_issues.js';
import { getColumnIcon, TABLE_ICON, LatestProfilingTime } from '../data_profiling/data_profiling_utils.js';
import { RadioGroup } from '/app/static/js/components/radio_group.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { Select } from '/app/static/js/components/select.js';
import { capitalize, caseInsensitiveIncludes, DISABLED_ACTION_TEXT } from '/app/static/js/display_utils.js';
import { TableSizeCard } from '../data_profiling/table_size.js';
import { Card } from '/app/static/js/components/card.js';
import { Button } from '/app/static/js/components/button.js';
import { Link } from '/app/static/js/components/link.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '/app/static/js/components/empty_state.js';
import { DropdownButton } from '/app/static/js/components/dropdown_button.js';
import { TableCreateScriptCard } from '../data_profiling/table_create_script.js';
import { MetadataTagsCard, MetadataTagsMultiEdit, TAG_KEYS } from '../data_profiling/metadata_tags.js';
import { RunProfilingDialog } from '/app/static/js/components/run_profiling_dialog.js';
import { ColumnHistoryDialog } from '../shared/column_history_dialog.js';
import { DataPreviewDialog } from '../shared/data_preview_dialog.js';

const { div, h2, span } = van.tags;

// https://www.sam.today/blog/html5-dnd-globe-icon
const EMPTY_IMAGE = new Image(1, 1);
EMPTY_IMAGE.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==';


const DataCatalog = (/** @type Properties */ props) => {
    loadStylesheet('data-catalog', stylesheet);

    /** @type TreeNode[] */
    const treeNodes = van.derive(() => {
        let columns = [];
        try {
            columns = JSON.parse(getValue(props.columns) ?? []);
        } catch { }

        const tables = {};
        columns.forEach((item) => {
            const { column_id, table_id, column_name, table_name, record_ct, value_ct, add_date, drop_date, table_add_date, table_drop_date } = item;
            if (!tables[table_id]) {
                tables[table_id] = {
                    id: table_id,
                    label: table_name,
                    classes: table_drop_date ? 'text-disabled' : (table_add_date && (Date.now() - new Date(table_add_date * 1000).getTime()) < 7 * 86400000) ? 'text-bold' : '',
                    ...TABLE_ICON,
                    iconClass: record_ct === 0 ? 'text-error' : null,
                    iconTooltip: record_ct === 0 ? 'No records detected' : null,
                    criticalDataElement: !!item.table_critical_data_element,
                    children: [],
                };
                TAG_KEYS.forEach(key => tables[table_id][key] = item[`table_${key}`]);
            }
            const columnNode = {
                id: column_id,
                label: column_name,
                classes: `column ${drop_date ? 'text-disabled' : (add_date && (Date.now() - new Date(add_date * 1000).getTime()) < 7 * 86400000) ? 'text-bold' : ''}`,
                ...getColumnIcon(item),
                iconClass: value_ct === 0 ? 'text-error' : null,
                iconTooltip: value_ct === 0 ? 'No non-null values detected' : null,
                prefix: () => {
                    const icons = [];
                    if (item.critical_data_element ?? item.table_critical_data_element) {
                        icons.push(withTooltip(Icon({ size: 15, classes: 'text-purple' }, 'star'), { text: 'Critical data element', position: 'right' }));
                    }
                    if (item.excluded_data_element) {
                        icons.push(withTooltip(Icon({ size: 15, classes: 'text-brown' }, 'visibility_off'), { text: 'Excluded data element', position: 'right' }));
                    }
                    if (item.pii_flag) {
                        icons.push(withTooltip(Icon({ size: 15, classes: 'text-orange' }, 'shield_person'), { text: 'PII data', position: 'right' }));
                    }
                    return span({ class: 'tg-dh--column-prefix' }, ...icons);
                },
                criticalDataElement: !!(item.critical_data_element ?? item.table_critical_data_element),
                excludedDataElement: !!item.excluded_data_element,
                piiFlag: !!item.pii_flag,
            };
            TAG_KEYS.forEach(key => columnNode[key] = item[key] ?? item[`table_${key}`]);
            tables[table_id].children.push(columnNode);
        });
        return Object.values(tables);
    });

    const selectedItem = van.derive(() => {
        try {
            return JSON.parse(getValue(props.selected_item));
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
            document.getElementById(treeDomId)?.style.setProperty('min-width', `${constrainedWidth}px`);
        }
    };

    const searchOptions = {
        tableName: van.state(true),
        columnName: van.state(true),
    };
    const filters = { criticalDataElement: van.state(false), piiFlag: van.state(false), showExcluded: van.state(false) };
    TAG_KEYS.forEach(key => filters[key] = van.state(null));

    // To hold temporary state within the portals, which might be discarded by clicking outside
    const tempSearchOptions = {};
    const tempFilters = {};

    const copyState = (fromObject, toObject) => {
        Object.entries(fromObject).forEach(([ key, state ]) => {
            toObject[key] = toObject[key] ?? van.state();
            toObject[key].val = state.val;
        });
    };

    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;
    const userCanNavigate = getValue(props.permissions)?.can_navigate ?? false;
    const userCanViewPii = getValue(props.permissions)?.can_view_pii ?? false;
    const projectSummary = getValue(props.project_summary);

    return projectSummary.table_group_count > 0
        ? div(
            { 'data-testid': 'data-catalog', class: 'flex-column tg-dh' },
            div(
                { class: 'flex-row fx-align-flex-end fx-justify-space-between mb-2' },
                () => Select({
                    label: 'Table Group',
                    value: getValue(props.table_group_filter_options)?.find((op) => op.selected)?.value ?? null,
                    options: getValue(props.table_group_filter_options) ?? [],
                    style: 'font-size: 14px;',
                    testId: 'table-group-filter',
                    onChange: (value) => emitEvent('TableGroupSelected', {payload: value}),
                }),
                div(
                    { class: 'flex-row fx-gap-2' },
                    userCanEdit
                        ? Button({
                            icon: 'upload',
                            type: 'stroked',
                            label: 'Import',
                            tooltip: 'Import metadata from CSV',
                            tooltipPosition: 'left',
                            width: 'fit-content',
                            style: 'background: var(--button-generic-background-color);',
                            onclick: () => emitEvent('ImportClicked', {}),
                        })
                        : null,
                    ExportOptions(treeNodes, multiSelectedItems, userCanEdit),
                ),
            ),
            () => treeNodes.val.length
                ? div(
                    {
                        class: 'flex-row tg-dh--content',
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
                            multiSelectToggleLabel: 'Edit multiple',
                            onMultiSelect: (/** @type string[] | null */ selected) => multiSelectedItems.val = selected,
                            isNodeHidden: (/** @type TreeNode */ node, /** string */ search) => search 
                                && (!caseInsensitiveIncludes(node.label, search)
                                    || (!!node.children && !searchOptions.tableName.val)
                                    || (!node.children && !searchOptions.columnName.val))
                                || ![ node.criticalDataElement, false ].includes(filters.criticalDataElement.val)
                                || ![ node.piiFlag, false ].includes(filters.piiFlag.val)
                                || (node.excludedDataElement && !filters.showExcluded.val)
                                || TAG_KEYS.some(key => ![ node[key], null ].includes(filters[key].val)),
                            onApplySearchOptions: () => {
                                copyState(tempSearchOptions, searchOptions);
                                // If both were unselected, reset their values
                                // Otherwise, nothing will be matched and the user might not realize why 
                                if (!searchOptions.tableName.val && !searchOptions.columnName.val) {
                                    searchOptions.tableName.val = true;
                                    searchOptions.columnName.val = true;
                                }
                            },
                            hasActiveFilters: () => filters.criticalDataElement.val || filters.piiFlag.val || filters.showExcluded.val || TAG_KEYS.some(key => !!filters[key].val),
                            onApplyFilters: () => copyState(tempFilters, filters),
                            onResetFilters: () => {
                                tempFilters.criticalDataElement.val = false;
                                tempFilters.piiFlag.val = false;
                                tempFilters.showExcluded.val = false;
                                TAG_KEYS.forEach(key => tempFilters[key].val = null);
                            },
                        },
                        () => {
                            copyState(searchOptions, tempSearchOptions);
                            return div(
                                { class: 'flex-column fx-gap-2' },
                                span({ class: 'text-caption' }, 'Search by'),
                                Checkbox({
                                    label: 'Table name',
                                    checked: tempSearchOptions.tableName,
                                    onChange: (checked) => tempSearchOptions.tableName.val = checked,
                                }),
                                Checkbox({
                                    label: 'Column name',
                                    checked: tempSearchOptions.columnName,
                                    onChange: (checked) => tempSearchOptions.columnName.val = checked,
                                }),
                            );
                        },
                        // Pass as a function that will be called when the filter portal is opened
                        // Otherwise state bindings get garbage collected and Select dropdowns won't open
                        // https://vanjs.org/advanced#gc
                        () => {
                            copyState(filters, tempFilters);
                            return div(
                                div(
                                    { class: 'flex-column fx-gap-3' },
                                    Checkbox({
                                        label: span({ class: 'flex-row fx-gap-1' }, 'Only critical data elements (CDEs)', Icon({ size: 18, classes: 'text-purple' }, 'star')),
                                        checked: tempFilters.criticalDataElement,
                                        onChange: (checked) => tempFilters.criticalDataElement.val = checked,
                                    }),
                                    Checkbox({
                                        label: span({ class: 'flex-row fx-gap-1' }, 'Only PII data', Icon({ size: 18, classes: 'text-orange' }, 'shield_person')),
                                        checked: tempFilters.piiFlag,
                                        onChange: (checked) => tempFilters.piiFlag.val = checked,
                                    }),
                                    Checkbox({
                                        label: span({ class: 'flex-row fx-gap-1' }, 'Show excluded data elements (XDEs)', Icon({ size: 18, classes: 'text-brown' }, 'visibility_off')),
                                        checked: tempFilters.showExcluded,
                                        onChange: (checked) => tempFilters.showExcluded.val = checked,
                                    }),
                                ),
                                div(
                                    {
                                        class: 'flex-row fx-flex-wrap fx-gap-4 fx-justify-space-between mt-4',
                                        style: 'max-width: 420px;',
                                    },
                                    TAG_KEYS.map(key => Select({
                                        id: `data-catalog-${key}`,
                                        label: capitalize(key.replaceAll('_', ' ')),
                                        height: 32,
                                        value: tempFilters[key],
                                        options: getValue(props.tag_values)?.[key]?.map(key => ({ label: key, value: key })),
                                        allowNull: true,
                                        disabled: !getValue(props.tag_values)?.[key]?.length,
                                        onChange: (value) => tempFilters[key].val = value,
                                    })),
                                ),
                            );
                        },
                    ),
                    div(
                        {
                            class: 'tg-dh--dragger',
                            draggable: true,
                            ondragstart: (event) => {
                                event.dataTransfer.effectAllowed = 'move';
                                event.dataTransfer.setDragImage(EMPTY_IMAGE, 0, 0);
                                const treeEl = document.getElementById(treeDomId);
                                dragState.val = { startX: event.screenX, startWidth: treeEl ? treeEl.offsetWidth : dragConstraints.min };
                            },
                            ondragend: (event) => {
                                dragResize(event);
                                dragState.val = null;
                            },
                            ondrag: van.derive(() => dragState.val ? dragResize : null),
                        },
                    ),
                    () => multiEditMode.val
                        ? div(
                            { class: 'tg-dh--details flex-column' },
                            () => multiSelectedItems.val?.length
                                ? MetadataTagsMultiEdit(
                                    {
                                        tagOptions: getValue(props.tag_values),
                                        piiEditable: userCanViewPii,
                                        autoflagSettings: getValue(props.autoflag_settings) ?? {},
                                        onCancel: () => multiEditMode.val = false,
                                    },
                                    multiSelectedItems,
                                )
                                : ItemEmptyState(
                                    'Select tables or columns on the left to edit their tags.',
                                    'edit_document',
                                )
                        )
                        : SelectedDetails(props, selectedItem.val),
                )
                : ConditionalEmptyState(projectSummary, userCanEdit, userCanNavigate),
            () => {
                const info = getValue(props.run_profiling_dialog);
                if (!info) return div();
                return RunProfilingDialog({
                    dialog: { title: info.title ?? 'Run Profiling', open: true },
                    table_groups: info.table_groups ?? [],
                    allow_selection: info.allow_selection ?? false,
                    selected_id: info.selected_id,
                    result: info.result,
                    onClose: () => emitEvent('RunProfilingDialogClosed', {}),
                });
            },
            ColumnHistoryDialog({
                historyData: props.history_dialog,
                onClose: () => emitEvent('HistoryDialogClosed', {}),
                onRunSelected: (runId) => emitEvent('HistoryRunSelected', { payload: runId }),
            }),
            DataPreviewDialog({
                previewData: props.data_preview_dialog,
                onClose: () => emitEvent('DataPreviewDialogClosed', {}),
            }),
        )
        : ConditionalEmptyState(projectSummary, userCanEdit, userCanNavigate);
};

const ExportOptions = (/** @type TreeNode[] */ treeNodes, /** @type SelectedNode[] */ selectedNodes) => {
    return DropdownButton({
        icon: 'download',
        label: 'Export',
        items: () => {
            const items = [
                {
                    label: 'All columns',
                    onclick: () => emitEvent('ExportClicked', { payload: null }),
                },
                {
                    label: 'Filtered columns',
                    onclick: () => {
                        const payload = treeNodes.val.reduce((array, table) => {
                            if (!table.hidden.val) {
                                const [ type, id ] = table.id.split('_');
                                array.push({ type, id, selected: table.selected.val });

                                table.children.forEach(column => {
                                    if (!column.hidden.val) {
                                        const [ type, id ] = column.id.split('_');
                                        array.push({ type, id, selected: column.selected.val });
                                    }
                                });
                            }
                            return array;
                        }, []);
                        emitEvent('ExportClicked', { payload });
                    },
                },
            ];
            if (selectedNodes.val?.length) {
                items.push({
                    label: 'Selected columns',
                    onclick: () => {
                        const payload = selectedNodes.val.reduce((array, table) => {
                            const [ type, id ] = table.id.split('_');
                            array.push({ type, id });

                            table.children.forEach(column => {
                                const [ type, id ] = column.id.split('_');
                                array.push({ type, id });
                            });

                            return array;
                        }, []);
                        emitEvent('ExportClicked', { payload });
                    },
                });
            }
            items.push({
                label: 'Metadata CSV',
                separator: true,
                onclick: () => emitEvent('ExportCsvClicked', {}),
            });
            return items;
        },
    });
};

const SelectedDetails = (/** @type Properties */ props, /** @type Table | Column */ item) => {
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;
    const userCanNavigate = getValue(props.permissions)?.can_navigate ?? false;
    const userCanViewPii = getValue(props.permissions)?.can_view_pii ?? false;

    return item
        ? div(
            { class: 'tg-dh--details flex-column fx-gap-2' },
            div(
                { },
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
            DataCharacteristicsCard({ scores: true, allowRemove: true }, item),
            item.type === 'column'
                ? ColumnDistributionCard({ dataPreview: true, history: true }, item)
                : TableSizeCard({}, item),
            MetadataTagsCard(
                {
                    tagOptions: getValue(props.tag_values),
                    editable: userCanEdit,
                    piiEditable: userCanViewPii,
                    autoflagSettings: getValue(props.autoflag_settings) ?? {},
                },
                item,
            ),
            HygieneIssuesCard({ noLinks: !userCanNavigate }, item),
            TestIssuesCard({ noLinks: !userCanNavigate }, item),
            TestSuitesCard({ noLinks: !userCanNavigate }, item),
            item.type === 'table'
                ? TableCreateScriptCard({}, item)
                : null,
        )
        : ItemEmptyState(
            'Select a table or column on the left to view its details.',
            'quick_reference_all',
        );
};

const TestSuitesCard = (/** @type Properties */ props, /** @type Table | Column */ item) => {
    return Card({
        title: 'Related Test Suites',
        content: div(
            { class: 'flex-column fx-gap-2' },
            item.test_suites.map(({ id, name, test_count }) => div(
                { class: 'flex-row fx-gap-1' },
                props.noLinks
                    ? span(name)
                    : Link({
                        href: 'test-suites:definitions',
                        params: {
                            test_suite_id: id,
                            table_name: item.table_name,
                            column_name: item.column_name,
                            project_code: item.project_code,
                        },
                        open_new: true,
                        label: name,
                    }),
                span({ class: 'text-caption' }, `(${test_count} test definitions)`),
            ))
        ),
        actionContent: item.test_suites.length
            ? null
            : item.drop_date
            ? span({ class: 'text-secondary' }, `No test definitions for ${item.type}`)
            : span(
                { class: 'text-secondary flex-row fx-gap-1 fx-justify-content-flex-end' },
                `No test definitions yet for ${item.type}.`,
                props.noLinks
                    ? null
                    : Link({
                        href: 'test-suites',
                        params: {
                            project_code: item.project_code,
                            table_group_id: item.table_group_id,
                        },
                        open_new: true,
                        label: 'Go to Test Suites',
                        right_icon: 'chevron_right',
                    }),
            ),
    });
};

const MultiEdit = (/** @type Properties */ props, /** @type Object */ selectedItems, /** @type Object */ multiEditMode) => {
    const hasSelection = van.derive(() => selectedItems.val?.length);
    const columnCount = van.derive(() => selectedItems.val?.reduce((count, { children }) => count + children.length, 0));

    const attributes = [
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
                                    label, help, width,
                                    height: 32,
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
                                    }

                                    table.children.forEach(column => {
                                        const [ type, id ] = column.id.split('_');
                                        array.push({ type, id });
                                    });

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
            : ItemEmptyState(
                'Select tables or columns on the left to edit their tags.',
                'edit_document',
            ),
    );
};

const ItemEmptyState = (/** @type string */ message, /** @type string */ icon) => {
    return div(
        { class: 'flex-column fx-align-flex-center fx-justify-center tg-dh--no-selection' },
        Icon({ size: 80, classes: 'text-disabled mb-5' }, icon),
        span({ class: 'text-secondary' }, message),
    );
};

const ConditionalEmptyState = (
    /** @type ProjectSummary */ projectSummary,
    /** @type boolean */ userCanEdit,
    /** @type boolean */ userCanNavigate,
) => {
    let args = {
        label: 'No profiling data yet',
        message: EMPTY_STATE_MESSAGE.profiling,
        button: Button({
            icon: 'play_arrow',
            type: 'stroked',
            color: 'primary',
            label: 'Run Profiling',
            width: 'fit-content',
            style: 'margin: auto; background: var(--button-generic-background-color);',
            disabled: !userCanEdit,
            tooltip: userCanEdit ? null : DISABLED_ACTION_TEXT,
            tooltipPosition: 'bottom',
            onclick: () => emitEvent('RunProfilingClicked', {}),
        }),
    }
    if (projectSummary.connection_count <= 0) {
        args = {
            label: 'Your project is empty',
            message: EMPTY_STATE_MESSAGE.connection,
            link: {
                label: 'Go to Connections',
                href: 'connections',
                params: { project_code: projectSummary.project_code },
                disabled: !userCanNavigate,
            },
        };
    } else if (projectSummary.table_group_count <= 0) {
        args = {
            label: 'Your project is empty',
            message: EMPTY_STATE_MESSAGE.tableGroup,
            link: {
                label: 'Go to Table Groups',
                href: 'table-groups',
                params: {
                    project_code: projectSummary.project_code,
                    connection_id: projectSummary.default_connection_id,
                },
                disabled: !userCanNavigate,
            },
        };
    }
    
    return EmptyState({
        icon: 'dataset',
        ...args,
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-dh {
    height: 100%;
}

.tg-dh--content {
    min-height: 0;
    flex: auto;
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

.tg-dh--tree .tg-tree:not(.multi-select) .tg-tree--row.column {
    margin-left: -30px;
}

.tg-dh--column-prefix {
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    width: 34px;
    flex-shrink: 0;
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

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    Streamlit.enableV2(setTriggerValue);

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, DataCatalog(componentState));
        parentElement._cleanup = fillViewportHeight(parentElement);
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => {
        parentElement._cleanup?.();
        parentElement.state = null;
    };
};
