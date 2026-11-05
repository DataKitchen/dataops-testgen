/**
 * @typedef SchemaField
 * @type {object}
 * @property {string} label
 * @property {string?} value
 *
 * @typedef RuleDeclaration
 * @type {object}
 * @property {string} label
 * @property {string?} value
 * @property {string} test_type
 * @property {string} test_name
 *
 * @typedef SchemaColumn
 * @type {object}
 * @property {string} name - the column's physical name, which the save and the rule links match on
 * @property {string} label - the column's name, as the browser shows it
 * @property {SchemaField[]} fields
 * @property {RuleDeclaration[]} declared
 * @property {number} rule_count
 *
 * @typedef SchemaTable
 * @type {object}
 * @property {string} name
 * @property {SchemaField[]} fields
 * @property {SchemaColumn[]} columns
 * @property {number} rule_count
 *
 * @typedef Properties
 * @type {object}
 * @property {function(): SchemaTable[]} tables
 * @property {function(): SchemaTable[]} currentTables - the same, read without subscribing to them
 * @property {function(): string[]} unverifiable - the tables the table group does not hold
 * @property {function(): boolean} editable
 * @property {object} selected - VanJS state holding the selected node's id, kept across renders
 * @property {object} tableEditing - VanJS state holding whether the table form is open
 * @property {object} columnEditing - VanJS state holding whether the column form is open
 * @property {function(): object?} refusal - the refused save to show in the open form, if any
 * @property {function(): object?} warnings - the last save's warnings, with the `target` table and column it saved
 * @property {function(): object} link_params - the URL parameters naming this contract version on the
 *     test-definitions page
 * @property {function(): void} onDismiss
 * @property {function(string, object): void} onSave
 * @property {function} emit
 */
import van from '../van.min.js';
import { isEqual, loadStylesheet } from '../utils.js';
import { Alert } from './alert.js';
import { Attribute } from './attribute.js';
import { Card } from './card.js';
import { Checkbox } from './checkbox.js';
import { RefusalAlert } from './contract_section_cards.js';
import { EditableCard } from './editable_card.js';
import { Input } from './input.js';
import { Link } from './link.js';
import { Select } from './select.js';
import { Textarea } from './textarea.js';
import { Tree } from './tree.js';

const { div, span } = van.tags;

const SEPARATOR = '\u0000';
const tableId = (table) => `table${SEPARATOR}${table}`;
const columnId = (table, column) => `column${SEPARATOR}${table}${SEPARATOR}${column}`;

const ruleCountText = (count, scope) => `${count} ${count === 1 ? 'quality rule' : 'quality rules'} on this ${scope} ›`;

const LOGICAL_TYPES = ['string', 'date', 'timestamp', 'time', 'number', 'integer', 'object', 'array', 'boolean', 'map', 'vector'];
const DECLARABLE_LABELS = { required: 'Required', unique: 'Unique' };

const columnForm = (/** @type SchemaColumn */ column) => ({
    ...(column?.form ?? {}),
    examples: (column?.form?.examples ?? []).join('\n'),
});
const columnValues = (form) => ({ ...form, examples: (form.examples ?? '').split('\n') });
const comparable = (form) => Object.fromEntries(
    Object.entries(form).map(([key, value]) => [key, typeof value === 'string' ? value.trim() : (value ?? '')]),
);

const ContractSchema = (/** @type Properties */ props) => {
    loadStylesheet('contract-schema', stylesheet);
    const tableForm = van.state({});
    const columnFormState = van.state({});

    const find = (tables, selected) => {
        const [kind, tableName, columnName] = (selected ?? '').split(SEPARATOR);
        const table = tables.find((candidate) => candidate.name === tableName) ?? tables[0];
        const column = kind === 'column' ? table?.columns.find((candidate) => candidate.name === columnName) : null;
        return { table, column };
    };
    van.derive(() => {
        if (props.tableEditing.val) {
            tableForm.val = { ...(find(props.currentTables(), props.selected.rawVal).table?.form ?? {}) };
        }
    });
    van.derive(() => {
        if (props.columnEditing.val) {
            columnFormState.val = columnForm(find(props.currentTables(), props.selected.rawVal).column);
        }
    });

    const select = (id) => {
        if (id && id !== props.selected.rawVal) {
            props.tableEditing.val = false;
            props.columnEditing.val = false;
            props.onDismiss();
            props.selected.val = id;
        }
    };

    return div(
        { 'data-testid': 'contract-schema-browser' },
        () => {
            const tables = props.tables();
            if (!tables.length) {
                return span({ class: 'text-secondary' }, 'The contract declares no tables.');
            }
            if (!find(tables, props.selected.rawVal).table || !props.selected.rawVal) {
                props.selected.val = tableId(tables[0].name);
            }
            const unverifiable = new Set(props.unverifiable());
            const nodes = tables.map((table) => ({
                id: tableId(table.name),
                label: table.name,
                icon: unverifiable.has(table.name) ? 'warning' : 'table',
                iconClass: unverifiable.has(table.name) ? 'text-warning' : '',
                iconTooltip: unverifiable.has(table.name) ? 'Not in the table group' : null,
                children: table.columns.map((column) => ({
                    id: columnId(table.name, column.name),
                    label: column.label,
                    icon: 'view_column',
                })),
            }));
            return div(
                { class: 'flex-row fx-align-stretch fx-gap-4' },
                div(
                    { class: 'tg-contract-schema--tree border border-radius-2' },
                    Tree({ classes: 'tg-contract-schema--tree-nodes', nodes, selected: props.selected.rawVal, onSelect: select }),
                ),
                () => Detail(find(tables, props.selected.val), props, { tableForm, columnForm: columnFormState }),
            );
        },
    );
};

const Detail = ({ table, column }, /** @type Properties */ props, forms) => {
    const rulesLink = (label, filter) => Link({
        emit: props.emit,
        href: 'test-suites:definitions',
        params: { ...props.link_params(), tab: 'rules', ...filter },
        label,
    });
    const countLink = (count, filter, scope) => count ? rulesLink(ruleCountText(count, scope), filter) : '';
    const refusal = (section) => () => {
        const result = props.refusal();
        return result?.section === section ? RefusalAlert(result) : '';
    };

    if (!column) {
        const form = forms.tableForm;
        return div(
            { class: 'fx-flex flex-column fx-gap-3', 'data-testid': 'contract-schema-detail' },
            span({ class: 'title m' }, table.name),
            EditableCard({
                title: 'Table',
                testId: 'contract-schema-table',
                class: 'tg-contract-schema--section mb-0',
                editable: props.editable,
                editing: props.tableEditing,
                content: Fields(table.fields),
                editingContent: () => div(
                    { class: 'flex-column fx-gap-3' },
                    Textarea({
                        name: 'table-description', label: 'Description', height: 72, value: form.rawVal.description ?? '',
                        onChange: (value) => update(form, props, 'description', value),
                    }),
                    Input({
                        name: 'table-granularity', label: 'Granularity', value: form.rawVal.dataGranularityDescription ?? '',
                        onChange: (value) => update(form, props, 'dataGranularityDescription', value),
                    }),
                    Select({
                        name: 'table-logical-type', label: 'Logical type', value: form.rawVal.logicalType ?? null,
                        options: [{ label: 'object', value: 'object' }], allowNull: true, width: 240,
                        onChange: (value) => update(form, props, 'logicalType', value ?? ''),
                    }),
                    refusal('schema_table'),
                ),
                hasChanges: () => !isEqual(comparable(form.val), comparable(table.form)),
                onCancel: props.onDismiss,
                onSave: () => props.onSave('schema_table', { table: table.name, ...form.rawVal }),
            }),
            countLink(table.rule_count, { table_name: table.name }, 'table'),
        );
    }

    const form = forms.columnForm;
    const label = `${table.name}.${column.label}`;
    const warnings = () => {
        const result = props.warnings();
        return result?.target?.table === table.name && result?.target?.column === column.name
            ? Alert({ type: 'warn', icon: 'warning' }, div(
                { class: 'flex-column' },
                result.warnings.map((warning) => span(warning)),
            ))
            : '';
    };
    const text = (name, fieldLabel, Component = Input, extra = {}) => Component({
        name: `column-${name}`, label: fieldLabel, value: form.rawVal[name] ?? '',
        onChange: (value) => update(form, props, name, value),
        ...extra,
    });
    const flag = (name, flagLabel) => Checkbox({
        name: `column-${name}`, label: flagLabel, checked: !!form.rawVal[name],
        onChange: (checked) => update(form, props, name, checked),
    });

    return div(
        { class: 'fx-flex flex-column fx-gap-3', 'data-testid': 'contract-schema-detail' },
        span({ class: 'title m' }, label),
        warnings,
        EditableCard({
            title: 'Column',
            testId: 'contract-schema-column',
            class: 'tg-contract-schema--section mb-0',
            editable: props.editable,
            editing: props.columnEditing,
            content: Fields(column.fields),
            editingContent: () => div(
                { class: 'flex-column fx-gap-3' },
                div(
                    { class: 'flex-row fx-gap-3 fx-align-flex-start' },
                    div({ class: 'fx-flex' }, Select({
                        name: 'column-logical-type', label: 'Logical type', value: form.rawVal.logicalType || null,
                        options: LOGICAL_TYPES.map((type) => ({ label: type, value: type })), allowNull: true,
                        onChange: (value) => update(form, props, 'logicalType', value ?? ''),
                    })),
                    div({ class: 'fx-flex' }, text('physicalType', 'Physical type')),
                    div({ class: 'fx-flex' }, text('classification', 'Classification')),
                ),
                div(
                    { class: 'flex-row fx-gap-5 fx-align-flex-center' },
                    flag('primaryKey', 'Primary key'),
                    text('primaryKeyPosition', 'Primary key position', Input, { type: 'number', width: 200 }),
                    flag('criticalDataElement', 'Critical data element'),
                    ...column.declarable.map((key) => flag(key, DECLARABLE_LABELS[key])),
                ),
                text('description', 'Description', Textarea, { height: 72 }),
                text('examples', 'Examples', Textarea, { height: 72, help: 'One example per line.' }),
                refusal('schema_column'),
            ),
            hasChanges: () => !isEqual(comparable(form.val), comparable(columnForm(column))),
            onCancel: props.onDismiss,
            onSave: () => props.onSave('schema_column', { table: table.name, column: column.name, ...columnValues(form.rawVal) }),
        }),
        column.declared.length
            ? Card({
                title: span({ class: 'tg-contract-schema--title' }, 'Declared by Quality Rules'),
                class: 'tg-contract-schema--section mb-0',
                testId: 'contract-schema-declared',
                content: div(
                    { class: 'flex-column fx-gap-2' },
                    column.declared.map((field) => div(
                        { class: 'flex-row fx-gap-4 fx-align-flex-center' },
                        span({ class: 'tg-contract-schema--declared-label text-secondary' }, field.label),
                        span({ class: 'tg-contract-schema--declared-value' }, field.value ?? '--'),
                        rulesLink(`${field.test_name} ›`, {
                            table_name: table.name, column_name: column.name, test_type: field.test_type,
                        }),
                    )),
                ),
            })
            : '',
        countLink(column.rule_count, { table_name: table.name, column_name: column.name }, 'column'),
    );
};

const update = (form, props, name, value) => {
    if (value !== form.rawVal[name]) {
        form.val = { ...form.rawVal, [name]: value };
        props.onDismiss();
    }
};

const Fields = (/** @type SchemaField[] */ fields) => div(
    { class: 'tg-contract-schema--fields' },
    fields.map((field) => Attribute({ label: field.label, value: field.value })),
);

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-contract-schema--tree {
    position: relative;
    width: 280px;
    min-height: 280px;
    flex-shrink: 0;
}

.tg-contract-schema--tree-nodes {
    position: absolute;
    inset: 0;
    overflow-y: auto;
    padding: 8px;
}

.tg-contract-schema--fields {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 16px 24px;
}

.tg-contract-schema--fields .attribute-value {
    white-space: pre-wrap;
}

.tg-contract-schema--tree .tg-tree--row-icon.text-warning {
    color: var(--orange);
}

.tg-card.tg-contract-schema--section {
    padding: 0;
    background-color: transparent;
}

.tg-contract-schema--title {
    text-transform: none;
}

.tg-contract-schema--declared-label {
    width: 160px;
}

.tg-contract-schema--declared-value {
    width: 200px;
}
`);

export { ContractSchema };
