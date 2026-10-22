/**
 * @typedef DeclaredTable
 * @type {object}
 * @property {string} name
 * @property {boolean} unverifiable
 *
 * @typedef SaveResult
 * @type {object}
 * @property {string} token - a new value for each save attempt
 * @property {boolean} success
 * @property {string?} message
 * @property {string[]?} problems
 * @property {{line: number, message: string}[]?} markers
 *
 * @typedef MetadataData
 * @type {object}
 * @property {boolean} editable
 * @property {DeclaredTable[]} tables
 * @property {string[]} table_options
 * @property {string?} unverifiable_message
 * @property {string} document
 * @property {{line: number, message: string, severity: string}[]} unverifiable_markers
 * @property {string} document_info
 * @property {string} comments_caption
 * @property {SaveResult?} document_result
 * @property {SaveResult?} tables_result
 *
 * @typedef Properties
 * @type {object}
 * @property {MetadataData} data
 * @property {((text: string) => void)} onSaveDocument
 * @property {((tables: string[]) => void)} onSaveTables
 */
import van from '../van.min.js';
import { getValue, isEqual, isState } from '../utils.js';
import { Alert } from './alert.js';
import { CodeEditor } from './code_editor.js';
import { ContractTablePicker } from './contract_table_picker.js';
import { EditableCard } from './editable_card.js';
import { Icon } from './icon.js';

const { div, li, span, ul } = van.tags;

const DOCUMENT_HEIGHT = 480;

const peek = (prop) => isState(prop) ? prop.rawVal : getValue(prop);

const ContractMetadata = (/** @type Properties */ props) => {
    const data = van.derive(() => getValue(props.data) ?? {});

    const tablesEditing = van.state(false);
    const documentEditing = van.state(false);
    const selected = van.state([]);
    const text = van.state('');
    const dismissed = { document_result: van.state(null), tables_result: van.state(null) };
    const handled = { document_result: null, tables_result: null };

    van.derive(() => {
        const d = data.val;
        for (const [key, editing] of [['document_result', documentEditing], ['tables_result', tablesEditing]]) {
            const result = d[key];
            if (result?.token && result.token !== handled[key]) {
                handled[key] = result.token;
                if (result.success) {
                    editing.val = false;
                }
            }
        }
        if (!d.editable) {
            tablesEditing.val = false;
            documentEditing.val = false;
        }
    });
    van.derive(() => {
        if (tablesEditing.val) {
            selected.val = (peek(data).tables ?? []).map((table) => table.name);
        }
    });
    van.derive(() => {
        if (documentEditing.val) {
            text.val = peek(data).document ?? '';
        }
    });

    const refusal = (key) => van.derive(() => {
        const result = data.val[key];
        return result && !result.success && result.token !== dismissed[key].val ? result : null;
    });
    const documentRefusal = refusal('document_result');
    const tablesRefusal = refusal('tables_result');
    const markers = van.derive(() => documentRefusal.val?.markers ?? data.val.unverifiable_markers ?? []);
    const dismiss = (key) => dismissed[key].val = peek(data)[key]?.token ?? null;
    // A refusal describes the content that was saved, so a change after it clears the alert and its markers
    van.derive(() => {
        selected.val;
        dismiss('tables_result');
    });

    return div(
        { class: 'flex-column fx-gap-4', 'data-testid': 'contract-metadata' },
        EditableCard({
            title: 'Declared Tables',
            testId: 'contract-declared-tables',
            editable: () => data.val.editable,
            editing: tablesEditing,
            content: () => DeclaredTables(data.val),
            editingContent: () => div(
                { class: 'flex-column fx-gap-3' },
                ContractTablePicker({
                    tables: peek(data).table_options ?? [],
                    unverifiable: (peek(data).tables ?? []).filter((table) => table.unverifiable).map((table) => table.name),
                    selected,
                }),
                () => RefusalAlert(tablesRefusal.val),
            ),
            hasChanges: () => !isEqual(
                [...selected.val].sort(),
                (data.val.tables ?? []).map((table) => table.name).sort(),
            ),
            onCancel: () => dismiss('tables_result'),
            onSave: () => props.onSaveTables(selected.rawVal),
        }),
        EditableCard({
            title: 'Contract Document',
            testId: 'contract-document',
            editable: () => data.val.editable,
            editing: documentEditing,
            content: () => div(
                { class: 'flex-column fx-gap-3' },
                Alert({ type: 'info', icon: 'info' }, span(data.val.document_info)),
                CodeEditor({
                    value: data.val.document,
                    language: 'yaml',
                    readOnly: true,
                    markers: data.val.unverifiable_markers ?? [],
                    height: DOCUMENT_HEIGHT,
                }),
            ),
            editingContent: () => div(
                { class: 'flex-column fx-gap-3' },
                Alert({ type: 'info', icon: 'info' }, span(peek(data).document_info)),
                () => RefusalAlert(documentRefusal.val),
                CodeEditor({
                    value: text.rawVal,
                    language: 'yaml',
                    markers,
                    statusBar: {},
                    height: DOCUMENT_HEIGHT,
                    onChange: (value) => {
                        text.val = value;
                        dismiss('document_result');
                    },
                }),
                span({ class: 'text-caption' }, peek(data).comments_caption),
            ),
            hasChanges: () => text.val !== data.val.document,
            onCancel: () => dismiss('document_result'),
            onSave: () => props.onSaveDocument(text.rawVal),
        }),
    );
};

const DeclaredTables = (/** @type MetadataData */ d) => {
    const tables = d.tables ?? [];
    return div(
        { class: 'flex-column fx-gap-2' },
        tables.length
            ? div(
                { class: 'flex-row fx-flex-wrap fx-align-flex-center fx-gap-1', 'data-testid': 'contract-declared-table-list' },
                tables.map((table, index) => span(
                    { class: 'flex-row fx-align-flex-center' },
                    index ? span({ class: 'text-secondary mr-1' }, '·') : '',
                    span(table.name),
                    table.unverifiable ? Icon({ size: 16, classes: 'text-warning ml-1' }, 'warning') : '',
                )),
            )
            : span({ class: 'text-secondary' }, 'The contract declares no tables.'),
        d.unverifiable_message
            ? div(
                { class: 'flex-row fx-align-flex-start fx-gap-1 text-caption' },
                Icon({ size: 16, classes: 'text-warning' }, 'warning'),
                span(d.unverifiable_message),
            )
            : '',
    );
};

const RefusalAlert = (/** @type SaveResult? */ result) => result
    ? Alert(
        { type: 'error', icon: 'error' },
        div(
            { class: 'flex-column' },
            span(result.message),
            result.problems?.length
                ? ul({ class: 'mt-1 mb-0 pl-4' }, result.problems.map((problem) => li(problem)))
                : null,
        ),
    )
    : '';

export { ContractMetadata };
