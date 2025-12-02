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
 * @property {string} project_code
 * @property {string} project_host
 * @property {string} project_port
 * @property {string} project_db
 * @property {string} project_user
 * @property {string} project_pw_encrypted
 * @property {boolean} connect_by_url
 * @property {string?} url
 * @property {boolean} connect_by_key
 * @property {boolean} connect_with_identity
 * @property {string?} private_key
 * @property {string?} private_key_passphrase
 * @property {string?} http_path
 * @property {string?} warehouse
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
 * @property {FileValue} serviceAccountKey
 *
 * @typedef Properties
 * @type {object}
 * @property {Connection} connection
 * @property {Array.<Flavor>} flavors
 * @property {boolean} disableFlavor
 * @property {FileValue?} cachedPrivateKeyFile
 * @property {FileValue?} cachedServiceAccountKeyFile
 * @param {string?} dynamicConnectionUrl
 * @property {(c: Connection, state: FormState, cache?: FieldsCache) => void} onChange
 */
import van from '../van.min.js';
import { Button } from './button.js';
import { Alert } from './alert.js';
import { getValue, emitEvent, loadStylesheet, isEqual } from '../utils.js';
import { Input } from './input.js';
import { Slider } from './slider.js';
import { Select } from './select.js';
import { maxLength, minLength, required, requiredIf, sizeLimit } from '../form_validators.js';
import { RadioGroup } from './radio_group.js';
import { FileInput } from './file_input.js';
import { ExpansionPanel } from './expansion_panel.js';
import { Caption } from './caption.js';

const { div, span } = van.tags;
const clearSentinel = '<clear>';
const secretsPlaceholder = '<hidden for safety reasons>';
const defaultPorts = {
    redshift: '5439',
    redshift_spectrum: '5439',
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

    const connectionStatus = van.state(undefined);
    van.derive(() => {
        connectionStatus.val = getValue(props.connection)?.status;
    });

    const connectionFlavor = van.state(connection?.sql_flavor_code);
    const connectionName = van.state(connection?.connection_name ?? '');
    const connectionMaxThreads = van.state(connection?.max_threads ?? 4);
    const connectionQueryChars = van.state(connection?.max_query_chars ?? 20000);
    const privateKeyFile = van.state(getValue(props.cachedPrivateKeyFile) ?? null);
    const serviceAccountKeyFile = van.state(getValue(props.cachedServiceAccountKeyFile) ?? null);

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
        warehouse: connection?.warehouse ?? '',
        url: connection?.url ?? '',
        service_account_key: connection?.service_account_key ?? '',
        connect_with_identity: connection?.connect_with_identity ?? false,
        sql_flavor_code: connectionFlavor.rawVal ?? '',
        connection_name: connectionName.rawVal ?? '',
        max_threads: connectionMaxThreads.rawVal ?? 4,
        max_query_chars: connectionQueryChars.rawVal ?? 20000,
    });
    const dynamicConnectionUrl = van.state(props.dynamicConnectionUrl?.rawVal ?? '');

    van.derive(() => {
        const previousValue = updatedConnection.oldVal;
        const currentValue = updatedConnection.rawVal;

        if (shouldRefreshUrl(previousValue, currentValue)) {
            emitEvent('ConnectionUpdated', {payload: updatedConnection.rawVal});
        }
    });

    van.derive(() => {
        const updatedUrl = getValue(props.dynamicConnectionUrl);
        dynamicConnectionUrl.val = updatedUrl;
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
            dynamicConnectionUrl,
        ),
        redshift_spectrum: () => RedshiftSpectrumForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('redshift_spectrum_form', isValid);
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
            dynamicConnectionUrl,
        ),
        synapse_mssql: () => SynapseMSSQLForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('mssql_form', isValid);
            },
            connection,
            dynamicConnectionUrl,
        ),
        mssql: () => MSSQLForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('mssql_form', isValid);
            },
            connection,
            dynamicConnectionUrl,
        ),
        postgresql: () => PostgresqlForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('postgresql_form', isValid);
            },
            connection,
            dynamicConnectionUrl,
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
            dynamicConnectionUrl,
        ),
        databricks: () => DatabricksForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                setFieldValidity('databricks_form', isValid);
            },
            connection,
            dynamicConnectionUrl,
        ),
        bigquery: () => BigqueryForm(
            updatedConnection,
            getValue(props.flavors).find(f => f.value === connectionFlavor.rawVal),
            (formValue, fileValue, isValid) => {
                updatedConnection.val = {...updatedConnection.val, ...formValue};
                serviceAccountKeyFile.val = fileValue;
                setFieldValidity('bigquery_form', isValid);
            },
            connection,
            getValue(props.cachedServiceAccountKeyFile) ?? null
        ),
    };

    const setFieldValidity = (field, validity) => {
        validityPerField.val = {...validityPerField.val, [field]: validity};
    }

    const authenticationForm = van.derive(() => {
        const selectedFlavorCode = connectionFlavor.val;
        validityPerField.val = {connection_name: validityPerField.val.connection_name};
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
        props.onChange?.(
            updatedConnection.val,
            { dirty: dirty.val, valid: isValid },
            { privateKey: privateKeyFile.rawVal, serviceAccountKey: serviceAccountKeyFile.rawVal }
        );
    });

    return div(
        { class: 'flex-column fx-gap-3 fx-align-stretch', style: 'overflow-y: auto;' },
        Select({
            label: 'Database Type',
            value: connectionFlavor,
            options: props.flavors,
            disabled: props.disableFlavor,
            help: 'Type of database server to connect to. This determines the database driver and SQL dialect that will be used by TestGen.',
            testId: 'sql_flavor',
        }),
        Input({
            name: 'connection_name',
            label: 'Connection Name',
            value: connectionName,
            help: 'Unique name to describe the connection',
            onChange: (value, state) => {
                connectionName.val = value;
                setFieldValidity('connection_name', state.valid);
            },
            validators: [ required, minLength(3), maxLength(40) ],
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
                    max: 50000,
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
            return connectionStatus.val
                ? Alert(
                    {
                        type: connectionStatus.val.successful ? 'success' : 'error',
                        closeable: true,
                        onClose: () => connectionStatus.val = undefined,
                    },
                    div(
                        { class: 'flex-column' },
                        span(connectionStatus.val.message),
                        connectionStatus.val.details ? span(connectionStatus.val.details) : '',
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
 * @param {VanState<string?>} dynamicConnectionUrl
 * @returns {HTMLElement}
 */
const RedshiftForm = (
    connection,
    flavor,
    onChange,
    originalConnection,
    dynamicConnectionUrl,
) => {
    const isValid = van.state(true);
    const connectByUrl = van.state(connection.rawVal.connect_by_url ?? false);
    const connectionHost = van.state(connection.rawVal.project_host ?? '');
    const connectionPort = van.state(connection.rawVal.project_port || defaultPorts[flavor.flavor]);
    const connectionDatabase = van.state(connection.rawVal.project_db ?? '');
    const connectionUsername = van.state(connection.rawVal.project_user ?? '');
    const connectionPassword = van.state(connection.rawVal?.project_pw_encrypted ?? '');
    const connectionUrl = van.state(connection.rawVal?.url ?? '');

    const validityPerField = {};

    van.derive(() => {
        onChange({
            project_host: connectionHost.val,
            project_port: connectionPort.val,
            project_db: connectionDatabase.val,
            project_user: connectionUsername.val,
            project_pw_encrypted: connectionPassword.val,
            connect_by_url: connectByUrl.val,
            url: connectByUrl.val ? connectionUrl.val : connectionUrl.rawVal,
            connect_by_key: false,
        }, isValid.val);
    });

    van.derive(() => {
        const newUrlValue = (dynamicConnectionUrl.val ?? '').replace(extractPrefix(dynamicConnectionUrl.rawVal), '');
        if (!connectByUrl.rawVal) {
            connectionUrl.val = newUrlValue;
        }
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
                layout: 'inline',
            }),
            div(
                { class: 'flex-row fx-gap-3 fx-flex' },
                Input({
                    name: 'db_host',
                    label: 'Host',
                    value: connectionHost,
                    class: 'fx-flex',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionHost.val = value;
                        validityPerField['db_host'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        maxLength(250),
                        requiredIf(() => !connectByUrl.val),
                    ],
                }),
                Input({
                    name: 'db_port',
                    label: 'Port',
                    value: connectionPort,
                    type: 'number',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionPort.val = value;
                        validityPerField['db_port'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        minLength(3),
                        maxLength(5),
                        requiredIf(() => !connectByUrl.val),
                    ],
                })
            ),
            Input({
                name: 'db_name',
                label: 'Database',
                value: connectionDatabase,
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionDatabase.val = value;
                    validityPerField['db_name'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    maxLength(100),
                    requiredIf(() => !connectByUrl.val),
                ],
            }),
            () => div(
                { class: 'flex-row fx-gap-3 fx-align-stretch', style: 'position: relative;' },
                Input({
                    label: 'URL',
                    value: connectionUrl,
                    class: 'fx-flex',
                    name: 'url_suffix',
                    prefix: span({ style: 'white-space: nowrap; color: var(--disabled-text-color)' }, extractPrefix(dynamicConnectionUrl.val)),
                    disabled: !connectByUrl.val,
                    onChange: (value, state) => {
                        connectionUrl.val = value;
                        validityPerField['url_suffix'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        requiredIf(() => connectByUrl.val),
                    ],
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
                onChange: (value, state) => {
                    connectionUsername.val = value;
                    validityPerField['db_user'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    required,
                    maxLength(50),
                ],
            }),
            Input({
                name: 'password',
                label: 'Password',
                value: connectionPassword,
                type: 'password',
                passwordSuggestions: false,
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

const RedshiftSpectrumForm = RedshiftForm;

const PostgresqlForm = RedshiftForm;

const AzureMSSQLForm = (
    connection,
    flavor,
    onChange,
    originalConnection,
    dynamicConnectionUrl,
) => {
    const isValid = van.state(true);
    const connectByUrl = van.state(connection.rawVal.connect_by_url ?? false);
    const connectionHost = van.state(connection.rawVal.project_host ?? '');
    const connectionPort = van.state(connection.rawVal.project_port || defaultPorts[flavor.flavor]);
    const connectionDatabase = van.state(connection.rawVal.project_db ?? '');
    const connectionUsername = van.state(connection.rawVal.project_user ?? '');
    const connectionPassword = van.state(connection.rawVal?.project_pw_encrypted ?? '');
    const connectionUrl = van.state(connection.rawVal?.url ?? '');
    const connectWithIdentity = van.state(connection.rawVal?.connect_with_identity ?? '');

    const validityPerField = {};

    van.derive(() => {
        onChange({
            project_host: connectionHost.val,
            project_port: connectionPort.val,
            project_db: connectionDatabase.val,
            project_user: connectionUsername.val,
            project_pw_encrypted: connectionPassword.val,
            connect_by_url: connectByUrl.val,
            url: connectByUrl.val ? connectionUrl.val : connectionUrl.rawVal,
            connect_by_key: false,
            connect_with_identity: connectWithIdentity.val,
        }, isValid.val);
    });

    van.derive(() => {
        const newUrlValue = (dynamicConnectionUrl.val ?? '').replace(extractPrefix(dynamicConnectionUrl.rawVal), '');
        if (!connectByUrl.rawVal) {
            connectionUrl.val = newUrlValue;
        }
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
                layout: 'inline',
            }),
            div(
                { class: 'flex-row fx-gap-3 fx-flex' },
                Input({
                    name: 'db_host',
                    label: 'Host',
                    value: connectionHost,
                    class: 'fx-flex',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionHost.val = value;
                        validityPerField['db_host'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        maxLength(250),
                        requiredIf(() => !connectByUrl.val),
                    ],
                }),
                Input({
                    name: 'db_port',
                    label: 'Port',
                    value: connectionPort,
                    type: 'number',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionPort.val = value;
                        validityPerField['db_port'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        minLength(3),
                        maxLength(5),
                        requiredIf(() => !connectByUrl.val),
                    ],
                })
            ),
            Input({
                name: 'db_name',
                label: 'Database',
                value: connectionDatabase,
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionDatabase.val = value;
                    validityPerField['db_name'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    maxLength(100),
                    requiredIf(() => !connectByUrl.val),
                ],
            }),
            () => div(
                { class: 'flex-row fx-gap-3 fx-align-stretch', style: 'position: relative;' },
                Input({
                    label: 'URL',
                    value: connectionUrl,
                    class: 'fx-flex',
                    name: 'url_suffix',
                    prefix: span({ style: 'white-space: nowrap; color: var(--disabled-text-color)' }, extractPrefix(dynamicConnectionUrl.val)),
                    disabled: !connectByUrl.val,
                    onChange: (value, state) => {
                        connectionUrl.val = value;
                        validityPerField['url_suffix'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        requiredIf(() => connectByUrl.val),
                    ],
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
                    {label: 'Connect with Managed Identity', value: true},
                ],
                value: connectWithIdentity,
                onChange: (value) => connectWithIdentity.val = value,
                layout: 'inline',
            }),

            () => {
                const _connectWithIdentity = connectWithIdentity.val;
                if (_connectWithIdentity) {
                    return div(
                        {class: 'flex-row p-4 fx-justify-center text-secondary'},
                        'Microsoft Entra ID credentials configured on host machine will be used',
                    );
                }

                return div(
                    {class: 'flex-column fx-gap-1'},
                    Input({
                        name: 'db_user',
                        label: 'Username',
                        value: connectionUsername,
                        onChange: (value, state) => {
                            connectionUsername.val = value;
                            validityPerField['db_user'] = state.valid;
                            isValid.val = Object.values(validityPerField).every(v => v);
                        },
                        validators: [
                            requiredIf(() => !connectWithIdentity.val),
                            maxLength(50),
                        ],
                    }),
                    Input({
                        name: 'password',
                        label: 'Password',
                        value: connectionPassword,
                        type: 'password',
                        passwordSuggestions: false,
                        placeholder: (originalConnection?.connection_id && originalConnection?.project_pw_encrypted) ? secretsPlaceholder : '',
                        onChange: (value, state) => {
                            connectionPassword.val = value;
                            validityPerField['password'] = state.valid;
                            isValid.val = Object.values(validityPerField).every(v => v);
                        },
                    }),
                )
            },
        ),
    );
};

const SynapseMSSQLForm = RedshiftForm;

const MSSQLForm = RedshiftForm;

/**
 * @param {VanState<Connection>} connection
 * @param {Flavor} flavor
 * @param {boolean} maskPassword
 * @param {(params: Partial<Connection>, isValid: boolean) => void} onChange
 * @param {Connection?} originalConnection
 * @param {VanState<string?>} dynamicConnectionUrl
 * @returns {HTMLElement}
 */
const DatabricksForm = (
    connection,
    flavor,
    onChange,
    originalConnection,
    dynamicConnectionUrl,
) => {
    const isValid = van.state(true);
    const connectByUrl = van.state(connection.rawVal?.connect_by_url ?? false);
    const connectionHost = van.state(connection.rawVal?.project_host ?? '');
    const connectionPort = van.state(connection.rawVal?.project_port || defaultPorts[flavor.flavor]);
    const connectionHttpPath = van.state(connection.rawVal?.http_path ?? '');
    const connectionDatabase = van.state(connection.rawVal?.project_db ?? '');
    const connectionUsername = van.state(connection.rawVal?.project_user ?? '');
    const connectionPassword = van.state(connection.rawVal?.project_pw_encrypted ?? '');
    const connectionUrl = van.state(connection.rawVal?.url ?? '');

    const validityPerField = {};

    van.derive(() => {
        onChange({
            project_host: connectionHost.val,
            project_port: connectionPort.val,
            project_db: connectionDatabase.val,
            project_user: connectionUsername.val,
            project_pw_encrypted: connectionPassword.val,
            http_path: connectionHttpPath.val,
            connect_by_url: connectByUrl.val,
            url: connectByUrl.val ? connectionUrl.val : connectionUrl.rawVal,
            connect_by_key: false,
        }, isValid.val);
    });

    van.derive(() => {
        const newUrlValue = (dynamicConnectionUrl.val ?? '').replace(extractPrefix(dynamicConnectionUrl.rawVal), '');
        if (!connectByUrl.rawVal) {
            connectionUrl.val = newUrlValue;
        }
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
                layout: 'inline',
            }),
            div(
                { class: 'flex-row fx-gap-3 fx-flex' },
                Input({
                    name: 'db_host',
                    label: 'Host',
                    value: connectionHost,
                    class: 'fx-flex',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionHost.val = value;
                        validityPerField['db_host'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        requiredIf(() => !connectByUrl.val),
                        maxLength(250),
                    ],
                }),
                Input({
                    name: 'db_port',
                    label: 'Port',
                    value: connectionPort,
                    type: 'number',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionPort.val = value;
                        validityPerField['db_port'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        requiredIf(() => !connectByUrl.val),
                        minLength(3),
                        maxLength(5),
                    ],
                })
            ),
            Input({
                label: 'HTTP Path',
                value: connectionHttpPath,
                class: 'fx-flex',
                name: 'http_path',
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionHttpPath.val = value;
                    validityPerField['http_path'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    requiredIf(() => !connectByUrl.val),
                    maxLength(50),
                ],
            }),
            Input({
                name: 'db_name',
                label: 'Database',
                value: connectionDatabase,
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionDatabase.val = value;
                    validityPerField['db_name'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    requiredIf(() => !connectByUrl.val),
                    maxLength(100),
                ],
            }),
            () => div(
                { class: 'flex-row fx-gap-3 fx-align-stretch', style: 'position: relative;' },
                Input({
                    label: 'URL',
                    value: connectionUrl,
                    class: 'fx-flex',
                    name: 'url_suffix',
                    prefix: span({ style: 'white-space: nowrap; color: var(--disabled-text-color)' }, extractPrefix(dynamicConnectionUrl.val)),
                    disabled: !connectByUrl.val,
                    onChange: (value, state) => {
                        connectionUrl.val = value;
                        validityPerField['url_suffix'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        requiredIf(() => connectByUrl.val),
                    ],
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
                onChange: (value, state) => {
                    connectionUsername.val = value;
                    validityPerField['db_user'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    required,
                    maxLength(50),
                ],
            }),
            Input({
                name: 'password',
                label: 'Password',
                value: connectionPassword,
                type: 'password',
                passwordSuggestions: false,
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
 * @param {(params: Partial<Connection>, fileValue: FileValue, isValid: boolean) => void} onChange
 * @param {Connection?} originalConnection
 * @param {string?} cachedFile
 * @param {VanState<string?>} dynamicConnectionUrl
 * @returns {HTMLElement}
 */
const SnowflakeForm = (
    connection,
    flavor,
    onChange,
    originalConnection,
    cachedFile,
    dynamicConnectionUrl,
) => {
    const isValid = van.state(false);
    const clearPrivateKeyPhrase = van.state(connection.rawVal?.private_key_passphrase === clearSentinel);
    const connectByUrl = van.state(connection.rawVal.connect_by_url ?? false);
    const connectByKey = van.state(connection.rawVal?.connect_by_key ?? false);
    const connectionHost = van.state(connection.rawVal.project_host ?? '');
    const connectionPort = van.state(connection.rawVal.project_port || defaultPorts[flavor.flavor]);
    const connectionDatabase = van.state(connection.rawVal.project_db ?? '');
    const connectionWarehouse = van.state(connection.rawVal.warehouse ?? '');
    const connectionUsername = van.state(connection.rawVal.project_user ?? '');
    const connectionPassword = van.state(connection.rawVal?.project_pw_encrypted ?? '');
    const connectionPrivateKey = van.state(connection.rawVal?.private_key ?? '');
    const connectionPrivateKeyPassphrase = van.state(
        clearPrivateKeyPhrase.rawVal
        ? ''
        : (connection.rawVal?.private_key_passphrase ?? '')
    );
    const connectionUrl = van.state(connection.rawVal?.url ?? '');

    const validityPerField = {};

    const privateKeyFileRaw = van.state(cachedFile);

    van.derive(() => {
        onChange({
            project_host: connectionHost.val,
            project_port: connectionPort.val,
            project_db: connectionDatabase.val,
            project_user: connectionUsername.val,
            project_pw_encrypted: connectionPassword.val,
            connect_by_url: connectByUrl.val,
            url: connectByUrl.val ? connectionUrl.val : connectionUrl.rawVal,
            connect_by_key: connectByKey.val,
            private_key: connectionPrivateKey.val,
            private_key_passphrase: clearPrivateKeyPhrase.val ? clearSentinel : connectionPrivateKeyPassphrase.val,
            warehouse: connectionWarehouse.val,
        }, privateKeyFileRaw.val, isValid.val);
    });

    van.derive(() => {
        const newUrlValue = (dynamicConnectionUrl.val ?? '').replace(extractPrefix(dynamicConnectionUrl.rawVal), '');
        if (!connectByUrl.rawVal) {
            connectionUrl.val = newUrlValue;
        }
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
                layout: 'inline',
            }),
            div(
                { class: 'flex-row fx-gap-3 fx-flex' },
                Input({
                    name: 'db_host',
                    label: 'Host',
                    value: connectionHost,
                    class: 'fx-flex',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionHost.val = value;
                        validityPerField['db_host'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        requiredIf(() => !connectByUrl.val),
                        maxLength(250),
                    ],
                }),
                Input({
                    name: 'db_port',
                    label: 'Port',
                    value: connectionPort,
                    type: 'number',
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionPort.val = value;
                        validityPerField['db_port'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        requiredIf(() => !connectByUrl.val),
                        minLength(3),
                        maxLength(5),
                    ],
                })
            ),
            Input({
                name: 'db_name',
                label: 'Database',
                value: connectionDatabase,
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionDatabase.val = value;
                    validityPerField['db_name'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    requiredIf(() => !connectByUrl.val),
                    maxLength(100),
                ],
            }),
            Input({
                name: 'warehouse',
                label: 'Warehouse',
                value: connectionWarehouse,
                disabled: connectByUrl,
                onChange: (value, state) => {
                    connectionWarehouse.val = value;
                    validityPerField['warehouse'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    maxLength(100),
                ],
            }),
            () => div(
                { class: 'flex-row fx-gap-3 fx-align-stretch', style: 'position: relative;' },
                Input({
                    label: 'URL',
                    value: connectionUrl,
                    class: 'fx-flex',
                    name: 'url_suffix',
                    prefix: span({ style: 'white-space: nowrap; color: var(--disabled-text-color)' }, extractPrefix(dynamicConnectionUrl.val)),
                    disabled: !connectByUrl.val,
                    onChange: (value, state) => {
                        connectionUrl.val = value;
                        validityPerField['url_suffix'] = state.valid;
                        isValid.val = Object.values(validityPerField).every(v => v);
                    },
                    validators: [
                        requiredIf(() => connectByUrl.val),
                    ],
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
                layout: 'inline',
            }),

            Input({
                name: 'db_user',
                label: 'Username',
                value: connectionUsername,
                onChange: (value, state) => {
                    connectionUsername.val = value;
                    validityPerField['db_user'] = state.valid;
                    isValid.val = Object.values(validityPerField).every(v => v);
                },
                validators: [
                    required,
                    maxLength(50),
                ],
            }),
            () => {
                if (connectByKey.val) {
                    const hasPrivateKeyPhrase = originalConnection?.private_key_passphrase || connectionPrivateKeyPassphrase.val;

                    return div(
                        { class: 'flex-column fx-gap-3' },
                        div(
                            { class: 'key-pair-passphrase-field'},
                            Input({
                                name: 'private_key_passphrase',
                                label: 'Private Key Passphrase',
                                value: connectionPrivateKeyPassphrase,
                                type: 'password',
                                passwordSuggestions: false,
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
                                clearable: hasPrivateKeyPhrase,
                                clearableCondition: 'always',
                                onClear: () => {
                                    clearPrivateKeyPhrase.val = true;
                                    connectionPrivateKeyPassphrase.val = '';
                                },
                            }),
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

                                validityPerField['private_key'] = isFieldValid;
                                isValid.val = Object.values(validityPerField).every(v => v);
                            },
                            validators: [
                                requiredIf(() => !originalConnection?.connection_id || !originalConnection?.private_key),
                                sizeLimit(200 * 1024 * 1024),
                            ],
                        }),
                    );
                }

                return Input({
                    name: 'password',
                    label: 'Password',
                    value: connectionPassword,
                    type: 'password',
                    passwordSuggestions: false,
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

/**
 * @param {VanState<Connection>} connection
 * @param {Flavor} flavor
 * @param {(params: Partial<Connection>, fileValue: FileValue, isValid: boolean) => void} onChange
 * @param {Connection?} originalConnection
 * @param {string?} originalConnection
 * @param {FileValue?} cachedFile
 * @returns {HTMLElement}
 */
const BigqueryForm = (
    connection,
    flavor,
    onChange,
    originalConnection,
    cachedFile,
) => {
    const isValid = van.state(false);
    const serviceAccountKey = van.state(connection.rawVal.service_account_key ?? null);
    const projectId = van.state("");
    const serviceAccountKeyFileRaw = van.state(cachedFile);

    const validityPerField = {};

    van.derive(() => {
        projectId.val = serviceAccountKey.val?.project_id ?? '';
        isValid.val = !!projectId.val;
    });

    van.derive(() => {
        onChange({ service_account_key: serviceAccountKey.val, project_db: projectId.val }, serviceAccountKeyFileRaw.val, isValid.val);
    });

    return div(
        {class: 'flex-column fx-gap-3 fx-flex'},
        div(
            { class: 'flex-column border border-radius-1 p-3 mt-1 fx-gap-1', style: 'position: relative;' },
            Caption({content: 'Service Account Key', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),

            () => {
                return div(
                    { class: 'flex-column fx-gap-3' },
                    FileInput({
                        name: 'service_account_key',
                        label: 'Upload service account key (.json)',
                        placeholder: (originalConnection?.connection_id && originalConnection?.service_account_key)
                            ? 'Drop file here or browse files to replace existing key'
                            : undefined,
                        value: serviceAccountKeyFileRaw,
                        onChange: (value, state) => {
                            let isFieldValid = state.valid;
                            try {
                                if (value?.content) {
                                    serviceAccountKey.val = JSON.parse(atob(value.content.split(',')?.[1] ?? ''));
                                }
                            } catch (err) {
                                console.error(err);
                                isFieldValid = false;
                            }
                            serviceAccountKeyFileRaw.val = value;
                            validityPerField['service_account_key'] = isFieldValid;
                            isValid.val = Object.values(validityPerField).every(v => v);
                        },
                        validators: [
                            requiredIf(() => !originalConnection?.connection_id || !originalConnection?.service_account_key),
                            sizeLimit(20 * 1024),
                        ],
                    }),
                );
            },

            div(
                { class: 'text-caption text-right' },
                () => `Project ID: ${projectId.val}`,
            ),
        ),
    );
};

function extractPrefix(url) {
    if (!url) {
        return '';
    }

    if (url.includes('@')) {
        const parts = url.split('@');
        if (!parts[0]) {
            return '';
        }
        return `${parts[0]}@`;
    }

    return url.slice(0, url.indexOf('://') + 3);
}

function shouldRefreshUrl(previous, current) {
    if (current.connect_by_url) {
        return false;
    }

    const fields = ['sql_flavor', 'project_host', 'project_port', 'project_db', 'project_user', 'connect_by_key', 'http_path', 'warehouse', 'connect_with_identity'];
    return fields.some((fieldName) => previous[fieldName] !== current[fieldName]);
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
