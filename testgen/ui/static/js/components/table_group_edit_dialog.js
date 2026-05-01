/**
 * @import { Connection } from './connection_form.js'
 * @import { TableGroup } from './table_group_form.js'
 * @import { TableGroupPreview } from './table_group_test.js'
 *
 * @typedef EditResult
 * @type {object}
 * @property {boolean} success
 * @property {string?} message
 *
 * @typedef Properties
 * @type {object}
 * @property {object} dialog
 * @property {Connection[]} connections
 * @property {TableGroup} table_group
 * @property {boolean} is_in_use
 * @property {TableGroupPreview?} table_group_preview
 * @property {EditResult?} result
 */
import van from '../van.min.js';
import { Dialog } from './dialog.js';
import { TableGroupForm } from './table_group_form.js';
import { TableGroupTest } from './table_group_test.js';
import { getValue } from '../utils.js';
import { Button } from './button.js';
import { Alert } from './alert.js';

const { div, span } = van.tags;

/**
 * Two-phase edit dialog: form → verify → save.
 * No wizard stepper — just shows/hides the form and verify panels.
 *
 * @param {Properties} props
 */
const TableGroupEditDialog = (props) => {
    const emit = props.emit;
    const dialogProp = getValue(props.dialog);
    const dialogOpen = van.state(dialogProp?.open === true);
    van.derive(() => { if (getValue(props.dialog)?.open) dialogOpen.val = true; });

    const connections = (props.connections?.rawVal ?? getValue(props.connections)) ?? [];
    const tableGroupState = van.state(getValue(props.table_group));
    const formValid = van.state(false);

    // Phase: 'form' or 'verify'
    const phase = van.state('form');

    const tableGroupPreview = van.state(getValue(props.table_group_preview));
    van.derive(() => {
        const renewed = getValue(props.table_group_preview);
        if (phase.rawVal === 'verify') {
            tableGroupPreview.val = renewed;
        }
    });
    const verified = van.derive(() => tableGroupPreview.val?.success === true);

    const form = TableGroupForm({
        connections,
        tableGroup: getValue(props.table_group),
        showConnectionSelector: connections.length > 1,
        disableConnectionSelector: false,
        disableSchemaField: getValue(props.is_in_use) ?? false,
        onChange: (updatedTableGroup, state) => {
            tableGroupState.val = updatedTableGroup;
            formValid.val = state.valid;
        },
    });

    const onClose = () => {
        dialogOpen.val = false;
        emit('CloseEditClicked', {});
    };

    const goToVerify = () => {
        phase.val = 'verify';
        emit('PreviewEditTableGroupClicked', {
            payload: { table_group: tableGroupState.val },
        });
    };

    const goBackToForm = () => {
        phase.val = 'form';
        tableGroupPreview.val = null;
    };

    const dialogTitle = van.derive(() => getValue(props.dialog)?.title ?? 'Edit Table Group');

    return Dialog(
        {
            title: dialogTitle,
            open: dialogOpen,
            onClose,
            width: '50rem',
        },
        div(
            { class: 'flex-column fx-gap-3' },
            // Form phase
            div(
                { style: () => phase.val === 'form' ? '' : 'display:none' },
                form,
            ),
            // Verify phase
            div(
                { style: () => phase.val === 'verify' ? '' : 'display:none' },
                TableGroupTest(tableGroupPreview, {
                    onVerifyAccess: () => {
                        emit('PreviewEditTableGroupClicked', {
                            payload: {
                                table_group: tableGroupState.val,
                                verify_access: true,
                            },
                        });
                    },
                }),
            ),
            // Error display
            () => {
                const result = getValue(props.result);
                if (!result || result.success !== false) return '';
                return Alert({ type: 'error' }, span(result.message));
            },
            // Buttons
            div(
                { class: 'flex-row fx-gap-3' },
                // Back button (verify phase only)
                () => phase.val === 'verify'
                    ? Button({
                        type: 'stroked',
                        color: 'basic',
                        label: 'Previous',
                        width: 'auto',
                        style: 'margin-right: auto;',
                        onclick: goBackToForm,
                    })
                    : '',
                // Next / Save button
                () => phase.val === 'form'
                    ? Button({
                        type: 'stroked',
                        color: 'primary',
                        label: 'Next',
                        width: 'auto',
                        style: 'margin-left: auto;',
                        disabled: !formValid.val,
                        onclick: goToVerify,
                    })
                    : Button({
                        type: 'flat',
                        color: 'primary',
                        label: 'Save',
                        width: 'auto',
                        style: 'margin-left: auto;',
                        disabled: !verified.val,
                        onclick: () => emit('SaveEditTableGroupClicked', {
                            payload: { table_group: tableGroupState.val },
                        }),
                    }),
            ),
        ),
    );
};

export { TableGroupEditDialog };
