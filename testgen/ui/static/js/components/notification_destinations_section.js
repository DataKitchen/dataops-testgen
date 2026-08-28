/**
 * @import {VanState} from '/app/static/js/van.min.js';
 */
import van from '/app/static/js/van.min.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Button } from '/app/static/js/components/button.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Input } from '/app/static/js/components/input.js';
import { Select } from '/app/static/js/components/select.js';
import { Table } from '/app/static/js/components/table.js';
import { Textarea } from '/app/static/js/components/textarea.js';
import { required } from '/app/static/js/form_validators.js';
import { getValue } from '/app/static/js/utils.js';

const { div, span } = van.tags;

const DESTINATION_TYPE_OPTIONS = [
    { value: 'email', label: 'Email' },
];

const DESTINATION_TYPE_LABELS = {
    email: 'Email',
};

/**
 * Split raw recipient input on commas, semicolons, newlines, and spaces; drop empties.
 * De-duplicate while preserving order.
 */
const parseRecipients = (raw) => {
    if (!raw) return [];
    const seen = new Set();
    const out = [];
    for (const token of raw.split(/[,;\s]+/)) {
        const trimmed = token.trim();
        if (trimmed && !seen.has(trimmed)) {
            seen.add(trimmed);
            out.push(trimmed);
        }
    }
    return out;
};

/**
 * @typedef Destination
 * @type {object}
 * @property {string} id
 * @property {string} name
 * @property {string} destination_type
 * @property {string[]} recipients
 * @property {string} target_summary
 * @property {number} rule_count
 *
 * @typedef Properties
 * @type {object}
 * @property {VanState<Destination[]>} destinations
 * @property {VanState<boolean>} smtp_configured
 *
 * @param {Properties} props
 * @param {(event: string, detail?: object) => void} emit
 */
const NotificationDestinationsSection = (props, emit) => {
    const destinations = van.derive(() => getValue(props.destinations) ?? []);
    const smtpConfigured = van.derive(() => !!getValue(props.smtp_configured));
    const hasEmailDestination = van.derive(() =>
        destinations.val.some((d) => d.destination_type === 'email')
    );
    const showSmtpWarn = van.derive(() => !smtpConfigured.val && hasEmailDestination.val);

    const showFormDialog = van.state(false);
    const editingDestination = van.state(/** @type {Destination | null} */ (null));
    const deletingDestination = van.state(/** @type {Destination | null} */ (null));

    const openAddDialog = () => {
        editingDestination.val = null;
        showFormDialog.val = true;
    };
    const openEditDialog = (destination) => {
        editingDestination.val = destination;
        showFormDialog.val = true;
    };
    const openDeleteDialog = (destination) => {
        deletingDestination.val = destination;
    };

    const tableRows = van.derive(() =>
        destinations.val.map((destination) => ({
            name: span(destination.name),
            destination_type: span(DESTINATION_TYPE_LABELS[destination.destination_type] ?? destination.destination_type),
            target_summary: span(
                { style: 'overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block;' },
                destination.target_summary || '--',
            ),
            rule_count: span(destination.rule_count > 0 ? String(destination.rule_count) : '--'),
            actions: div(
                { class: 'flex-row', style: 'justify-content: center; gap: 4px;' },
                Button({
                    type: 'icon',
                    icon: 'edit',
                    tooltip: 'Edit destination',
                    onclick: () => openEditDialog(destination),
                }),
                Button({
                    type: 'icon',
                    icon: 'delete',
                    tooltip: 'Delete destination',
                    color: 'warn',
                    onclick: () => openDeleteDialog(destination),
                }),
            ),
        }))
    );

    return div(
        { class: 'flex-column fx-gap-2' },
        div(
            { class: 'flex-row fx-justify-space-between fx-align-flex-end' },
            span({ class: 'body m' }, 'Notification Destinations'),
            Button({
                type: 'stroked',
                icon: 'add',
                label: 'Add Destination',
                color: 'primary',
                width: 'auto',
                style: 'background: var(--button-generic-background-color);',
                onclick: openAddDialog,
            }),
        ),
        () => showSmtpWarn.val
            ? Alert(
                { type: 'warn', icon: 'warning', class: 'mb-0' },
                'Email destinations cannot deliver until an email server is configured.',
            )
            : '',
        Table(
            {
                columns: [
                    { name: 'name', label: 'Name', width: 200, align: 'left' },
                    { name: 'destination_type', label: 'Type', width: 100, align: 'left' },
                    { name: 'target_summary', label: 'Sends To', width: 320, align: 'left', overflow: true },
                    { name: 'rule_count', label: 'Rules', width: 80, align: 'left' },
                    { name: 'actions', label: '', width: 80, align: 'center' },
                ],
                emptyState: div(
                    { class: 'flex-row fx-justify-center empty-table-message' },
                    span({ class: 'text-secondary' }, 'No notification destinations yet'),
                ),
                class: 'notification-destinations-table',
                height: 'auto',
                maxHeight: '400px',
            },
            tableRows,
            emit,
        ),
        Dialog(
            {
                title: van.derive(() => editingDestination.val ? 'Edit Destination' : 'Add Destination'),
                open: showFormDialog,
                width: '32rem',
                onClose: () => { showFormDialog.val = false; },
            },
            // The form is mounted on each dialog open with a snapshot of the
            // destination being edited (or ``null`` for add). ``rawVal`` reads
            // deliberately do NOT track ``editingDestination`` / ``destinations`` as
            // dependencies of this binding -- if they did, any state change while
            // the dialog is open would remount the form and wipe the user's input.
            () => {
                if (!showFormDialog.val) return '';
                const editing = editingDestination.rawVal;
                return DestinationForm({
                    destination: editing,
                    existingNames: destinations.rawVal
                        .filter((d) => d.id !== editing?.id)
                        .map((d) => d.name),
                    onCancel: () => { showFormDialog.val = false; },
                    onConfirm: (payload) => {
                        showFormDialog.val = false;
                        if (editing) {
                            emit('EditDestinationClicked', { payload: { id: editing.id, ...payload } });
                        } else {
                            emit('AddDestinationClicked', { payload });
                        }
                    },
                });
            },
        ),
        Dialog(
            {
                title: 'Delete Destination',
                open: van.derive(() => deletingDestination.val !== null),
                width: '28rem',
                onClose: () => { deletingDestination.val = null; },
            },
            () => {
                const target = deletingDestination.val;
                if (!target) return '';
                return DeleteConfirmation({
                    destination: target,
                    onCancel: () => { deletingDestination.val = null; },
                    onConfirm: () => {
                        deletingDestination.val = null;
                        emit('DeleteDestinationClicked', { payload: { id: target.id } });
                    },
                });
            },
        ),
    );
};

/**
 * @param {{
 *   destination: Destination | null,
 *   existingNames: string[],
 *   onCancel: () => void,
 *   onConfirm: (payload: object) => void,
 * }} props
 */
const DestinationForm = (props) => {
    const { destination, existingNames, onCancel, onConfirm } = props;
    const isEdit = destination !== null;

    const nameState = van.state(destination?.name ?? '');
    const nameValid = van.state(!!(destination?.name ?? ''));
    const typeState = van.state(destination?.destination_type ?? 'email');
    const recipientsState = van.state((destination?.recipients ?? []).join(', '));
    const recipientsValid = van.state((destination?.recipients ?? []).length > 0);

    const existingNamesLower = existingNames.map((n) => n.toLowerCase());
    const nameNotUnique = van.derive(() =>
        existingNamesLower.includes(nameState.val.trim().toLowerCase())
    );

    const saveDisabled = van.derive(() =>
        !nameValid.val
        || nameNotUnique.val
        || !recipientsValid.val
    );

    return div(
        { class: 'flex-column fx-gap-3' },
        Input({
            label: 'Destination name',
            value: nameState,
            validators: [required],
            onChange: (value, validity) => {
                nameState.val = value;
                nameValid.val = validity.valid;
            },
        }),
        () => nameNotUnique.val
            ? Alert(
                { type: 'error', icon: 'error', class: 'mb-0' },
                'A destination with this name already exists.',
            )
            : '',
        Select({
            label: 'Destination type',
            value: typeState,
            options: DESTINATION_TYPE_OPTIONS,
            allowNull: false,
            onChange: (value) => { typeState.val = value; },
        }),
        () => typeState.val === 'email'
            ? Textarea({
                label: 'Recipients',
                value: recipientsState,
                help: 'List of email addresses, separated by commas or newlines',
                validators: [required],
                onChange: (value, validity) => {
                    recipientsState.val = value;
                    recipientsValid.val = validity.valid && parseRecipients(value).length > 0;
                },
            })
            : '',
        div(
            { class: 'flex-row fx-justify-content-flex-end fx-gap-2' },
            Button({
                type: 'stroked',
                label: 'Cancel',
                width: 'auto',
                onclick: onCancel,
            }),
            Button({
                type: 'flat',
                color: 'primary',
                label: isEdit ? 'Save' : 'Add Destination',
                width: 'auto',
                disabled: saveDisabled,
                onclick: () => onConfirm({
                    name: nameState.rawVal.trim(),
                    destination_type: typeState.rawVal,
                    recipients: parseRecipients(recipientsState.rawVal),
                }),
            }),
        ),
    );
};

/**
 * @param {{
 *   destination: Destination,
 *   onCancel: () => void,
 *   onConfirm: () => void,
 * }} props
 */
const DeleteConfirmation = (props) => {
    const { destination, onCancel, onConfirm } = props;
    const ruleCount = destination.rule_count ?? 0;

    return div(
        { class: 'flex-column fx-gap-3' },
        span(`Delete destination "${destination.name}"?`),
        ruleCount > 0
            ? Alert(
                { type: 'warn', icon: 'warning', class: 'mb-0' },
                ruleCount === 1
                    ? '1 notification rule uses this destination and will also be deleted.'
                    : `${ruleCount} notification rules use this destination and will also be deleted.`,
            )
            : '',
        div(
            { class: 'flex-row fx-justify-content-flex-end fx-gap-2' },
            Button({
                type: 'stroked',
                label: 'Cancel',
                width: 'auto',
                onclick: onCancel,
            }),
            Button({
                type: 'flat',
                color: 'warn',
                label: 'Delete',
                width: 'auto',
                onclick: onConfirm,
            }),
        ),
    );
};

export { NotificationDestinationsSection, parseRecipients };
