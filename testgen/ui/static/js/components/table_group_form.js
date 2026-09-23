/**
 * @import { Connection } from './connection_form.js';
 *
 * @typedef TableGroup
 * @type {object}
 * @property {string?} id
 * @property {string?} connection_id
 * @property {string?} table_groups_name
 * @property {string?} profiling_include_mask
 * @property {string?} profiling_exclude_mask
 * @property {string?} profiling_table_set
 * @property {FileDeclaration[]?} file_declarations
 * @property {string?} table_group_schema
 * @property {string?} profile_id_column_mask
 * @property {string?} profile_sk_column_mask
 * @property {number?} profiling_delay_days
 * @property {boolean?} profile_flag_cdes
 * @property {boolean?} profile_flag_pii
 * @property {boolean?} include_in_dashboard
 * @property {boolean?} add_scorecard_definition
 * @property {boolean?} profile_use_sampling
 * @property {number?} profile_sample_percent
 * @property {number?} profile_sample_min_count
 * @property {string?} description
 * @property {string?} data_source
 * @property {string?} source_system
 * @property {string?} source_process
 * @property {string?} data_location
 * @property {string?} business_domain
 * @property {string?} stakeholder_group
 * @property {string?} transform_level
 * @property {string?} data_product
 * @property {string?} data_classification
 *
 * @typedef FileDeclaration
 * @type {object}
 * @property {string} name
 * @property {string} uri
 * @property {'csv' | 'parquet' | 'json'} format
 * @property {object?} options
 *
 * @typedef FormState
 * @type {object}
 * @property {boolean} dirty
 * @property {boolean} valid
 *
 * @typedef Properties
 * @type {object}
 * @property {TableGroup} tableGroup
 * @property {Connection[]} connections
 * @property {boolean?} showConnectionSelector
 * @property {boolean?} disableConnectionSelector
 * @property {boolean?} disableSchemaField
 * @property {string?} sqlFlavor
 * @property {string?} sqlFlavorCode
 * @property {string?} schemaLabel
 * @property {boolean?} disablePiiFlag
 * @property {(tg: TableGroup, state: FormState) => void} onChange
 */
import van from '../van.min.js';
import { getValue, isEqual, loadStylesheet } from '../utils.js';
import { Input } from './input.js';
import { Checkbox } from './checkbox.js';
import { ExpansionPanel } from './expansion_panel.js';
import { numberBetween, required } from '../form_validators.js';
import { Select } from './select.js';
import { Caption } from './caption.js';
import { Textarea } from './textarea.js';
import { Icon } from './icon.js';
import { Button } from './button.js';
import { withTooltip } from './tooltip.js';

// Flavors whose profiling sample clause cannot sample views — views are profiled in full.
const SAMPLE_SKIPS_VIEWS_FLAVORS = ['mssql', 'postgresql'];

// Flavor codes whose tables are declared file by file instead of matched from a schema. Branching
// on the code rather than the family matters: the DuckDB database flavor shares a family with the
// file one and keeps the schema-and-criteria form.
const FILE_DECLARATION_FLAVOR_CODES = ['files'];
const declaresFiles = (sqlFlavorCode) => FILE_DECLARATION_FLAVOR_CODES.includes(sqlFlavorCode);

const FILE_FORMAT_OPTIONS = [
    { label: 'CSV', value: 'csv' },
    { label: 'Parquet', value: 'parquet' },
    { label: 'JSON', value: 'json' },
];

const URI_HELP = 'Path relative to the connection base path. Name one file (sales/orders.csv), '
    + 'or a pattern to read every file that matches it: sales/*.csv for the CSV files in a folder, '
    + 'sales/**/*.csv to include its subfolders.';


const HEADER_OPTIONS = [
    { label: 'Auto detect', value: '' },
    { label: 'Yes', value: 'true' },
    { label: 'No', value: 'false' },
];

const DECLARATION_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

// Query-string keys that carry a signed URL. Credentials belong on the connection, where they are
// stored encrypted, rather than in the path of a table.
const CREDENTIAL_KEYS = ['sig', 'x-amz-signature', 'x-amz-credential', 'x-goog-signature', 'signature'];

const hasEmbeddedCredentials = (value) => {
    const query = String(value ?? '').split('?')[1];
    if (!query) {
        return false;
    }
    return query.split('&')
        .map(pair => pair.split('=')[0].trim().toLowerCase())
        .some(key => CREDENTIAL_KEYS.includes(key));
};

const declarationNameValidators = (rows, row) => [
    (value) => (String(value ?? '').trim() ? null : 'Name is required.'),
    (value) => (!value || DECLARATION_NAME_PATTERN.test(String(value).trim())
        ? null
        : 'Name must start with a letter or underscore and contain only letters, numbers and underscores.'),
    (value) => {
        const name = String(value ?? '').trim();
        // DuckDB folds identifiers even when quoted, so names that differ only in case collide.
        const key = name.toLowerCase();
        const taken = rows.rawVal.some(
            other => other !== row && String(other.name.rawVal ?? '').trim().toLowerCase() === key,
        );
        return name && taken ? 'Name is already used by another table in this table group.' : null;
    },
];

const declarationUriValidators = [
    (value) => (String(value ?? '').trim() ? null : 'File or Pattern is required.'),
    (value) => (hasEmbeddedCredentials(value)
        ? 'File or Pattern cannot contain credentials. Credentials are configured on the connection.'
        : null),
];

let nextDeclarationId = 0;
const declarationRow = (declaration) => ({
    id: `declaration-${nextDeclarationId++}`,
    name: van.state(declaration?.name ?? ''),
    uri: van.state(declaration?.uri ?? ''),
    format: van.state(declaration?.format ?? 'csv'),
    delimiter: van.state(declaration?.options?.delimiter ?? ''),
    header: van.state(declaration?.options?.header === undefined ? '' : String(declaration.options.header)),
    quote: van.state(declaration?.options?.quote ?? ''),
    escape: van.state(declaration?.options?.escape ?? ''),
    expanded: van.state(false),
});

const declarationPayload = (row) => {
    const options = {};
    if (row.format.val === 'csv') {
        if (row.delimiter.val) {
            options.delimiter = row.delimiter.val;
        }
        if (row.header.val) {
            options.header = row.header.val === 'true';
        }
        if (row.quote.val) {
            options.quote = row.quote.val;
        }
        if (row.escape.val) {
            options.escape = row.escape.val;
        }
    }
    return {
        name: String(row.name.val ?? '').trim(),
        uri: String(row.uri.val ?? '').trim(),
        format: row.format.val,
        ...(Object.keys(options).length ? { options } : {}),
    };
};

const { div, span } = van.tags;

const normalizeTableSet = (value) => {
    return value?.split(/[,\n]/)
        .map(part => part.trim())
        .filter(part => part)
        .join(', ');
}

/**
 *
 * @param {Properties} props
 * @returns
 */
const TableGroupForm = (props) => {
    loadStylesheet('table-group-form', stylesheet);

    const tableGroup = getValue(props.tableGroup);
    const tableGroupConnectionId = van.state(tableGroup.connection_id);
    const tableGroupsName = van.state(tableGroup.table_groups_name);
    const profilingIncludeMask = van.state(tableGroup.profiling_include_mask ?? '%');
    const profilingExcludeMask = van.state(tableGroup.profiling_exclude_mask ?? 'tmp%');
    const profilingTableSet = van.state(normalizeTableSet(tableGroup.profiling_table_set));
    const declarationRows = van.state((tableGroup.file_declarations ?? []).map(declarationRow));
    const tableGroupSchema = van.state(tableGroup.table_group_schema);
    const profileIdColumnMask = van.state(tableGroup.profile_id_column_mask ?? '%_id');
    const profileSkColumnMask = van.state(tableGroup.profile_sk_column_mask ?? '%_sk');
    const profilingDelayDays = van.state(tableGroup.profiling_delay_days ?? 0);
    const profileFlagCdes = van.state(tableGroup.profile_flag_cdes ?? true);
    const profileFlagPii = van.state(tableGroup.profile_flag_pii ?? true);
    const profileExcludeXde = van.state(tableGroup.profile_exclude_xde ?? true);
    const includeInDashboard = van.state(tableGroup.include_in_dashboard ?? true);
    const addScorecardDefinition = van.state(tableGroup.add_scorecard_definition ?? true);
    const profileUseSampling = van.state(tableGroup.profile_use_sampling ?? false);
    const profileSamplePercent = van.state(tableGroup.profile_sample_percent ?? 30);
    const profileSampleMinCount = van.state(tableGroup.profile_sample_min_count ?? 15000);
    const description = van.state(tableGroup.description);
    const dataSource = van.state(tableGroup.data_source);
    const sourceSystem = van.state(tableGroup.source_system);
    const sourceProcess = van.state(tableGroup.source_process);
    const dataLocation = van.state(tableGroup.data_location);
    const businessDomain = van.state(tableGroup.business_domain);
    const stakeholderGroup = van.state(tableGroup.stakeholder_group);
    const transformLevel = van.state(tableGroup.transform_level);
    const dataProduct = van.state(tableGroup.data_product);
    const dataClassification = van.state(tableGroup.data_classification);

    const connectionOptions = van.derive(() => {
        const connections = getValue(props.connections) ?? [];
        return connections.map(c => ({
            label: c.connection_name,
            value: c.connection_id,
            icon: c.flavor.icon,
        }));
    });
    const showConnectionSelector = getValue(props.showConnectionSelector) ?? false;
    const disableSchemaField = van.derive(() => getValue(props.disableSchemaField) ?? false)

    // A null label means the database type has no schema to name. Only an absent value falls back,
    // so the checks below test for presence rather than using ??, which would treat the two alike.
    const schemaLabel = van.derive(() => {
        const connections = getValue(props.connections) ?? [];
        const selected = connections.find(c => c.connection_id === tableGroupConnectionId.val);
        if (selected?.flavor && 'schema_label' in selected.flavor) {
            return selected.flavor.schema_label;
        }
        const fromProps = getValue(props.schemaLabel);
        return fromProps === undefined ? 'Schema' : fromProps;
    });

    const flavorCode = van.derive(() => {
        const connections = getValue(props.connections) ?? [];
        const selected = connections.find(c => c.connection_id === tableGroupConnectionId.val);
        return selected?.sql_flavor_code ?? getValue(props.sqlFlavorCode);
    });
    const declaresFilesState = van.derive(() => declaresFiles(flavorCode.val));

    const sampleSkipsViews = van.derive(() => {
        const connections = getValue(props.connections) ?? [];
        const selected = connections.find(c => c.connection_id === tableGroupConnectionId.val);
        const flavor = selected?.sql_flavor ?? getValue(props.sqlFlavor);
        return SAMPLE_SKIPS_VIEWS_FLAVORS.includes(flavor);
    });

    const updatedTableGroup = van.derive(() => {
        return {
            id: tableGroup.id,
            connection_id: tableGroupConnectionId.val,
            table_groups_name: tableGroupsName.val,
            profiling_include_mask: profilingIncludeMask.val,
            profiling_exclude_mask: profilingExcludeMask.val,
            profiling_table_set: normalizeTableSet(profilingTableSet.val),
            file_declarations: declarationRows.val.length ? declarationRows.val.map(declarationPayload) : null,
            table_group_schema: tableGroupSchema.val,
            profile_id_column_mask: profileIdColumnMask.val,
            profile_sk_column_mask: profileSkColumnMask.val,
            profiling_delay_days: Number(profilingDelayDays.val),
            profile_flag_cdes: profileFlagCdes.val,
            profile_flag_pii: profileFlagPii.val,
            profile_exclude_xde: profileExcludeXde.val,
            include_in_dashboard: includeInDashboard.val,
            add_scorecard_definition: addScorecardDefinition.val,
            profile_use_sampling: profileUseSampling.val,
            profile_sample_percent: Number(profileSamplePercent.val),
            profile_sample_min_count: Number(profileSampleMinCount.val),
            description: description.val,
            data_source: dataSource.val,
            source_system: sourceSystem.val,
            source_process: sourceProcess.val,
            data_location: dataLocation.val,
            business_domain: businessDomain.val,
            stakeholder_group: stakeholderGroup.val,
            transform_level: transformLevel.val,
            data_product: dataProduct.val,
            data_classification: dataClassification.val,
        };
    });
    const dirty = van.derive(() => !isEqual(updatedTableGroup.val, tableGroup));
    const validityPerField = van.state({});
    if (showConnectionSelector) {
        validityPerField.val.connection_id = !!tableGroupConnectionId.val;
    }

    van.derive(() => {
        // The two ways of naming tables are mutually exclusive, so whichever one the flavor does
        // not use has its fields left out rather than holding the form back while hidden.
        const hidden = declaresFilesState.val ? SCHEMA_FIELDS : DECLARATION_FIELDS;
        const entries = Object.entries(validityPerField.val).filter(([field]) => !hidden.includes(field));
        const isValid = entries.length > 0 && entries.every(([, valid]) => valid);
        props.onChange?.(updatedTableGroup.val, { dirty: dirty.val, valid: isValid });
    });

    const setFieldValidity = (field, validity) => {
        validityPerField.val = {...validityPerField.rawVal, [field]: validity};
    }

    const declarationsValid = van.derive(() => {
        const rows = declarationRows.val;
        const names = rows.map(row => String(row.name.val ?? '').trim());
        const keys = names.map(name => name.toLowerCase());
        return rows.length > 0 && rows.every((row, index) => {
            const name = names[index];
            const uri = String(row.uri.val ?? '').trim();
            return name && DECLARATION_NAME_PATTERN.test(name) && keys.indexOf(keys[index]) === index
                && uri && !hasEmbeddedCredentials(uri);
        });
    });
    van.derive(() => setFieldValidity('file_declarations', declarationsValid.val));

    return div(
        { class: 'flex-column fx-gap-3' },
        showConnectionSelector
            ? Select({
                name: 'connection_id',
                label: 'Connection',
                value: tableGroupConnectionId.rawVal,
                options: connectionOptions,
                required: true,
                disabled: props.disableConnectionSelector,
                onChange: (value, state) => {
                    tableGroupConnectionId.val = value;
                    setFieldValidity('connection_id', state.valid);
                },
            })
            : undefined,
        MainForm(
            { disableSchemaField, schemaLabel, declaresFiles: declaresFilesState, setValidity: setFieldValidity },
            tableGroupsName,
            tableGroupSchema,
        ),
        // Both forms stay mounted and are hidden with CSS rather than swapped out. A reactive node
        // that leaves the DOM loses its bindings for good, and the connection selector can put
        // either one back on screen.
        div(
            { style: () => declaresFilesState.val ? 'display: none;' : '' },
            CriteriaForm(
                { setValidity: setFieldValidity },
                profilingIncludeMask,
                profilingExcludeMask,
                profilingTableSet,
                profileIdColumnMask,
                profileSkColumnMask,
            ),
        ),
        div(
            { style: () => declaresFilesState.val ? '' : 'display: none;' },
            TablesForm(declarationRows),
        ),
        SettingsForm(
            { editMode: !!tableGroup.id, disablePiiFlag: getValue(props.disablePiiFlag) ?? false, setValidity: setFieldValidity },
            profilingDelayDays,
            profileFlagCdes,
            profileFlagPii,
            profileExcludeXde,
            includeInDashboard,
            addScorecardDefinition,
        ),
        SamplingForm(
            { setValidity: setFieldValidity, sampleSkipsViews },
            profileUseSampling,
            profileSamplePercent,
            profileSampleMinCount,
        ),
        TaggingForm(
            { setValidity: setFieldValidity },
            description,
            dataSource,
            sourceSystem,
            sourceProcess,
            dataLocation,
            businessDomain,
            stakeholderGroup,
            transformLevel,
            dataProduct,
            dataClassification,
        ),
    );
};

const MainForm = (
    options,
    tableGroupsName,
    tableGroupSchema,
) => {
    return div(
        { class: 'flex-row fx-align-flex-start fx-gap-3 fx-flex-wrap' },
        Input({
            name: 'table_groups_name',
            label: 'Name',
            value: tableGroupsName,
            class: 'tg-column-flex',
            help: 'Unique name to describe the table group',
            helpPlacement: 'bottom-right',
            onChange: (value, state) => {
                tableGroupsName.val = value;
                options.setValidity?.('table_groups_name', state.valid);
            },
            validators: [ required ],
        }),
        () => getValue(options.declaresFiles) ? '' : Input({
            name: 'table_group_schema',
            label: getValue(options.schemaLabel),
            value: tableGroupSchema,
            class: 'tg-column-flex',
            help: `${getValue(options.schemaLabel)} containing the tables for the Table Group`,
            helpPlacement: 'bottom-left',
            disabled: options.disableSchemaField,
            onChange: (value, state) => {
                tableGroupSchema.val = value;
                options.setValidity?.('table_group_schema', state.valid);
            },
            validators: [ required ],
        }),
    );
};

const TablesForm = (declarationRows) => {
    const addRow = () => {
        declarationRows.val = [...declarationRows.rawVal, declarationRow()];
    };
    const removeRow = (id) => {
        declarationRows.val = declarationRows.rawVal.filter(row => row.id !== id);
    };

    return div(
        { class: 'flex-column fx-gap-3 border border-radius-1 p-3 mt-1', style: 'position: relative;' },
        Caption({ content: 'Tables', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),
        div(
            { class: 'tg-declarations' },
            div(
                { class: 'tg-declarations--row text-caption' },
                span('Name'),
                span(
                    { class: 'flex-row fx-gap-1 fx-align-flex-center' },
                    'File or Pattern',
                    withTooltip(
                        Icon({ size: 16, classes: 'text-disabled' }, 'help'),
                        { text: URI_HELP, position: 'bottom-right', width: 260 },
                    ),
                ),
                span('Format'),
                span(),
                span(),
            ),
            () => div(
                { class: 'flex-column fx-gap-2' },
                declarationRows.val.map(row => DeclarationRow(row, declarationRows, removeRow)),
            ),
            () => declarationRows.val.length
                ? ''
                : div(
                    { class: 'flex-row fx-justify-center fx-gap-1 mt-6 mb-3 text-secondary text-caption' },
                    'No tables declared yet.',
                    span({ class: 'text-error' }, '*'),
                ),
        ),
        div(
            { class: 'flex-row' },
            Button({ type: 'stroked', icon: 'add', label: 'Add Table', width: 'auto', onclick: addRow }),
        ),
    );
};

const DeclarationRow = (row, declarationRows, removeRow) => {
    return div(
        { class: 'tg-declarations--row' },
        Input({
            name: `declaration_name_${row.id}`,
            value: row.name,
            onChange: (value) => row.name.val = value,
            validators: declarationNameValidators(declarationRows, row),
        }),
        Input({
            name: `declaration_uri_${row.id}`,
            value: row.uri,
            onChange: (value) => row.uri.val = value,
            validators: declarationUriValidators,
        }),
        Select({
            name: `declaration_format_${row.id}`,
            value: row.format,
            options: FILE_FORMAT_OPTIONS,
            onChange: (value) => row.format.val = value,
        }),
        () => row.format.val === 'csv'
            ? Button({
                type: 'icon',
                icon: 'tune',
                tooltip: 'CSV settings',
                tooltipPosition: 'left',
                onclick: () => row.expanded.val = !row.expanded.rawVal,
            })
            : span(),
        Button({
            type: 'icon',
            icon: 'delete',
            tooltip: 'Remove table',
            tooltipPosition: 'left',
            onclick: () => removeRow(row.id),
        }),
        () => row.format.val === 'csv' && row.expanded.val
            ? div(
                { class: 'tg-declarations--options flex-row fx-gap-3 fx-flex-wrap p-2 border-radius-1' },
                Input({
                    name: `declaration_delimiter_${row.id}`,
                    label: 'Delimiter',
                    value: row.delimiter,
                    width: 120,
                    placeholder: 'Auto detect',
                    onChange: (value) => row.delimiter.val = value,
                }),
                Select({
                    name: `declaration_header_${row.id}`,
                    label: 'Has header',
                    value: row.header,
                    options: HEADER_OPTIONS,
                    width: 140,
                    onChange: (value) => row.header.val = value,
                }),
                Input({
                    name: `declaration_quote_${row.id}`,
                    label: 'Quote',
                    value: row.quote,
                    width: 100,
                    placeholder: 'Auto detect',
                    onChange: (value) => row.quote.val = value,
                }),
                Input({
                    name: `declaration_escape_${row.id}`,
                    label: 'Escape',
                    value: row.escape,
                    width: 100,
                    placeholder: 'Auto detect',
                    onChange: (value) => row.escape.val = value,
                }),
            )
            : '',
    );
};

// Validity keys that belong to only one way of naming a table group's tables.
const SCHEMA_FIELDS = ['table_group_schema'];
const DECLARATION_FIELDS = ['file_declarations'];

const CriteriaForm = (
    options,
    profilingIncludeMask,
    profilingExcludeMask,
    profilingTableSet,
    profileIdColumnMask,
    profileSkColumnMask,
) => {
    return div(
        { class: 'flex-column fx-gap-3 border border-radius-1 p-3 mt-1', style: 'position: relative;' },
        Caption({content: 'Criteria', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),
        div(
            { class: 'flex-row fx-gap-3 fx-flex-wrap fx-align-flex-start' },
            div(
                { class: 'tg-column-flex flex-column fx-gap-3', },
                Input({
                    name: 'profiling_include_mask',
                    label: 'Tables to Include Mask',
                    value: profilingIncludeMask,
                    help: 'SQL filter supported by your database\'s LIKE operator for table names to include',
                    onChange: (value, state) => {
                        profilingIncludeMask.val = value;
                        options.setValidity?.('profiling_include_mask', state.valid);
                    },
                }),
                Input({
                    name: 'profiling_exclude_mask',
                    label: 'Tables to Exclude Mask',
                    value: profilingExcludeMask,
                    help: 'SQL filter supported by your database\'s LIKE operator for table names to exclude',
                    onChange: (value, state) => {
                        profilingExcludeMask.val = value;
                        options.setValidity?.('profiling_exclude_mask', state.valid);
                    },
                }),
            ),
            Textarea({
                name: 'profiling_table_set',
                label: 'Explicit Table List',
                value: profilingTableSet,
                height: 108,
                class: 'tg-column-flex',
                help: 'List of specific table names to include, separated by commas or newlines',
                onChange: (value) => profilingTableSet.val = value,
            }),
        ),
        div(
            { class: 'flex-row fx-gap-3 fx-flex-wrap' },
            Input({
                name: 'profile_id_column_mask',
                label: 'Profiling ID Column Mask',
                value: profileIdColumnMask,
                class: 'tg-column-flex',
                help: 'SQL filter supported by your database\'s LIKE operator representing ID columns',
                onChange: (value, state) => {
                    profileIdColumnMask.val = value;
                    options.setValidity?.('profile_id_column_mask', state.valid);
                },
            }),
            Input({
                name: 'profile_sk_column_mask',
                label: 'Profiling Surrogate Key Column Mask',
                value: profileSkColumnMask,
                class: 'tg-column-flex',
                help: 'SQL filter supported by your database\'s LIKE operator representing surrogate key columns',
                onChange: (value, state) => {
                    profileSkColumnMask.val = value
                    options.setValidity?.('profile_sk_column_mask', state.valid);
                },
            }),
        ),
    );
};

const SettingsForm = (
    options,
    profilingDelayDays,
    profileFlagCdes,
    profileFlagPii,
    profileExcludeXde,
    includeInDashboard,
    addScorecardDefinition,
) => {
    return div(
        { class: 'flex-row fx-gap-3 fx-flex-wrap fx-align-flex-start border border-radius-1 p-3 mt-1', style: 'position: relative;' },
        Caption({content: 'Settings', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),
        div(
            { class: 'tg-column-flex flex-column fx-gap-3' },
            Checkbox({
                name: 'profile_flag_cdes',
                label: 'Detect critical data elements (CDE) during profiling',
                checked: profileFlagCdes,
                onChange: (value) => profileFlagCdes.val = value,
            }),
            Checkbox({
                name: 'profile_flag_pii',
                label: 'Detect PII during profiling',
                checked: profileFlagPii,
                onChange: (value) => profileFlagPii.val = value,
                disabled: options.disablePiiFlag,
            }),
            Checkbox({
                name: 'profile_exclude_xde',
                label: 'Exclude XDE columns from profiling',
                checked: profileExcludeXde,
                onChange: (value) => profileExcludeXde.val = value,
            }),
            Checkbox({
                name: 'include_in_dashboard',
                label: 'Include table group in Project Dashboard',
                checked: includeInDashboard,
                onChange: (value) => includeInDashboard.val = value,
            }),
            () => !options.editMode
                ? Checkbox({
                    name: 'add_scorecard_definition',
                    label: 'Add scorecard for table group',
                    help: 'Add a new scorecard to the Quality Dashboard upon creation of this table group',
                    checked: addScorecardDefinition,
                    onChange: (value) => addScorecardDefinition.val = value,
                })
                : '',
        ),
        Input({
            name: 'profiling_delay_days',
            type: 'number',
            label: 'Min Profiling Age (in days)',
            value: profilingDelayDays,
            class: 'tg-column-flex',
            validators: [ numberBetween(0, 999, 0) ],
            help: 'Number of days to wait before new profiling will be available to generate tests',
            onChange: (value, state) => {
                profilingDelayDays.val = value;
                options.setValidity?.('profiling_delay_days', state.valid);
            },
        }),
    );
};

const SamplingForm = (
    options,
    profileUseSampling,
    profileSamplePercent,
    profileSampleMinCount,
) => {
    return ExpansionPanel(
        { title: 'Sampling Parameters' },
        div(
            { class: 'flex-column fx-gap-3' },
            Checkbox({
                name: 'profile_use_sampling',
                label: 'Use profile sampling',
                help: 'When checked, profiling will be based on a sample of records instead of the full table',
                checked: profileUseSampling,
                onChange: (value) => profileUseSampling.val = value,
            }),
            div(
                { class: 'flex-row fx-gap-3' },
                Input({
                    name: 'profile_sample_percent',
                    class: 'fx-flex',
                    type: 'number',
                    label: 'Sample percent',
                    value: profileSamplePercent,
                    validators: [ numberBetween(1, 100, 0) ],
                    help: 'Percent of records to include in the sample, unless the calculated count falls below the specified minimum',
                    onChange: (value, state) => {
                        profileSamplePercent.val = value;
                        options.setValidity?.('profile_sample_percent', state.valid);
                    },
                }),
                Input({
                    name: 'profile_sample_min_count',
                    class: 'fx-flex',
                    type: 'number',
                    label: 'Min Sample Record Count',
                    value: profileSampleMinCount,
                    validators: [ numberBetween(0, 999999999, 0) ],
                    help: 'Minimum number of records to be included in any sample (if available)',
                    onChange: (value, state) => {
                        profileSampleMinCount.val = value;
                        options.setValidity?.('profile_sample_min_count', state.valid);
                    },
                }),
            ),
            () => (getValue(options.sampleSkipsViews) && profileUseSampling.val)
                ? div(
                    { class: 'flex-row fx-align-center fx-gap-1' },
                    Icon({ style: 'color: var(--orange); font-size: 18px;' }, 'warning'),
                    span('Views are profiled in full on this database — sampling applies only to tables and materialized views.'),
                )
                : '',
        ),
    );
};

const TaggingForm = (
    options,
    description,
    dataSource,
    sourceSystem,
    sourceProcess,
    dataLocation,
    businessDomain,
    stakeholderGroup,
    transformLevel,
    dataProduct,
    dataClassification,
) => {
    return ExpansionPanel(
        { title: 'Table Group Tags' },
        Input({
            name: 'description',
            class: 'fx-flex mb-3',
            label: 'Description',
            value: description,
            onChange: (value, state) => {
                description.val = value;
                options.setValidity?.('description', state.valid);
            },
        }),
        div(
            { class: 'tg-tagging-form-fields flex-column fx-gap-3 fx-flex-wrap' },
            Input({
                name: 'data_source',
                label: 'Data Source',
                value: dataSource,
                help: 'Original source of the dataset',
                onChange: (value, state) => {
                    dataSource.val = value;
                    options.setValidity?.('data_source', state.valid);
                },
            }),
            Input({
                name: 'source_process',
                label: 'Source Process',
                value: sourceProcess,
                help: 'Process, program, or data flow that produced the dataset',
                onChange: (value, state) => {
                    sourceProcess.val = value;
                    options.setValidity?.('source_process', state.valid);
                },
            }),
            Input({
                name: 'business_domain',
                label: 'Business Domain',
                value: businessDomain,
                help: 'Business division responsible for the dataset, e.g., Finance, Sales, Manufacturing',
                onChange: (value, state) => {
                    businessDomain.val = value;
                    options.setValidity?.('business_domain', state.valid);
                },
            }),
            Input({
                name: 'transform_level',
                label: 'Transform Level',
                value: transformLevel,
                help: 'Data warehouse processing stage, e.g., Raw, Conformed, Processed, Reporting, or Medallion level (bronze, silver, gold)',
                onChange: (value, state) => {
                    transformLevel.val = value;
                    options.setValidity?.('transform_level', state.valid);
                },
            }),
            Input({
                name: 'source_system',
                label: 'Source System',
                value: sourceSystem,
                help: 'Enterprise system source for the dataset',
                onChange: (value, state) => {
                    sourceSystem.val = value;
                    options.setValidity?.('source_system', state.valid);
                },
            }),
            Input({
                name: 'data_location',
                label: 'Data Location',
                value: dataLocation,
                help: 'Physical or virtual location of the dataset, e.g., Headquarters, Cloud',
                onChange: (value, state) => {
                    dataLocation.val = value;
                    options.setValidity?.('data_location', state.valid);
                },
            }),
            Input({
                name: 'stakeholder_group',
                label: 'Stakeholder Group',
                value: stakeholderGroup,
                help: 'Data owners or stakeholders responsible for the dataset',
                onChange: (value, state) => {
                    stakeholderGroup.val = value;
                    options.setValidity?.('stakeholder_group', state.valid);
                },
            }),
            Input({
                name: 'data_product',
                label: 'Data Product',
                value: dataProduct,
                help: 'Data domain that comprises the dataset',
                onChange: (value, state) => {
                    dataProduct.val = value;
                    options.setValidity?.('data_product', state.valid);
                },
            }),
            Input({
                name: 'data_classification',
                label: 'Data Classification',
                value: dataClassification,
                help: 'Information sensitivity level of the dataset, e.g., Public, Internal, Confidential, Restricted',
                onChange: (value, state) => {
                    dataClassification.val = value;
                    options.setValidity?.('data_classification', state.valid);
                },
            }),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-column-flex {
    flex: 250px;
}
.tg-tagging-form-fields {
    height: 332px;
}
.tg-declarations {
    overflow-x: auto;
}
.tg-declarations--row {
    display: grid;
    grid-template-columns: minmax(120px, 1fr) minmax(160px, 2fr) 130px 40px 40px;
    gap: 12px;
    align-items: start;
    min-width: 560px;
}
/* The column headers name these fields once, so each control renders without its own label. The
   empty label still occupies the wrapper's row gap, which is what pushes a select out of line
   with the inputs beside it. */
.tg-declarations--row > .tg-input--label > .text-caption:first-child,
.tg-declarations--row > .tg-select--label > :first-child {
    display: none;
}
.tg-declarations--options {
    grid-column: 1 / -1;
    background: var(--form-field-background-color, rgba(0, 0, 0, 0.04));
}
/* Selects carry a 200px floor, which in these columns overhangs the controls to their right. */
.tg-declarations--row .tg-select--field {
    min-width: 0;
}
`);

export { TableGroupForm, declaresFiles };
