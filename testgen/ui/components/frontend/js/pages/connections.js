/**
 * @import { Connection, Flavor } from '/app/static/js/components/connection_form.js';
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
 * @property {string?} generated_connection_url
 * @property {Results?} results
 */
import van from '/app/static/js/van.min.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { ConnectionForm } from '/app/static/js/components/connection_form.js';
import { TableGroupWizard } from '/app/static/js/components/table_group_wizard.js';
import { Button } from '/app/static/js/components/button.js';
import { Link } from '/app/static/js/components/link.js';
import { Alert } from '/app/static/js/components/alert.js';

const { div, span } = van.tags;

/**
 * 
 * @param {Properties} props 
 * @returns 
 */
const Connections = (props) => {
    const { emit } = props;
    loadStylesheet('connections', stylesheet);

    const wrapperId = 'connections-list-wrapper';
    const projectCode = getValue(props.project_code);
    const connection = getValue(props.connection);
    const connectionId = connection.connection_id;
    const updatedConnection = van.state(connection);
    const formState = van.state({dirty: false, valid: false});


    return div(
        { id: wrapperId, 'data-testid': 'connections', class: 'flex-column fx-gap-4' },
        div(
            { class: 'flex-row fx-justify-content-flex-end' },
            () => getValue(props.has_table_groups)
                ? Link({ emit, 
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
                    tooltip: () => !getValue(props.permissions).is_admin ? 'You do not have permissions to perform this action. Contact your administrator.' : '',
                    onclick: () => emit('SetupTableGroupClicked', {}),
                }),
        ),
        div(
            { class: 'flex-column fx-gap-4 p-4' },
            ConnectionForm(
                {
                    emit,
                    connection: props.connection,
                    flavors: props.flavors,
                    disableFlavor: false,
                    dynamicConnectionUrl: props.generated_connection_url,
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
                        onclick: () => emit('SaveConnectionClicked', { payload: updatedConnection.val }),
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
        () => {
            const wizardData = getValue(props.setup_wizard);
            if (!wizardData) return div();
            return TableGroupWizard(wizardData, emit);
        },
    );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-connections--link {
    margin-left: auto;
    border-radius: 4px;
    background: var(--button-generic-background-color);
    border: var(--button-stroked-border);
    padding: 8px 8px 8px 16px;
    color: var(--primary-color) !important;
}
`);

export { Connections };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, Connections(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
