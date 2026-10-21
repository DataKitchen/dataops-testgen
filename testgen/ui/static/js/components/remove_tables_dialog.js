/**
 * @typedef RemoveTablesData
 * @type {object}
 * @property {string} question
 * @property {string} warning
 *
 * @typedef Properties
 * @type {object}
 * @property {RemoveTablesData?} data - reactive: set to open the dialog, null to close it
 * @property {(() => void)} onRemove
 * @property {(() => void)?} onClose
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { Alert } from './alert.js';
import { Button } from './button.js';
import { Dialog } from './dialog.js';

const { div, span } = van.tags;

const RemoveTablesDialog = (/** @type Properties */ props) => {
    const open = van.state(false);
    const data = van.state(null);

    van.derive(() => {
        const raw = getValue(props.data) ?? null;
        data.val = raw;
        open.val = !!raw;
    });

    const onClose = () => {
        open.val = false;
        props.onClose?.();
    };

    return Dialog(
        { title: 'Remove Tables', open, onClose, width: '36rem' },
        () => {
            if (!open.val) {
                return '';
            }
            const d = data.rawVal;
            return div(
                { class: 'flex-column fx-gap-4', 'data-testid': 'remove-tables-dialog' },
                span(d.question),
                Alert({ type: 'warn' }, span(d.warning)),
                div(
                    { class: 'flex-row fx-justify-content-flex-end' },
                    Button({
                        type: 'flat',
                        color: 'warn',
                        label: 'Remove',
                        width: 'auto',
                        onclick: () => props.onRemove(),
                    }),
                ),
            );
        },
    );
};

export { RemoveTablesDialog };
