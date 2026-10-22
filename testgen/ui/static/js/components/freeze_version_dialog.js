/**
 * @typedef FreezeResult
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * @property {string[]} problems
 *
 * @typedef FreezeData
 * @type {object}
 * @property {string} title
 * @property {string} question
 * @property {string} consequence
 * @property {FreezeResult?} result
 *
 * @typedef Properties
 * @type {object}
 * @property {FreezeData?} data - reactive: set to open the dialog, null to close it
 * @property {((label: string) => void)} onFreeze
 * @property {(() => void)?} onClose
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { Alert } from './alert.js';
import { Button } from './button.js';
import { Dialog } from './dialog.js';
import { Icon } from './icon.js';
import { Input } from './input.js';

const { div, li, span, ul } = van.tags;

const FreezeVersionDialog = (/** @type Properties */ props) => {
    const open = van.state(false);
    const data = van.state(null);
    const label = van.state('');

    van.derive(() => {
        const raw = getValue(props.data) ?? null;
        data.val = raw;
        open.val = !!raw;
        if (!raw) {
            label.val = '';
        }
    });

    const title = van.derive(() => data.val?.title ?? '');
    const result = van.derive(() => data.val?.result ?? null);

    const onClose = () => {
        label.val = '';
        open.val = false;
        props.onClose?.();
    };

    return Dialog(
        { title, open, onClose, width: '36rem' },
        () => {
            if (!open.val) {
                return '';
            }
            const d = data.rawVal;
            return div(
                { class: 'flex-column fx-gap-3', 'data-testid': 'freeze-version-dialog' },
                span(d.question),
                span({ class: 'text-secondary' }, d.consequence),
                div(
                    { class: 'flex-column fx-gap-1' },
                    Input({
                        name: 'version-label',
                        label: 'Label',
                        value: label.rawVal,
                        onChange: (value) => label.val = value,
                    }),
                    span({ class: 'text-caption' }, 'Optional'),
                ),
                () => {
                    const outcome = result.val;
                    return outcome && !outcome.success
                        ? Alert(
                            { type: 'error', icon: 'error' },
                            div(
                                { class: 'flex-column' },
                                span(outcome.message),
                                outcome.problems?.length
                                    ? ul({ class: 'mt-1 mb-0 pl-4' }, outcome.problems.map((problem) => li(problem)))
                                    : null,
                            ),
                        )
                        : '';
                },
                div(
                    { class: 'flex-row fx-justify-space-between fx-align-flex-center mt-2' },
                    div(
                        { class: 'flex-row fx-gap-1' },
                        Icon({ size: 16 }, 'info'),
                        span({ class: 'text-caption' }, 'Freezing cannot be undone.'),
                    ),
                    Button({
                        type: 'stroked',
                        color: 'primary',
                        icon: 'ac_unit',
                        label: 'Freeze Version',
                        width: 'auto',
                        onclick: () => props.onFreeze(label.val),
                    }),
                ),
            );
        },
    );
};

export { FreezeVersionDialog };
