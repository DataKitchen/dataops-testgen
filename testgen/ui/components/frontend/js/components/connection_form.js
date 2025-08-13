/**
 * @import { FileValue } from './file_input.js';
 * @import { VanState } from '../van.min.js';
 * 
 * @typedef Flavor
 * @type {object}
 * @property {string} label
 * @property {string} value
 * @property {string} icon
 * @property {string} flavor
 * @property {string} connection_string
 * 
 * @typedef ConnectionStatus
 * @type {object}
 * @property {string} message
 * @property {boolean} successful
 * @property {string?} details
 * 
 * @typedef Connection
 * @type {object}
 * @property {string} connection_id
 * @property {string} connection_name
 * @property {string} sql_flavor
 * @property {string} sql_flavor_code
 * @property {string} project_host
 * @property {string} project_port
 * @property {string} project_db
 * @property {string} project_user
 * @property {string} project_pw_encrypted
 * @property {boolean} connect_by_url
 * @property {string?} url
 * @property {boolean} connect_by_key
 * @property {string?} private_key
 * @property {string?} private_key_passphrase
 * @property {string?} http_path
 * @property {ConnectionStatus?} status
 * 
 * @typedef FormState
 * @type {object}
 * @property {boolean} dirty
 * @property {boolean} valid
 * 
 * @typedef FieldsCache
 * @type {object}
 * @property {FileValue} privateKey
 * 
 * @typedef Properties
 * @type {object}
 * @property {Connection} connection
 * @property {Array.<Flavor>} flavors
 * @property {boolean} disableFlavor
 * @property {FileValue?} cachedPrivateKeyFile
 * @property {(c: Connection, state: FormState, cache?: FieldsCache) => void} onChange
 */
import van from '../van.min.js';
import { Button } from './button.js';
import { Alert } from './alert.js';
import { getValue, emitEvent, loadStylesheet, isEqual } from '../utils.js';
import { Input } from './input.js';
import { Slider } from './slider.js';
import { Select } from './select.js';
import { maxLength, minLength, sizeLimit } from '../form_validators.js';
import { RadioGroup } from './radio_group.js';
import { FileInput } from './file_input.js';
import { ExpansionPanel } from './expansion_panel.js';
import { Caption } from './caption.js';

const { div, i, span } = van.tags;
const clearSentinel = '<clear>';
const secretsPlaceholder = '<hidden for safety reasons>';
const defaultPorts = {
    redshift: '5439',
    azure_mssql: '1433',
    synapse_mssql: '1433',
    mssql: '1433',
    postgresql: '5432',
    snowflake: '443',
    databricks: '443',
};

/**
 * 
 * @param {Properties} props
 * @param {(any|undefined)} saveButton
 * @returns {HTMLElement}
 */
const ConnectionForm = (props, saveButton) => {
    loadStylesheet('connectionform', stylesheet);

    const connection = getValue(props.connection);
    const isEditMode = !!connection?.connection_id;
    const defaultPort = defaultPorts[connection?.sql_flavor];

    const connectionFlavor = van.state(connection?.sql_flavor_code);
    const connectionName = van.state(connection?.connection_name ?? '');
    const connectionMaxThreads = van.state(connection?.max_threads ?? 4);
    const connectionQueryChars = van.state(connection?.max_query_chars ?? 9000);
    const privateKeyFile = van.state(getValue(props.cachedPrivateKeyFile) ?? null);

    const flavor = getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal);
    const originalURLTemplate = flavor.connection_string;
    const [_, urlSuffix] = originalURLTemplate.split('@');

    const updatedConnection = van.state({
        project_code: connection.project_code,
        connection_id: connection.connection_id,
        sql_flavor: connection?.sql_flavor ?? undefined,
        project_host: connection?.project_host ?? '',
        project_port: connection?.project_port ?? defaultPort ?? '',
        project_db: connection?.project_db ?? '',
        project_user: connection?.project_user ?? '',
        project_pw_encrypted: isEditMode ? '' : (connection?.project_pw_encrypted ?? ''),
        connect_by_url: connection?.connect_by_url ?? false,
        connect_by_key: connection?.connect_by_key ?? false,
        private_key: isEditMode ? '' : (connection?.private_key ?? ''),
        private_key_passphrase: isEditMode ? '' : (connection?.private_key_passphrase ?? ''),
        http_path: connection?.http_path ?? '',
        url: connection?.connect_by_url 
            ? (connection?.url ?? '')
            : formatURL(
                urlSuffix ?? '',
                connection?.project_host ?? '',
                connection?.project_port ?? defaultPort ?? '',
                connection?.project_db ?? '',
                connection?.http_path ?? '',
            ),

        sql_flavor_code: connectionFlavor.rawVal ?? '',
        connection_name: connectionName.rawVal ?? '',
        max_threads: connectionMaxThreads.rawVal ?? 4,
        max_query_chars: connectionQueryChars.rawVal ?? 9000,
    });

    const dirty = van.derive(() => !isEqual(updatedConnection.val, connection));
    const validityPerField = van.state({});

    const authenticationForms = {
        redshift: () => RedshiftForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('redshift_form', isValid);
            },
            connection,
        ),
        azure_mssql: () => AzureMSSQLForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('mssql_form', isValid);
            },
            connection,
        ),
        synapse_mssql: () => SynapseMSSQLForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('mssql_form', isValid);
            },
            connection,
        ),
        mssql: () => MSSQLForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('mssql_form', isValid);
            },
            connection,
        ),
        postgresql: () => PostgresqlForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('mssql_form', isValid);
            },
            connection,
        ),

        snowflake: () => SnowflakeForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, fileValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                privateKeyFile.val = fileValue;
                setFieldValidity('snowflake_form', isValid);
            },
            connection,
            getValue(props.cachedPrivateKeyFile) ?? null,
        ),
        databricks: () => DatabricksForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('databricks_form', isValid);
            },
            connection,
        ),
    };

    const setFieldValidity = (field, validity) => {
        validityPerField.val = {...validityPerField.val, [field]: validity};
    }

    const authenticationForm = van.derive(() => {
        const selectedFlavorCode = connectionFlavor.val;
        const flavor = getValue(props.flavors).find(f => f.value === selectedFlavorCode);
        return authenticationForms[flavor.value]();
    });

    van.derive(() => {
        const selectedFlavorCode = connectionFlavor.val;
        const previousFlavorCode = connectionFlavor.oldVal;
        const updatedConnection_ = updatedConnection.rawVal;
        
        const isCustomPort = updatedConnection_?.project_port !== defaultPorts[previousFlavorCode];
        if (selectedFlavorCode !== previousFlavorCode && (!isCustomPort || !updatedConnection_?.project_port)) {
            updatedConnection.val = {...updatedConnection_, project_port: defaultPorts[selectedFlavorCode]};
        }
    });

    van.derive(() => {
        const selectedFlavor = connectionFlavor.val;
        const flavorObject = getValue(props.flavors).find(f => f.value === selectedFlavor);

        updatedConnection.val = {
            ...updatedConnection.val,
            sql_flavor: flavorObject.flavor,
            sql_flavor_code: flavorObject.value,
            connection_name: connectionName.val,
            max_threads: connectionMaxThreads.val,
            max_query_chars: connectionQueryChars.val,
        };
    });

    van.derive(() => {
        const fieldsValidity = validityPerField.val;
        const isValid = Object.keys(fieldsValidity).length > 0 &&
            Object.values(fieldsValidity).every(v => v);
        props.onChange?.(updatedConnection.val, { dirty: dirty.val, valid: isValid }, { privateKey: privateKeyFile.rawVal });
    });

    return div(
        { class: 'flex-column fx-gap-3 fx-align-stretch', style: 'overflow-y: auto;' },
        Select({
            label: 'Database Type',
            value: connectionFlavor,
            options: props.flavors,
            disabled: props.disableFlavor,
            height: 38,
            help: 'Type of database server to connect to. This determines the database driver and SQL dialect that will be used by TestGen.',
            testId: 'sql_flavor',
        }),
        Input({
            name: 'connection_name',
            label: 'Connection Name',
            value: connectionName,
            height: 38,
            help: 'Unique name to describe the connection',
            onChange: (value, state) => {
                connectionName.val = value;
                setFieldValidity('connection_name', state.valid);
            },
            validators: [ minLength(3), maxLength(40) ],
        }),

        authenticationForm,

        ExpansionPanel(
            {
                title: 'Advanced Tuning',
            },
            div(
                { class: 'flex-row fx-gap-3' },
                Slider({
                    label: 'Max Threads',
                    hint: 'Maximum number of concurrent threads that run tests. Default values should be retained unless test queries are failing.',
                    value: connectionMaxThreads.rawVal,
                    min: 1,
                    max: 8,
                    onChange: (value) => connectionMaxThreads.val = value,
                }),
                Slider({
                    label: 'Max Expression Length',
                    hint: 'Some tests are consolidated into queries for maximum performance. Default values should be retained unless test queries are failing.',
                    value: connectionQueryChars.rawVal,
                    min: 500,
                    max: 14000,
                    onChange: (value) => connectionQueryChars.val = value,
                }),
            ),
        ),

        div(
            { class: 'flex-row fx-gap-3 fx-justify-space-between' },
            Button({
                label: 'Test Connection',
                color: 'basic',
                type: 'stroked',
                width: 'auto',
                onclick: () => emitEvent('TestConnectionClicked', { payload: updatedConnection.val }),
            }),
            saveButton,
        ),
        () => {
            const conn = getValue(props.connection);
            const connectionStatus = conn.status;
            return connectionStatus
                ? Alert(
                    {type: connectionStatus.successful ? 'success' : 'error', closeable: true},
                    div(
                        { class: 'flex-column' },
                        span(connectionStatus.message),
                        connectionStatus.details ? span(connectionStatus.details) : '',
                    )
                )
                : '';
        },
    );
};

/**
 * @param {VanState<Connection>} connection
 * @param {Flavor} flavor
 * @param {boolean} maskPassword
 * @param {(params: Partial<Connection>, isValid: boolean) => void} onChange
 * @param {Connection?} originalConnection
 * @returns {HTMLElement}
 */
const RedshiftForm = (
    connection,
    flavor,
    onChange,
    originalConnection,
) => {
    const originalURLTemplate = flavor.connection_string;

    const isValid = van.state(true);
    const connectByUrl = van.state(connection.rawVal.connect_by_url ?? false);
    const connectionHost = van.state(connection.rawVal.project_host ?? '');
    const connectionPort = van.state(connection.rawVal.project_port || defaultPorts[flavor.flavor]);
    const connectionDatabase = van.state(connection.rawVal.project_db ?? '');
    const connectionUsername = van.state(connection.rawVal.project_user ?? '');
    const connectionPassword = van.state(connection.rawVal?.project_pw_encrypted ?? '');

    const [prefixPart, sufixPart] = originalURLTemplate.split('@');
    const connectionStringPrefix = van.state(`${prefixPart}@`);
    const connectionStringSuffix = van.state(connection.rawVal?.url ?? '');

    const validityPerField = {};

    if (!connectionStringSuffix.rawVal) {
        connectionStringSuffix.val = formatURL(sufixPart ?? '', connectionHost.rawVal, connectionPort.rawVal, connectionDatabase.rawVal);
    }

    van.derive(() => {
        const connectionHost_ = connectionHost.val;
        const connectionPort_ = connectionPort.val;
        const connectionDatabase_ = connectionDatabase.val;

        if (!connectByUrl.rawVal && originalURLTemplate.includes('@')) {
            const [originalURLPrefix, originalURLSuffix] = originalURLTemplate.split('@');
            connectionStringPrefix.val = `${originalURLPrefix}@`;
            connectionStringSuffix.val = formatURL(originalURLSuffix, connectionHost_, connectionPort_, connectionDatabase_);
        }
    });

    van.derive(() => {
        onChange({
            project_host: connectionHost.val,
            project_port: connectionPort.val,
            project_db: connectionDatabase.val,
            project_user: connectionUsername.val,
            project_pw_encrypted: connectionPassword.val,
            connect_by_url: connectByUrl.val,
            url: connectByUrl.val ? connectionStringSuffix.val : connectionStringSuffix.rawVal,
            connect_by_key: false,
        }, isValid.val);
    });

    return div(
        {class: 'flex-column fx-gap-3 fx-flex'},
        div(
            { class: 'flex-column border border-radius-1 p-3 mt-1 fx-gap-1', style: 'position: relative;' },
            Caption({content: 'Server', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),

            RadioGroup({
                label: 'Connect by',
                options: [
                    {
                        label: 'Host',
                        value: false,
                    },
                    {
                        label: 'URL',
                        value: true,
                    },
                ],
                value: connectByUrl,
                onChange: (value) => connectByUrl.val = value,
                inline: true,
            }),
            div(
                { class: 'flex-row fx-gap-3 fx-flex' },
                Input({
                    name: 'db_host',
                    label: 'Host',
                    value: connectionHost,
                    height: 38,
                    class: 'fx-flex',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionHost.val = value;
                        validityPerField['db_host'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [ maxLength(250) ],
                }),
                Input({
                    name: 'db_port',
                    label: 'Port',
                    value: connectionPort,
                    height: 38,
                    type: 'number',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionPort.val = value;
                        validityPerField['db_port'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [ minLength(3), maxLength(5) ],
                })
            ),
            Input({
                name: 'db_name',
                label: 'Database',
                value: connectionDatabase,
                height: 38,
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionDatabase.val = value;
                    validityPerField['db_name'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [ maxLength(100) ],
            }),
            () => div(
                { class: 'flex-row fx-gap-3 fx-align-stretch', style: 'position: relative;' },
                Input({
                    label: 'URL',
                    value: connectionStringSuffix,
                    class: 'fx-flex',
                    height: 38,
                    name: 'url_suffix',
                    prefix: span({ style: 'height: 38px; white-space: nowrap; color: var(--disabled-text-color)' }, connectionStringPrefix),
                    disabled: !connectByUrl.val,
                    onChange: (value, state) => connectionStringSuffix.val = value,
                }),
            ),
        ),

        div(
            { class: 'flex-column border border-radius-1 p-3 mt-1 fx-gap-1', style: 'position: relative;' },
            Caption({content: 'Authentication', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),

            Input({
                name: 'db_user',
                label: 'Username',
                value: connectionUsername,
                height: 38,
                onChange: (value, state) => {
                    connectionUsername.val = value;
                    validityPerField['db_user'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [ maxLength(50) ],
            }),
            Input({
                name: 'password',
                label: 'Password',
                value: connectionPassword,
                height: 38,
                type: 'password',
                placeholder: (originalConnection?.connection_id && originalConnection?.project_pw_encrypted) ? secretsPlaceholder : '',
                onChange: (value, state) => {
                    connectionPassword.val = value;
                    validityPerField['password'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
            }),
        ),
    );
};

const PostgresqlForm = RedshiftForm;

const AzureMSSQLForm = RedshiftForm;

const SynapseMSSQLForm = RedshiftForm;

const MSSQLForm = RedshiftForm;

/**
 * @param {VanState<Connection>} connection
 * @param {Flavor} flavor
 * @param {boolean} maskPassword
 * @param {(params: Partial<Connection>, isValid: boolean) => void} onChange
 * @param {Connection?} originalConnection
 * @returns {HTMLElement}
 */
const DatabricksForm = (
    connection,
    flavor,
    onChange,
    originalConnection,
) => {
    const originalURLTemplate = flavor.connection_string;

    const isValid = van.state(true);
    const connectByUrl = van.state(connection.rawVal?.connect_by_url ?? false);
    const connectionHost = van.state(connection.rawVal?.project_host ?? '');
    const connectionPort = van.state(connection.rawVal?.project_port || defaultPorts[flavor.flavor]);
    const connectionHttpPath = van.state(connection.rawVal?.http_path ?? '');
    const connectionDatabase = van.state(connection.rawVal?.project_db ?? '');
    const connectionUsername = van.state(connection.rawVal?.project_user ?? '');
    const connectionPassword = van.state(connection.rawVal?.project_pw_encrypted ?? '');

    const [prefixPart, sufixPart] = originalURLTemplate.split('@');
    const connectionStringPrefix = van.state(`${prefixPart}@`);
    const connectionStringSuffix = van.state(connection.rawVal?.url ?? '');

    const validityPerField = {};

    if (!connectionStringSuffix.rawVal) {
        connectionStringSuffix.val = formatURL(sufixPart ?? '', connectionHost.rawVal, connectionPort.rawVal, connectionDatabase.rawVal, connectionHttpPath.rawVal);
    }

    van.derive(() => {
        const connectionHost_ = connectionHost.val;
        const connectionPort_ = connectionPort.val;
        const connectionDatabase_ = connectionDatabase.val;
        const connectionHttpPath_ = connectionHttpPath.val;

        if (!connectByUrl.rawVal && originalURLTemplate.includes('@')) {
            const [, originalURLSuffix] = originalURLTemplate.split('@');
            connectionStringSuffix.val = formatURL(originalURLSuffix, connectionHost_, connectionPort_, connectionDatabase_, connectionHttpPath_);
        }
    });

    van.derive(() => {
        onChange({
            project_host: connectionHost.val,
            project_port: connectionPort.val,
            project_db: connectionDatabase.val,
            project_user: connectionUsername.val,
            project_pw_encrypted: connectionPassword.val,
            http_path: connectionHttpPath.val,
            connect_by_url: connectByUrl.val,
            url: connectByUrl.val ? connectionStringSuffix.val : connectionStringSuffix.rawVal,
            connect_by_key: false,
        }, isValid.val);
    });

    return div(
        {class: 'flex-column fx-gap-3 fx-flex'},
        div(
            { class: 'flex-column border border-radius-1 p-3 mt-1 fx-gap-1', style: 'position: relative;' },
            Caption({content: 'Server', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),

            RadioGroup({
                label: 'Connect by',
                options: [
                    {
                        label: 'Host',
                        value: false,
                    },
                    {
                        label: 'URL',
                        value: true,
                    },
                ],
                value: connectByUrl,
                onChange: (value) => connectByUrl.val = value,
                inline: true,
            }),
            div(
                { class: 'flex-row fx-gap-3 fx-flex' },
                Input({
                    name: 'db_host',
                    label: 'Host',
                    value: connectionHost,
                    height: 38,
                    class: 'fx-flex',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionHost.val = value;
                        validityPerField['db_host'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [ maxLength(250) ],
                }),
                Input({
                    name: 'db_port',
                    label: 'Port',
                    value: connectionPort,
                    height: 38,
                    type: 'number',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionPort.val = value;
                        validityPerField['db_port'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [ minLength(3), maxLength(5) ],
                })
            ),
            Input({
                label: 'HTTP Path',
                value: connectionHttpPath,
                class: 'fx-flex',
                height: 38,
                name: 'http_path',
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionHttpPath.val = value;
                    validityPerField['http_path'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [ maxLength(50) ],
            }),
            Input({
                name: 'db_name',
                label: 'Database',
                value: connectionDatabase,
                height: 38,
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionDatabase.val = value;
                    validityPerField['db_name'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [ maxLength(100) ],
            }),
            () => div(
                { class: 'flex-row fx-gap-3 fx-align-stretch', style: 'position: relative;' },
                Input({
                    label: 'URL',
                    value: connectionStringSuffix,
                    class: 'fx-flex',
                    height: 38,
                    name: 'url_suffix',
                    prefix: span({ style: 'height: 38px; white-space: nowrap; color: var(--disabled-text-color)' }, connectionStringPrefix),
                    disabled: !connectByUrl.val,
                    onChange: (value, state) => connectionStringSuffix.val = value,
                }),
            ),
        ),

        div(
            { class: 'flex-column border border-radius-1 p-3 mt-1 fx-gap-1', style: 'position: relative;' },
            Caption({content: 'Authentication', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),

            Input({
                name: 'db_user',
                label: 'Username',
                value: connectionUsername,
                height: 38,
                onChange: (value, state) => {
                    connectionUsername.val = value;
                    validityPerField['db_user'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [ maxLength(50) ],
            }),
            Input({
                name: 'password',
                label: 'Password',
                value: connectionPassword,
                height: 38,
                type: 'password',
                placeholder: (originalConnection?.connection_id && originalConnection?.project_pw_encrypted) ? secretsPlaceholder : '',
                onChange: (value, state) => {
                    connectionPassword.val = value;
                    validityPerField['password'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
            }),
        ),
    );
};

/**
 * @param {VanState<Connection>} connection
 * @param {Flavor} flavor
 * @param {boolean} maskPassword
 * @param {(params: Partial<Connection>, isValid: boolean) => void} onChange
 * @param {Connection?} originalConnection
 * @param {string?} originalConnection
 * @returns {HTMLElement}
 */
const SnowflakeForm = (
    connection,
    flavor,
    onChange,
    originalConnection,
    cachedFile,
) => {
    const originalURLTemplate = flavor.connection_string;

    const isValid = van.state(false);
    const clearPrivateKeyPhrase = van.state(connection.rawVal?.private_key_passphrase === clearSentinel);
    const connectByUrl = van.state(connection.rawVal.connect_by_url ?? false);
    const connectByKey = van.state(connection.rawVal?.connect_by_key ?? false);
    const connectionHost = van.state(connection.rawVal.project_host ?? '');
    const connectionPort = van.state(connection.rawVal.project_port || defaultPorts[flavor.flavor]);
    const connectionDatabase = van.state(connection.rawVal.project_db ?? '');
    const connectionUsername = van.state(connection.rawVal.project_user ?? '');
    const connectionPassword = van.state(connection.rawVal?.project_pw_encrypted ?? '');
    const connectionPrivateKey = van.state(connection.rawVal?.private_key ?? '');
    const connectionPrivateKeyPassphrase = van.state(
        clearPrivateKeyPhrase.rawVal
        ? ''
        : (connection.rawVal?.private_key_passphrase ?? '')
    );
    const validityPerField = {};

    const privateKeyFileRaw = van.state(cachedFile);

    const [prefixPart, sufixPart] = originalURLTemplate.split('@');
    const connectionStringPrefix = van.state(`${prefixPart}@`);
    const connectionStringSuffix = van.state(connection.rawVal?.url ?? '');

    if (!connectionStringSuffix.rawVal) {
        connectionStringSuffix.val = formatURL(sufixPart ?? '', connectionHost.rawVal, connectionPort.rawVal, connectionDatabase.rawVal);
    }

    van.derive(() => {
        const connectionHost_ = connectionHost.val;
        const connectionPort_ = connectionPort.val;
        const connectionDatabase_ = connectionDatabase.val;

        if (!connectByUrl.rawVal && originalURLTemplate.includes('@')) {
            const [, originalURLSuffix] = originalURLTemplate.split('@');
            connectionStringSuffix.val = formatURL(originalURLSuffix, connectionHost_, connectionPort_, connectionDatabase_);
        }
    });

    van.derive(() => {
        onChange({
            project_host: connectionHost.val,
            project_port: connectionPort.val,
            project_db: connectionDatabase.val,
            project_user: connectionUsername.val,
            project_pw_encrypted: connectionPassword.val,
            connect_by_url: connectByUrl.val,
            url: connectByUrl.val ? connectionStringSuffix.val : connectionStringSuffix.rawVal,
            connect_by_key: connectByKey.val,
            private_key: connectionPrivateKey.val,
            private_key_passphrase: clearPrivateKeyPhrase.val ? clearSentinel : connectionPrivateKeyPassphrase.val,
        }, privateKeyFileRaw.val, isValid.val);
    });

    return div(
        {class: 'flex-column fx-gap-3 fx-flex'},
        div(
            { class: 'flex-column border border-radius-1 p-3 mt-1 fx-gap-1', style: 'position: relative;' },
            Caption({content: 'Server', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),

            RadioGroup({
                label: 'Connect by',
                options: [
                    {
                        label: 'Host',
                        value: false,
                    },
                    {
                        label: 'URL',
                        value: true,
                    },
                ],
                value: connectByUrl,
                onChange: (value) => connectByUrl.val = value,
                inline: true,
            }),
            div(
                { class: 'flex-row fx-gap-3 fx-flex' },
                Input({
                    name: 'db_host',
                    label: 'Host',
                    value: connectionHost,
                    height: 38,
                    class: 'fx-flex',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionHost.val = value;
                        validityPerField['db_host'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [ maxLength(250) ],
                }),
                Input({
                    name: 'db_port',
                    label: 'Port',
                    value: connectionPort,
                    height: 38,
                    type: 'number',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionPort.val = value;
                        validityPerField['db_port'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [ minLength(3), maxLength(5) ],
                })
            ),
            Input({
                name: 'db_name',
                label: 'Database',
                value: connectionDatabase,
                height: 38,
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionDatabase.val = value;
                    validityPerField['db_name'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [ maxLength(100) ],
            }),
            () => div(
                { class: 'flex-row fx-gap-3 fx-align-stretch', style: 'position: relative;' },
                Input({
                    label: 'URL',
                    value: connectionStringSuffix,
                    class: 'fx-flex',
                    height: 38,
                    name: 'url_suffix',
                    prefix: span({ style: 'height: 38px; white-space: nowrap; color: var(--disabled-text-color)' }, connectionStringPrefix),
                    disabled: !connectByUrl.val,
                    onChange: (value, state) => {
                        connectionStringSuffix.val = value;
                        validityPerField['url_suffix'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                }),
            ),
        ),

        div(
            { class: 'flex-column border border-radius-1 p-3 mt-1 fx-gap-1', style: 'position: relative;' },
            Caption({content: 'Authentication', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),

            RadioGroup({
                label: 'Connection Strategy',
                options: [
                    {label: 'Connect By Password', value: false},
                    {label: 'Connect By Key-Pair', value: true},
                ],
                value: connectByKey,
                onChange: (value) => connectByKey.val = value,
                inline: true,
            }),

            Input({
                name: 'db_user',
                label: 'Username',
                value: connectionUsername,
                height: 38,
                onChange: (value, state) => {
                    connectionUsername.val = value;
                    validityPerField['db_user'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [ maxLength(50) ],
            }),
            () => {
                if (connectByKey.val) {
                    return div(
                        { class: 'flex-column fx-gap-3' },
                        div(
                            { class: 'key-pair-passphrase-field'},
                            Input({
                                name: 'private_key_passphrase',
                                label: 'Private Key Passphrase',
                                value: connectionPrivateKeyPassphrase,
                                height: 38,
                                type: 'password',
                                help: 'Passphrase used when creating the private key. Leave empty if the private key is not encrypted.',
                                placeholder: () => (originalConnection?.connection_id && originalConnection?.private_key_passphrase && !clearPrivateKeyPhrase.val) ? secretsPlaceholder : '',
                                onChange: (value, state) => {
                                    if (value) {
                                        clearPrivateKeyPhrase.val = false;
                                    }
                                    connectionPrivateKeyPassphrase.val = value;
                                    validityPerField['private_key_passphrase'] = state.valid;
                                    isValid.val = Object.values(validityPerField).every(v => v);
                                },
                            }),
                            () => {
                                const hasPrivateKeyPhrase = originalConnection?.private_key_passphrase || connectionPrivateKeyPassphrase.val;
                                if (!hasPrivateKeyPhrase) {
                                    return '';
                                }

                                return i(
                                    {
                                        class: 'material-symbols-rounded clickable text-secondary',
                                        onclick: () => {
                                            clearPrivateKeyPhrase.val = true;
                                            connectionPrivateKeyPassphrase.val = '';
                                        },
                                    },
                                    'clear',
                                );
                            },
                        ),
                        FileInput({
                            name: 'private_key',
                            label: 'Upload private key (rsa_key.p8)',
                            placeholder: (originalConnection?.connection_id && originalConnection?.private_key)
                                ? 'Drop file here or browse files to replace existing key'
                                : undefined,
                            value: privateKeyFileRaw,
                            onChange: (value, state) => {
                                let isFieldValid = state.valid;

                                privateKeyFileRaw.val = value;
                                try {
                                    if (value?.content) {
                                        connectionPrivateKey.val = value.content.split(',')?.[1] ?? '';
                                    }
                                } catch (err) {
                                    console.error(err);
                                    isFieldValid = false;
                                }
                                validityPerField['private_key'] = state.valid;
                                isValid.val = Object.values(validityPerField).every(v => v);
                            },
                            validators: [
                                sizeLimit(200 * 1024 * 1024),
                            ],
                        }),
                    );
                }

                return Input({
                    name: 'password',
                    label: 'Password',
                    value: connectionPassword,
                    height: 38,
                    type: 'password',
                    placeholder: (originalConnection?.connection_id && originalConnection?.project_pw_encrypted) ? secretsPlaceholder : '',
                    onChange: (value, state) => {
                        connectionPassword.val = value;
                        validityPerField['password'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                });
            },
        ),
    );
};

function formatURL(url, host, port, database, httpPath) {
    return url.replace('<host>', host)
        .replace('<port>', port)
        .replace('<database>', database)
        .replace('<http_path>', httpPath);
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.key-pair-passphrase-field {
    position: relative;
}

.key-pair-passphrase-field > i {
    position: absolute;
    top: 26px;
    right: 8px;
}

`);

export { ConnectionForm };
