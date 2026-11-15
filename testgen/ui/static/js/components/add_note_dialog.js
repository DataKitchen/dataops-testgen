/**
 * @typedef Properties
 * @type {object}
 * @property {object?} target - reactive: set to open the dialog for a selection, null to close it
 * @property {(target: object) => (Node | string)} summary - what the note will be added to
 * @property {(text: string, target: object) => void} onAdd
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { Button } from './button.js';
import { Dialog } from './dialog.js';
import { Textarea } from './textarea.js';

const { div } = van.tags;

const AddNoteDialog = (/** @type Properties */ props) => {
    const open = van.state(false);
    const text = van.state('');

    van.derive(() => {
        const target = getValue(props.target) ?? null;
        open.val = !!target;
        if (target) text.val = '';
    });

    const close = () => {
        if (props.target?.val !== undefined) props.target.val = null;
        open.val = false;
    };

    return Dialog(
        { title: 'Add Note', open, onClose: close, width: '36rem' },
        () => {
            const target = getValue(props.target);
            if (!open.val || !target) return '';
            return div(
                { class: 'flex-column fx-gap-4', 'data-testid': 'add-note-dialog' },
                div(props.summary(target)),
                Textarea({
                    name: 'bulk_note',
                    label: 'Note',
                    value: text,
                    height: 120,
                    onChange: (value) => { text.val = value; },
                }),
                div(
                    { class: 'flex-row fx-justify-flex-end fx-gap-2' },
                    Button({ type: 'stroked', color: 'basic', label: 'Cancel', width: 'auto', onclick: close }),
                    Button({
                        type: 'flat',
                        color: 'primary',
                        label: 'Add Note',
                        width: 'auto',
                        disabled: () => !text.val.trim(),
                        onclick: () => {
                            const note = text.val.trim();
                            close();
                            props.onAdd(note, target);
                        },
                    }),
                ),
            );
        },
    );
};

export { AddNoteDialog };
