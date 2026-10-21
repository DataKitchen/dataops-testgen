/**
 * @typedef Comparison
 * @type {object}
 * @property {string} label
 * @property {number} source
 * @property {number} target
 *
 * @typedef DiscardData
 * @type {object}
 * @property {string} question
 * @property {string} warning
 * @property {string} confirmation
 * @property {Comparison} compare
 * @property {{success: boolean, message: string}?} result
 *
 * @typedef Properties
 * @type {object}
 * @property {DiscardData?} data - reactive: set to open the dialog, null to close it
 * @property {(() => void)} onDiscard
 * @property {((comparison: Comparison) => void)?} onCompare
 * @property {(() => void)?} onClose
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { Alert } from './alert.js';
import { Button } from './button.js';
import { Dialog } from './dialog.js';
import { Link } from './link.js';
import { Toggle } from './toggle.js';

const { div, span } = van.tags;

const DiscardDraftDialog = (/** @type Properties */ props) => {
    const open = van.state(false);
    const data = van.state(null);
    const confirmed = van.state(false);

    van.derive(() => {
        const raw = getValue(props.data) ?? null;
        data.val = raw;
        open.val = !!raw;
    });

    const result = van.derive(() => data.val?.result ?? null);

    const onClose = () => {
        confirmed.val = false;
        open.val = false;
        props.onClose?.();
    };

    return Dialog(
        { title: 'Discard Draft', open, onClose, width: '36rem' },
        () => {
            if (!open.val) {
                return '';
            }
            const d = data.rawVal;
            return div(
                { class: 'flex-column fx-gap-4', 'data-testid': 'discard-draft-dialog' },
                span(d.question),
                Alert(
                    { type: 'warn' },
                    div(
                        { class: 'flex-column fx-gap-1' },
                        span(d.warning),
                        Link({
                            href: '',
                            label: d.compare.label,
                            right_icon: 'chevron_right',
                            right_icon_size: 18,
                            onClick: (event) => {
                                event.preventDefault();
                                props.onCompare?.(d.compare);
                            },
                        }),
                    ),
                ),
                Toggle({
                    name: 'confirm-discard-draft',
                    label: d.confirmation,
                    checked: confirmed,
                    onChange: (value) => confirmed.val = value,
                }),
                () => {
                    const outcome = result.val;
                    return outcome && !outcome.success
                        ? Alert({ type: 'error', icon: 'error' }, span(outcome.message))
                        : '';
                },
                div(
                    { class: 'flex-row fx-justify-content-flex-end' },
                    () => Button({
                        type: confirmed.val ? 'flat' : 'stroked',
                        color: confirmed.val ? 'warn' : 'basic',
                        label: 'Discard',
                        width: 'auto',
                        disabled: !confirmed.val,
                        onclick: () => props.onDiscard(),
                    }),
                ),
            );
        },
    );
};

export { DiscardDraftDialog };
