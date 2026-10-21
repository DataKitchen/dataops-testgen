/**
 * @typedef ImportData
 * @type {object}
 * @property {number} max_file_bytes
 * @property {object?} preview - an ImportPreview, as ContractImportPreview takes it
 * @property {{success: boolean, message: string}?} result
 *
 * @typedef FilePayload
 * @type {object}
 * @property {string} name
 * @property {number} size
 * @property {string} content
 *
 * @typedef Properties
 * @type {object}
 * @property {ImportData?} data - reactive: set to open the dialog, null to close it
 * @property {((file: FilePayload) => void)} onFileUploaded
 * @property {(() => void)} onFileCleared
 * @property {((deleteConfirmed: boolean) => void)} onImport
 * @property {(() => void)?} onClose
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { sizeLimit } from '../form_validators.js';
import { Alert } from './alert.js';
import { Button } from './button.js';
import { ContractImportPreview } from './contract_import_preview.js';
import { Dialog } from './dialog.js';
import { FileInput } from './file_input.js';

const { div, span } = van.tags;

const ImportContractDialog = (/** @type Properties */ props) => {
    const open = van.state(false);
    const data = van.state(null);
    const fileValue = van.state(null);
    const deleteConfirmed = van.state(false);
    let autoCloseTimer = null;

    van.derive(() => {
        const raw = getValue(props.data) ?? null;
        data.val = raw;
        open.val = !!raw;
    });

    const preview = van.derive(() => data.val?.preview ?? null);
    const result = van.derive(() => data.val?.result ?? null);

    const onClose = () => {
        clearTimeout(autoCloseTimer);
        autoCloseTimer = null;
        fileValue.val = null;
        deleteConfirmed.val = false;
        open.val = false;
        props.onClose?.();
    };

    return Dialog(
        { title: 'Import Contract', open, onClose, width: '60rem' },
        () => {
            if (!open.val) {
                return '';
            }
            return div(
                { class: 'flex-column fx-gap-3', 'data-testid': 'import-contract-dialog' },
                FileInput({
                    label: 'ODCS contract file',
                    name: 'contract-file',
                    // Read without subscribing: FileInput reads its value while it is built, and a subscription would
                    // remount it empty whenever onChange below writes fileValue, losing a validation error.
                    value: fileValue.rawVal,
                    validators: [sizeLimit(data.rawVal.max_file_bytes)],
                    onChange: (value, state) => {
                        // FileInput replays onChange on mount with the value it was given.
                        if (value === fileValue.val) {
                            return;
                        }
                        const hadFile = !!fileValue.val;
                        const accepted = value?.content && state?.valid !== false ? value : null;
                        fileValue.val = accepted;
                        deleteConfirmed.val = false;
                        if (accepted) {
                            props.onFileUploaded({ name: accepted.name, size: accepted.size, content: accepted.content });
                        } else if (hadFile) {
                            props.onFileCleared();
                        }
                    },
                }),
                span(
                    { class: 'text-caption' },
                    'The contract is replaced by the file: terms not in the file are deleted.',
                ),
                ContractImportPreview({ preview, deleteConfirmed }),
                () => {
                    const outcome = result.val;
                    if (!outcome) {
                        return '';
                    }
                    if (outcome.success && !autoCloseTimer) {
                        autoCloseTimer = setTimeout(onClose, 2000);
                    }
                    return Alert(
                        { type: outcome.success ? 'success' : 'error', icon: outcome.success ? 'check_circle' : 'error' },
                        span(outcome.message),
                    );
                },
                div(
                    { class: 'flex-row fx-justify-flex-end' },
                    Button({
                        type: 'stroked',
                        color: 'primary',
                        icon: 'upload',
                        label: 'Import Contract',
                        width: 'auto',
                        disabled: () => {
                            const current = preview.val;
                            return !current || !!current.error || !!result.val?.success
                                || (current.summary?.delete > 0 && !deleteConfirmed.val);
                        },
                        onclick: () => props.onImport(deleteConfirmed.val),
                    }),
                ),
            );
        },
    );
};

export { ImportContractDialog };
