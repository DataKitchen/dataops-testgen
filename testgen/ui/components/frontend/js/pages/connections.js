/**
 * @import { Connection, Flavor } from '../components/connection_form.js';
 * 
 * @typedef Results
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * 
 * @typedef Permissions
 * @type {object}
 * @property {boolean} is_admin
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} project_code
 * @property {Connection} connection
 * @property {boolean} has_table_groups
 * @property {Array<Flavor>} flavors
 * @property {Permissions} permissions
 * @property {Results?} results
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange, getValue, emitEvent } from '../utils.js';
import { ConnectionForm } from '../components/connection_form.js';
import { Button } from '../components/button.js';
import { Link } from '../components/link.js';
import { Alert } from '../components/alert.js';

const { div, span } = van.tags;

/**
 * 
 * @param {Properties} props 
 * @returns 
 */
const Connections = (props) => {
    loadStylesheet('connections', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const wrapperId = 'connections-list-wrapper';
    const projectCode = getValue(props.project_code);
    const connection = getValue(props.connection);
    const connectionId = connection.connection_id;
    const updatedConnection = van.state(connection);
    const formState = van.state({dirty: false, valid: false});

    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return div(
        { id: wrapperId, class: 'flex-column fx-gap-4' },
        div(
            { class: 'flex-row fx-justify-content-flex-end' },
            () => getValue(props.has_table_groups)
                ? Link({
                    href: 'table-groups',
                    params: {'project_code': projectCode, "connection_id": connectionId},
                    label: 'Manage Table Groups',
                    right_icon: 'chevron_right',
                    class: 'tg-connections--link',
                })
                : Button({
                    type: 'stroked',
                    color: 'primary',
                    icon: 'table_view',
                    label: 'Setup Table Groups',
                    width: 'auto',
                    disabled: !getValue(props.permissions).is_admin,
                    tooltip: 'You do not have permissions to perform this action. Contact your administrator.',
                    onclick: () => emitEvent('SetupTableGroupClicked', {}),
                }),
        ),
        div(
            { class: 'flex-column fx-gap-4 p-4' },
            ConnectionForm(
                {
                    connection: props.connection,
                    flavors: props.flavors,
                    disableFlavor: false,
                    onChange: (connection, state) => {
                        formState.val = state;
                        updatedConnection.val = connection;
                    },
                },
                () => {
                    const hasSavePermission = getValue(props.permissions).is_admin;
                    if (!hasSavePermission) {
                        return '';
                    }

                    const formState_ = formState.val;
                    const canSave = formState_.dirty && formState_.valid;
                    return Button({
                        label: 'Save',
                        color: 'primary',
                        type: 'flat',
                        width: 'auto',
                        disabled: !canSave,
                        onclick: () => emitEvent('SaveConnectionClicked', { payload: updatedConnection.val }),
                    });
                },
            ),
            () => {
                const results = getValue(props.results) ?? {};
                return Object.keys(results).length > 0
                    ? Alert({ type: results.success ? 'success' : 'error' }, span(results.message))
                    : '';
            },
        ),
    );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-connections--link {
    margin-left: auto;
    border-radius: 4px;
    background: var(--dk-card-background);
    border: var(--button-stroked-border);
    padding: 8px 8px 8px 16px;
    color: var(--primary-color) !important;
}
`);

export { Connections };
