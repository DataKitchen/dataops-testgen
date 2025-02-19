/**
 * @import { Column, Table } from '../data_profiling/data_profiling_utils.js';
 *
 * @typedef ColumnPath
 * @type {object}
 * @property {string} column_id
 * @property {string} table_id
 * @property {string} column_name
 * @property {string} table_name
 * @property {'A' | 'B' | 'D' | 'N' | 'T' | 'X'} general_type
 * @property {string} functional_data_type
 * @property {number} column_drop_date
 * @property {number} table_drop_date
 *
 * @typedef Properties
 * @type {object}
 * @property {ColumnPath[]} columns
 * @property {Table | Column} selected
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
import { getColumnIcon, TABLE_ICON, LatestProfilingLink } from '../data_profiling/data_profiling_utils.js';
import { RadioGroup } from '../components/radio_group.js';

const { div, h2, span, i } = van.tags;

// https://www.sam.today/blog/html5-dnd-globe-icon
const EMPTY_IMAGE = new Image(1, 1);
EMPTY_IMAGE.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==';

const DataCatalog = (/** @type Properties */ props) => {
    loadStylesheet('data-catalog', stylesheet);
    Streamlit.setFrameHeight(1); // Non-zero value is needed to render
    window.frameElement.style.setProperty('height', 'calc(100vh - 175px)');
    window.testgen.isPage = true;

    const treeNodes = van.derive(() => {
        let columns = [];
        try {
            columns = JSON.parse(getValue(props.columns));
        } catch { }

        const tables = {};
        columns.forEach((item) => {
            const { column_id, table_id, column_name, table_name, column_drop_date, table_drop_date } = item;
            if (!tables[table_id]) {
                tables[table_id] = {
                    id: table_id,
                    label: table_name,
                    classes: table_drop_date ? 'text-disabled' : '',
                    ...TABLE_ICON,
                    children: [],
                };
            }
            tables[table_id].children.push({
                id: column_id,
                label: column_name,
                classes: column_drop_date ? 'text-disabled' : '',
                ...getColumnIcon(item),
            });
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

    const treeDomId = 'data-catalog-tree';
    const dragState = van.state(null);
    const dragConstraints = { min: 250, max: 600 };
    const dragResize = (event) => {
        // https://stackoverflow.com/questions/36308460/why-is-clientx-reset-to-0-on-last-drag-event-and-how-to-solve-it
        if (event.screenX && dragState.val) {
            const dragWidth = dragState.val.startWidth + event.screenX - dragState.val.startX;
            const constrainedWidth = Math.min(dragConstraints.max, Math.max(dragWidth, dragConstraints.min));
            document.getElementById(treeDomId).style.minWidth = `${constrainedWidth}px`;
        }
    };

    return div(
        {
            class: 'flex-row tg-dh',
            ondragover: (event) => event.preventDefault(),
        },
        Tree({
            id: treeDomId,
            nodes: treeNodes,
            // Use .rawVal, so only initial value from query params is passed to tree
            selected: selectedItem.rawVal ? `${selectedItem.rawVal.type}_${selectedItem.rawVal.id}` : null,
            classes: 'tg-dh--tree',
        }),
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
        () => {
            const item = selectedItem.val;
            if (item) {
                return div(
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
                        LatestProfilingLink(item),
                    ),
                    DataCharacteristicsCard({ scores: true }, item),
                    item.type === 'column' ? ColumnDistributionCard({}, item) : null,
                    TagsCard({}, item),
                    PotentialPIICard({}, item),
                    HygieneIssuesCard({}, item),
                    TestIssuesCard({}, item),
                );
            }

            return div(
                { class: 'flex-column fx-align-flex-center fx-justify-center tg-dh--no-selection' },
                i(
                    { class: 'material-symbols-rounded text-disabled mb-5' },
                    'quick_reference_all',
                ),
                span(
                    { class: 'text-secondary' },
                    'Select a table or column on the left to view its details.',
                ),
            );
        },
    );
};

const TagsCard = (/** @type object */ _props, /** @type Table | Column */ item) => {
    const attributes = [
        { key: 'description' },
        { key: 'critical_data_element' },
        { key: 'data_source', help: 'Original source of the dataset' },
        { key: 'source_system', help: 'Enterprise system source for the dataset' },
        { key: 'source_process', help: 'Process, program, or data flow that produced the dataset' },
        { key: 'business_domain', help: 'Business division responsible for the dataset, e.g., Finance, Sales, Manufacturing' },
        { key: 'stakeholder_group', help: 'Data owners or stakeholders responsible for the dataset' },
        { key: 'transform_level', help: 'Data warehouse processing stage, e.g., Raw, Conformed, Processed, Reporting, or Medallion level (bronze, silver, gold)' },
        { key: 'aggregation_level', help: 'Data granularity of the dataset, e.g. atomic, historical, snapshot, aggregated, time-rollup, rolling, summary' },
        { key: 'data_product', help: 'Data domain that comprises the dataset' },
    ].map(attribute => ({
        ...attribute,
        label: attribute.key.replaceAll('_', ' '),
        state: van.state(item[attribute.key]),
        inherited: item[`table_${attribute.key}`], // Table values inherited by column
    }));

    const InheritedIcon = () => withTooltip(
        Icon({ size: 18, classes: 'text-disabled' }, 'layers'),
        { text: 'Inherited from table tags', position: 'top-right'},
    );
    const width = 300;
    const descriptionWidth = 932;

    const content = div(
        { class: 'flex-row fx-flex-wrap fx-gap-4' },
        attributes.map(({ key, label, help, state, inherited }) => {
            let value = state.rawVal ?? inherited;
            const isInherited = item.type === 'column' && state.rawVal === null;

            if (key === 'critical_data_element') {
                return span(
                    { class: 'flex-row fx-gap-1', style: `width: ${width}px` },
                    i(
                        { class: `material-symbols-rounded ${value ? 'text-green' : 'text-disabled'}` },
                        value ? 'check_circle' : 'cancel',
                    ),
                    span(
                        { class: value ? 'text-capitalize' : 'text-secondary' },
                        value ? label : `Not a ${label}`,
                    ),
                    isInherited ? InheritedIcon() : null,
                );
            }

            if (isInherited && value) {
                value = span(
                    { class: 'flex-row fx-gap-1' },
                    InheritedIcon(),
                    value,
                );
            }
            return Attribute({ label, help, value, width: key === 'description' ? descriptionWidth : width });
        }),
    );

    // Define as function so the block is re-rendered with reset values when re-editing after a cancel
    const editingContent = () => div(
        { class: 'flex-row fx-flex-wrap fx-gap-4' },
        attributes.map(({ key, label, help, state, inherited }) => {
            if (key === 'critical_data_element') {
                const options = [
                    { label: 'Yes', value: true },
                    { label: 'No', value: false },
                ];
                if (item.type === 'column') {
                    options.push({ label: 'Inherit', value: null });
                }
                return RadioGroup({
                    label, width, options,
                    value: item.type === 'column' ? state.rawVal : !!state.rawVal, // Coerce null to false for tables
                    onChange: (value) => state.val = value,
                });
            };

            return Input({
                label, help,
                width: key === 'description' ? descriptionWidth : width,
                value: state.rawVal,
                placeholder: inherited ? `Inherited: ${inherited}` : null,
                style: 'text-transform: capitalize;',
                onChange: (value) => state.val = value || null,
            });
        }),
    );

    return EditableCard({
        title: `${item.type} Tags `,
        content, editingContent,
        onSave: () => {
            const payload = attributes.reduce((object, { key, state }) => {
                object[key] = state.rawVal;
                return object;
            }, { id: item.id, type: item.type });
            emitEvent('TagsChanged', { payload })
        },
        // Reset states to original values on cancel
        onCancel: () => attributes.forEach(({ key, state }) => state.val = item[key]),
        hasChanges: () => attributes.some(({ key, state }) => state.val !== item[key]),
    });
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

.tg-dh--no-selection > i {
    font-size: 80px;
}

.tg-dh--no-selection > span {
    font-size: 18px;
    text-align: center;
}
`);

export { DataCatalog };
