/**
 * @typedef DeclaredTable
 * @type {object}
 * @property {string} name
 * @property {boolean} unverifiable
 *
 * @typedef ServerEntry
 * @type {object}
 * @property {string?} name
 * @property {{label: string, value: string|number|boolean}[]} fields
 *
 * @typedef UnverifiableRule
 * @type {object}
 * @property {string} location
 * @property {string?} type
 * @property {string?} description
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
 * @property {ServerEntry[]} servers
 * @property {UnverifiableRule[]} unverifiable_rules
 * @property {string} unverifiable_rules_info
 * @property {SaveResult?} document_result
 * @property {SaveResult?} tables_result
 * @property {import('./contract_section_cards.js').Overview} overview
 * @property {import('./contract_section_cards.js').Team} team
 * @property {import('./contract_section_cards.js').ListRow[]} roles
 * @property {import('./contract_section_cards.js').ListRow[]} support
 * @property {import('./contract_section_cards.js').ListRow[]} service_levels
 * @property {string} service_levels_info
 * @property {import('./contract_schema.js').SchemaTable[]} schema
 * @property {object} link_params
 * @property {import('./contract_section_cards.js').SectionResult?} section_result
 *
 * @typedef Properties
 * @type {object}
 * @property {MetadataData} data
 * @property {((text: string) => void)} onSaveDocument
 * @property {((tables: string[]) => void)} onSaveTables
 * @property {((section: string, values: object) => void)} onSaveSection
 * @property {function} emit
 */
import van from '../van.min.js';
import { getValue, isEqual, isState } from '../utils.js';
import { Alert } from './alert.js';
import { Attribute } from './attribute.js';
import { Button } from './button.js';
import { Card } from './card.js';
import { CodeEditor } from './code_editor.js';
import { ContractSchema } from './contract_schema.js';
import { ContractTablePicker } from './contract_table_picker.js';
import { OverviewCard, RefusalAlert, RolesCard, serviceLevelsCard, SupportCard, TeamCard } from './contract_section_cards.js';
import { EditableCard } from './editable_card.js';
import { Icon } from './icon.js';
import { Table } from './table.js';
import { withTooltip } from './tooltip.js';

const { div, span } = van.tags;

const DOCUMENT_HEIGHT = 480;

const peek = (prop) => isState(prop) ? prop.rawVal : getValue(prop);

const ContractMetadata = (/** @type Properties */ props) => {
    const data = van.derive(() => getValue(props.data) ?? {});

    const tablesEditing = van.state(false);
    const documentEditing = van.state(false);
    const yamlOpen = van.state(false);
    const schemaSelection = van.state(null);
    const sectionEditing = Object.fromEntries(
        ['overview', 'team', 'roles', 'support', 'service_levels', 'schema_table', 'schema_column']
            .map((section) => [section, van.state(false)]),
    );
    const formOpen = van.derive(() => tablesEditing.val || Object.values(sectionEditing).some((editing) => editing.val));
    const closeYaml = () => {
        documentEditing.val = false;
        yamlOpen.val = false;
    };
    const selected = van.state([]);
    const text = van.state('');
    const dismissed = {
        document_result: van.state(null), tables_result: van.state(null), section_result: van.state(null),
    };
    const handled = { document_result: null, tables_result: null, section_result: null };

    van.derive(() => {
        const d = data.val;
        for (const [key, editing] of [['document_result', documentEditing], ['tables_result', tablesEditing]]) {
            const result = d[key];
            if (result?.token && result.token !== handled[key]) {
                handled[key] = result.token;
                if (result.success) {
                    editing.val = false;
                    if (key === 'document_result') {
                        yamlOpen.val = false;
                    }
                }
            }
        }
        const section = d.section_result;
        if (section?.token && section.token !== handled.section_result) {
            handled.section_result = section.token;
            if (section.success && sectionEditing[section.section]) {
                sectionEditing[section.section].val = false;
            }
        }
        if (!d.editable) {
            tablesEditing.val = false;
            documentEditing.val = false;
            Object.values(sectionEditing).forEach((editing) => editing.val = false);
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
    const sectionRefusal = refusal('section_result');
    const sectionWarnings = van.derive(() => {
        const result = data.val.section_result;
        return result?.success && result.warnings?.length && result.token !== dismissed.section_result.val ? result : null;
    });
    const markers = van.derive(() => documentRefusal.val?.markers ?? data.val.unverifiable_markers ?? []);
    const dismiss = (key) => dismissed[key].val = peek(data)[key]?.token ?? null;
    // A refusal describes the content that was saved, so a change after it clears the alert and its markers
    van.derive(() => {
        selected.val;
        dismiss('tables_result');
    });

    const sectionCard = (section, SectionCard) => SectionCard({
        value: () => data.val[section],
        current: () => peek(data)[section],
        editable: () => data.val.editable,
        editing: sectionEditing[section],
        refusal: () => sectionRefusal.val?.section === section ? sectionRefusal.val : null,
        onDismiss: () => dismiss('section_result'),
        onSave: (values) => props.onSaveSection(section, values),
    });

    const cards = () => {
        schemaContent = div(
            { class: 'flex-column fx-gap-3' },
            ContractSchema({
                tables: () => data.val.schema ?? [],
                currentTables: () => peek(data).schema ?? [],
                unverifiable: () => (data.val.tables ?? []).filter((table) => table.unverifiable).map((table) => table.name),
                editable: () => data.val.editable,
                selected: schemaSelection,
                tableEditing: sectionEditing.schema_table,
                columnEditing: sectionEditing.schema_column,
                refusal: () => sectionRefusal.val,
                warnings: () => sectionWarnings.val,
                link_params: () => data.val.link_params,
                onDismiss: () => dismiss('section_result'),
                onSave: (section, values) => props.onSaveSection(section, values),
                emit: props.emit,
            }),
            () => UnverifiableTables(data.val),
        );
        schemaBody = div(
            div({ style: () => tablesEditing.val ? 'display: none;' : '' }, schemaContent),
            () => tablesEditing.val
                ? div(
                    { class: 'flex-column fx-gap-3' },
                    ContractTablePicker({
                        tables: peek(data).table_options ?? [],
                        unverifiable: (peek(data).tables ?? []).filter((table) => table.unverifiable).map((table) => table.name),
                        selected,
                    }),
                    () => RefusalAlert(tablesRefusal.val),
                )
                : '',
        );
        return cardList();
    };
    let schemaContent = null;
    let schemaBody = null;

    const cardList = () => div(
        { class: 'flex-column fx-gap-4' },
        EditableCard({
            title: 'Schema',
            testId: 'contract-schema',
            editLabel: 'Edit Tables',
            editable: () => data.val.editable,
            editing: tablesEditing,
            // One node for both states: the browser stays connected while the picker is open, since VanJS drops
            // the bindings of a node that is detached when its data changes.
            content: () => schemaBody,
            editingContent: () => schemaBody,
            hasChanges: () => !isEqual(
                [...selected.val].sort(),
                (data.val.tables ?? []).map((table) => table.name).sort(),
            ),
            onCancel: () => dismiss('tables_result'),
            onSave: () => props.onSaveTables(selected.rawVal),
        }),
        sectionCard('overview', OverviewCard),
        sectionCard('team', TeamCard),
        sectionCard('roles', RolesCard),
        sectionCard('support', SupportCard),
        sectionCard('service_levels', serviceLevelsCard(() => data.val.service_levels_info)),
        Card({
            title: 'Servers',
            testId: 'contract-servers',
            content: () => Servers(data.val.servers ?? []),
        }),
        () => (data.val.unverifiable_rules ?? []).length
            ? Card({
                title: 'Rules TestGen Cannot Check',
                testId: 'contract-unverifiable-rules',
                content: () => UnverifiableRules(data.val),
            })
            : '',
    );

    const documentEditor = () => {
        const editable = documentEditing.val;
        return Card({
            title: 'Contract Document',
            testId: 'contract-document',
            content: div(
                { class: 'flex-column fx-gap-3' },
                Alert({ type: 'info', icon: 'info' }, span(peek(data).document_info)),
                editable ? () => RefusalAlert(documentRefusal.val) : '',
                editable
                    ? CodeEditor({
                        value: text.rawVal,
                        language: 'yaml',
                        markers,
                        statusBar: {},
                        height: DOCUMENT_HEIGHT,
                        onChange: (value) => {
                            text.val = value;
                            dismiss('document_result');
                        },
                    })
                    : () => CodeEditor({
                        value: data.val.document,
                        language: 'yaml',
                        readOnly: true,
                        markers: data.val.unverifiable_markers ?? [],
                        height: DOCUMENT_HEIGHT,
                    }),
                editable ? span({ class: 'text-caption' }, peek(data).comments_caption) : '',
                div(
                    { class: 'flex-row fx-justify-content-flex-end fx-gap-3' },
                    editable
                        ? [
                            Button({
                                type: 'stroked',
                                label: 'Cancel',
                                width: 'auto',
                                onclick: () => {
                                    dismiss('document_result');
                                    closeYaml();
                                },
                            }),
                            Button({
                                type: 'stroked',
                                color: 'primary',
                                label: 'Save',
                                width: 'auto',
                                disabled: () => text.val === data.val.document,
                                onclick: () => props.onSaveDocument(text.rawVal),
                            }),
                        ]
                        : Button({ type: 'stroked', label: 'Back', width: 'auto', onclick: closeYaml }),
                ),
            ),
        });
    };

    return div(
        { class: 'flex-column fx-gap-4', 'data-testid': 'contract-metadata' },
        () => yamlOpen.val
            ? ''
            : div(
                { class: 'flex-row fx-justify-content-flex-end' },
                withTooltip(
                    span(
                        { class: 'flex-row' },
                        Button({
                            type: 'stroked',
                            icon: 'data_object',
                            label: () => data.val.editable ? 'Edit as YAML' : 'View as YAML',
                            width: 'auto',
                            disabled: formOpen,
                            onclick: () => {
                                text.val = peek(data).document ?? '';
                                documentEditing.val = !!peek(data).editable;
                                yamlOpen.val = true;
                            },
                        }),
                    ),
                    { text: () => formOpen.val ? 'Save or cancel the open form first.' : '', position: 'left' },
                ),
            ),
        () => yamlOpen.val ? documentEditor() : cards(),
    );
};

const Servers = (/** @type ServerEntry[] */ servers) => servers.length
    ? div(
        { class: 'flex-column fx-gap-4' },
        servers.map((server) => div(
            { class: 'flex-column fx-gap-2', 'data-testid': 'contract-server' },
            span({ class: 'text-bold' }, server.name ?? 'Unnamed server'),
            div(
                { class: 'flex-row fx-flex-wrap fx-gap-5' },
                server.fields.map((field) => Attribute({ label: field.label, value: field.value })),
            ),
        )),
    )
    : span({ class: 'text-secondary' }, 'The contract declares no servers.');

const UnverifiableRules = (/** @type MetadataData */ d) => div(
    { class: 'flex-column fx-gap-3' },
    Alert({ type: 'info', icon: 'info' }, span(d.unverifiable_rules_info)),
    Table(
        {
            columns: [
                { name: 'location', label: 'Table or Column', width: 220, align: 'left' },
                { name: 'type', label: 'Type', width: 160, align: 'left' },
                { name: 'description', label: 'Description', width: 420, align: 'left' },
            ],
            height: 'auto',
            maxHeight: '320px',
            highDensity: true,
        },
        d.unverifiable_rules.map((rule) => ({
            location: rule.location,
            type: rule.type ?? '—',
            description: rule.description ?? '—',
        })),
    ),
);

const UnverifiableTables = (/** @type MetadataData */ d) => d.unverifiable_message
    ? div(
        { class: 'flex-row fx-align-flex-start fx-gap-1 text-caption' },
        Icon({ size: 16, classes: 'text-warning' }, 'warning'),
        span(d.unverifiable_message),
    )
    : '';

export { ContractMetadata };
