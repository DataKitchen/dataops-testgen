/**
 * @typedef Properties
 * @type {object}
 * @property {string} title
 * @property {object} content
 * @property {object} editingContent
 * @property {function} onSave
 * @property {function?} onCancel
 * @property {function?} hasChanges
 */
import { getValue } from '../utils.js';
import van from '../van.min.js';
import { Card } from './card.js';
import { Button } from './button.js';

const { div } = van.tags;

const EditableCard = (/** @type Properties */ props) => {
    const editing = van.state(false);
    const onCancel = van.derive(() => {
        const cancelFunction = props.onCancel?.val ?? props.onCancel;
        return () => {
            editing.val = false;
            cancelFunction?.();
        }
    });
    const saveDisabled = van.derive(() => {
        const hasChanges = props.hasChanges?.val ?? props.hasChanges;
        return !hasChanges?.();
    });

    return Card({
        title: props.title,
        content: [
            () => editing.val ? getValue(props.editingContent) : getValue(props.content),
            () => editing.val ? div(
                { class: 'flex-row fx-justify-content-flex-end fx-gap-3 mt-4' },
                Button({
                    type: 'stroked',
                    label: 'Cancel',
                    width: 'auto',
                    onclick: onCancel,
                }),
                Button({
                    type: 'stroked',
                    color: 'primary',
                    label: 'Save',
                    width: 'auto',
                    disabled: saveDisabled,
                    onclick: props.onSave,
                }),
            ) : '',
        ],
        actionContent: () => !editing.val ? Button({
            type: 'stroked',
            label: 'Edit',
            icon: 'edit',
            width: 'auto',
            onclick: () => editing.val = true,
        }) : '',
    });
};

export { EditableCard };
