/**
 * @typedef Flavor
 * @type {object}
 * @property {string} label
 * @property {string} value
 * @property {string} icon
 * @property {string} flavor
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
 * @property {string} password
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
 * @typedef Properties
 * @type {object}
 * @property {Connection} connection
 * @property {Array.<Flavor>} flavors
 * @property {boolean} disableFlavor
 * @property {(c: Connection, state: FormState) => void} onChange
 */
import van from '../van.min.js';
import { Button } from './button.js';
import { Alert } from './alert.js';
import { getValue, emitEvent, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange, isEqual } from '../utils.js';
import { Input } from './input.js';
import { Slider } from './slider.js';
import { Checkbox } from './checkbox.js';
import { Select } from './select.js';
import { maxLength, minLength, sizeLimit } from '../form_validators.js';
import { RadioGroup } from './radio_group.js';
import { FileInput } from './file_input.js';

const { div, hr, span } = van.tags;
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

    window.connectionFormConnection = props.connection;

    const connection = getValue(props.connection);
    const isEditMode = !!connection?.connection_id;
    const defaultPort = defaultPorts[connection?.sql_flavor];

    const connectionFlavor = van.state(connection?.sql_flavor_code);
    const connectionName = van.state(connection?.connection_name);
    const connectionHost = van.state(connection?.project_host);
    const connectionPort = van.state(connection?.project_port ?? defaultPort);
    const connectionDatabase = van.state(connection?.project_db);
    const connectionUsername = van.state(connection?.project_user);
    const connectionPassword = van.state(connection?.password);
    const connectionMaxThreads = van.state(connection?.max_threads ?? 4);
    const connectionQueryChars = van.state(connection?.max_query_chars ?? 9000);
    const connectByUrl = van.state(connection?.connect_by_url ?? false);
    const connectByKey = van.state(connection?.connect_by_key ?? false);
    const privateKey = van.state(connection?.private_key);
    const privateKeyPhrase = van.state(connection?.private_key_passphrase);
    const httpPath = van.state(connection?.http_path);

    if (isEditMode) {
        connectionPassword.val = '';
        privateKey.val = '';
        privateKeyPhrase.val = '';
    }

    const connectionUrl = connection?.url ?? '';
    let connectionStringPrefix = van.state('');
    let connectionStringSuffix = van.state(connectionUrl);
    if (connectionUrl.includes('@')) {
        const [prefixPart, sufixPart] = connectionUrl.split('@');
        connectionStringPrefix = van.state(prefixPart);
        connectionStringSuffix = van.state(sufixPart ?? '');
    }

    const updatedConnection = van.derive(() => {
        let privateKeyValue = privateKey.val ?? '';
        if (privateKeyValue) {
            privateKeyValue = privateKeyValue.content?.split(',')?.[1] ?? '';
        }

        return {
            project_code: connection.project_code,
            connection_id: connection.connection_id,
            sql_flavor: connection?.sql_flavor ?? undefined,
            sql_flavor_code: connectionFlavor.val ?? '',
            connection_name: connectionName.val ?? '',
            project_host: connectionHost.val ?? '',
            project_port: connectionPort.val ?? '',
            project_db: connectionDatabase.val ?? '',
            project_user: connectionUsername.val ?? '',
            password: connectionPassword.val ?? '',
            max_threads: connectionMaxThreads.val ?? 4,
            max_query_chars: connectionQueryChars.val ?? 9000,
            connect_by_url: connectByUrl.val ?? false,
            url: connectionStringSuffix.val,
            connect_by_key: connectByKey.val ?? false,
            private_key: privateKeyValue,
            private_key_passphrase: privateKeyPhrase.val ?? '',
            http_path: httpPath.val ?? '',
        };
    });
    const dirty = van.derive(() => !isEqual(updatedConnection.val, connection));
    const validityPerField = van.state({});

    van.derive(() => {
        const fieldsValidity = validityPerField.val;
        const isValid = Object.keys(fieldsValidity).length > 0 &&
            Object.values(fieldsValidity).every(v => v);
        props.onChange?.(updatedConnection.val, { dirty: dirty.val, valid: isValid });
    });

    const setFieldValidity = (field, validity) => {
        validityPerField.val = {...validityPerField.val, [field]: validity};
    }

    const authenticationForms = {
        redshift: () => PasswordConnectionForm(
            connection,
            connectionPassword,
            (value, state) => {
                connectionPassword.val = value;
                setFieldValidity('password', state.valid);
            },
            isEditMode,
        ),
        mssql: () => PasswordConnectionForm(
            connection,
            connectionPassword,
            (value, state) => {
                connectionPassword.val = value;
                setFieldValidity('password', state.valid);
            },
            isEditMode,
        ),
        postgresql: () => PasswordConnectionForm(
            connection,
            connectionPassword,
            (value, state) => {
                connectionPassword.val = value;
                setFieldValidity('password', state.valid);
            },
            isEditMode,
        ),
        snowflake: () => KeyPairConnectionForm(
            connection,
            connectByKey,
            connectionPassword,
            privateKey,
            privateKeyPhrase,
            (value, state) => {
                connectByKey.val = value.connect_by_key;
                connectionPassword.val = value.password;
                privateKey.val = value.private_key;
                privateKeyPhrase.val = value.private_key_passphrase;
                setFieldValidity('key_pair_form', state.valid);
            },
            isEditMode,
        ),
        databricks: () => HttpPathConnectionForm(
            connection,
            connectionPassword,
            httpPath,
            (value, state) => {
                connectionPassword.val = value.password;
                httpPath.val = value.http_path;
                setFieldValidity('http_path_form', state.valid);
            },
            isEditMode,
        ),
    };
    const authenticationForm = van.derive(() => {
        const selectedFlavorCode = connectionFlavor.val;
        const flavor = getValue(props.flavors).find(f => f.value === selectedFlavorCode);
        return authenticationForms[flavor.flavor]();
    });

    van.derive(() => {
        const selectedFlavorCode = connectionFlavor.val;
        const previousFlavorCode = connectionFlavor.oldVal;
        const isCustomPort = connectionPort.rawVal !== defaultPorts[previousFlavorCode];
        if (selectedFlavorCode !== previousFlavorCode && (!isCustomPort || !connectionPort.rawVal)) {
            connectionPort.val = defaultPorts[selectedFlavorCode];
        }
    });

    return div(
        { class: 'flex-column fx-gap-3 fx-align-stretch', style: 'overflow-y: auto;' },
        div(
            { class: 'flex-row fx-gap-3 fx-align-stretch' },
            div(
                { class: 'flex-column fx-gap-3', style: 'flex: 2' },
                Select({
                    label: 'Database Type',
                    value: connectionFlavor,
                    options: props.flavors,
                    disabled: props.disableFlavor,
                    height: 38,
                    help: 'Type of database server to connect to. This determines the database driver and SQL dialect that will be used by TestGen.',
                    testId: 'sql_flavor',
                    onChange: (value) => connectionFlavor.val = value,
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
                            setFieldValidity('db_host', state.valid);
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
                            setFieldValidity('db_port', state.valid);
                        },
                        validators: [ minLength(3), maxLength(5) ],
                    }),
                ),
                Input({
                    name: 'db_name',
                    label: 'Database',
                    value: connectionDatabase,
                    height: 38,
                    disabled: connectByUrl,
                    onChange: (value, state) => {
                        connectionDatabase.val = value;
                        setFieldValidity('db_name', state.valid);
                    },
                    validators: [ maxLength(100) ],
                }),
                Input({
                    name: 'db_user',
                    label: 'Username',
                    value: connectionUsername,
                    height: 38,
                    onChange: (value, state) => {
                        connectionUsername.val = value;
                        setFieldValidity('db_user', state.valid);
                    },
                    validators: [ maxLength(50) ],
                }),
            ),
            div(
                { class: 'flex-column fx-gap-3', style: 'padding: 2px; flex: 1;' },
                Slider({
                    label: 'Max Threads (Advanced Tuning)',
                    hint: 'Maximum number of concurrent threads that run tests. Default values should be retained unless test queries are failing.',
                    value: connectionMaxThreads,
                    min: 1,
                    max: 8,
                    onChange: (value) => connectionMaxThreads.val = value,
                }),
                Slider({
                    label: 'Max Expression Length (Advanced Tuning)',
                    hint: 'Some tests are consolidated into queries for maximum performance. Default values should be retained unless test queries are failing.',
                    value: connectionQueryChars,
                    min: 500,
                    max: 14000,
                    onChange: (value) => connectionQueryChars.val = value,
                }),
            ),
        ),
        authenticationForm,
        hr({ style: 'width: 100%;', class: 'mt-2 mb-2' }),
        Checkbox({
            name: 'connect_by_url',
            label: 'URL Override',
            help: 'When checked, the connection string will be driven by the field below, along with the username and password from the fields above',
            checked: connectByUrl.val,
            onChange: (checked) => connectByUrl.val = checked,
        }),
        () => {
            const connectByUrl_ = getValue(connectByUrl);

            if (!connectByUrl_) {
                return '';
            }

            if (connectionStringPrefix.val === '') {
                connectionStringPrefix.val = `${connectionFlavor.rawVal}://<username>:<password>`;
            }

            return div(
                { class: 'flex-row fx-gap-3 fx-align-stretch' },
                Input({
                    label: 'URL Prefix',
                    disabled: true,
                    value: connectionStringPrefix,
                    height: 38,
                    width: 255,
                    name: 'url_prefix',
                }),
                Input({
                    label: 'URL Suffix',
                    value: connectionStringSuffix,
                    class: 'fx-flex',
                    height: 38,
                    name: 'url_suffix',
                    onChange: (value, state) => connectionStringSuffix.val = value,
                }),
            );
        },
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

const PasswordConnectionForm = (connection, password, onValueChange, useSecretsPlaceholder) => {
    return div(
        { class: 'flex-row fx-gap-3 fx-align-stretch' },
        div(
            { class: 'flex-column fx-gap-3', style: 'flex: 2' },
            Input({
                name: 'password',
                label: 'Password',
                value: password,
                height: 38,
                type: 'password',
                placeholder: (useSecretsPlaceholder && connection.password) ? secretsPlaceholder : '',
                onChange: onValueChange,
            }),
        ),
        div(
            { class: 'flex-column fx-gap-3', style: 'padding: 2px; flex: 1;' },
            '',
        ),
    );
};

const HttpPathConnectionForm = (
    connection,
    password,
    httpPath,
    onValueChange,
    useSecretsPlaceholder,
) => {
    const passwordFieldState = van.state({value: password.val, valid: false});
    const httpPathFieldState = van.state({value: httpPath.val, valid: false});

    van.derive(() => {
        const passwordField = passwordFieldState.val;
        const httpPathField = httpPathFieldState.val;
        onValueChange({password: passwordField.value, http_path: httpPathField.value}, { valid: passwordField.valid && httpPathField.valid });
    });

    return div(
        { class: 'flex-row fx-gap-3 fx-align-stretch' },
        div(
            { class: 'flex-column fx-gap-3', style: 'flex: 2' },
            Input({
                name: 'password',
                label: 'Password',
                value: password,
                height: 38,
                type: 'password',
                placeholder: (useSecretsPlaceholder && connection.password) ? secretsPlaceholder : '',
                onChange: (value, state) => passwordFieldState.val = {value, valid: state.valid},
            }),
            Input({
                label: 'HTTP Path',
                value: httpPath,
                class: 'fx-flex',
                height: 38,
                name: 'http_path',
                onChange: (value, state) => httpPathFieldState.val = {value, valid: state.valid},
                validators: [ maxLength(50) ],
            })
        ),
        div(
            { class: 'flex-column fx-gap-3', style: 'padding: 2px; flex: 1;' },
            '',
        ),
    );
};

const KeyPairConnectionForm = (
    connection,
    connectByKey,
    password,
    privateKey,
    privateKeyPhrase,
    onValueChange,
    useSecretsPlaceholder,
) => {
    const connectByKeyFieldState = van.state({value: connectByKey.val, valid: true});
    const passwordFieldState = van.state({value: password.val, valid: true});
    const privateKeyFieldState = van.state({value: privateKey.val, valid: true});
    const privateKeyPhraseFieldState = van.state({value: privateKeyPhrase.val, valid: true});

    van.derive(() => {
        const connectByKeyField = connectByKeyFieldState.val;
        const passwordField = passwordFieldState.val;
        const privateKeyField = privateKeyFieldState.val;
        const privateKeyPhraseField = privateKeyPhraseFieldState.val;

        let isValid = passwordField.valid;
        if (connectByKeyField.value) {
            isValid = privateKeyField.valid && privateKeyPhraseField.valid;
        }

        onValueChange(
            {
                connect_by_key: connectByKeyField.value,
                password: passwordField.value,
                private_key: privateKeyField.value,
                private_key_passphrase: privateKeyPhraseField.value,
            },
            { valid: isValid },
        );
    });

    return div(
        { class: 'flex-column' },
        hr({ style: 'width: 100%;', class: 'mt-2 mb-2' }),
        RadioGroup({
            label: 'Connection Strategy',
            options: [
                {label: 'Connect By Password', value: false},
                {label: 'Connect By Key-Pair', value: true},
            ],
            value: connectByKey,
            onChange: (value) => connectByKeyFieldState.val = {value, valid: true},
        }),
        () => {
            if (connectByKey.val) {
                return div(
                    { class: 'flex-column fx-gap-3' },
                    Input({
                        name: 'private_key_passphrase',
                        label: 'Private Key Passphrase',
                        value: privateKeyPhrase,
                        height: 38,
                        type: 'password',
                        help: 'Passphrase used when creating the private key. Leave empty if the private key is not encrypted.',
                        placeholder: (useSecretsPlaceholder && connection.private_key_passphrase) ? secretsPlaceholder : '',
                        onChange: (value, state) => privateKeyPhraseFieldState.val = {value, valid: state.valid},
                    }),
                    FileInput({
                        name: 'private_key',
                        label: 'Upload private key (rsa_key.p8)',
                        placeholder: connection.private_key ? 'Drop file here or browse files to replace existing key' : undefined,
                        value: privateKey,
                        onChange: (value, state) => privateKeyFieldState.val = {value, valid: state.valid},
                        validators: [
                            sizeLimit(200 * 1024 * 1024),
                        ],
                    }),
                );
            }

            return Input({
                name: 'password',
                label: 'Password',
                value: password,
                height: 38,
                type: 'password',
                placeholder: (useSecretsPlaceholder && connection.password) ? secretsPlaceholder : '',
                onChange: (value, state) => passwordFieldState.val = {value, valid: state.valid},
            });
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
`);

export { ConnectionForm };
