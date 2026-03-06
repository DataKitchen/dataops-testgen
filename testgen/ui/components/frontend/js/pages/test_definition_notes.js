/**
 * @typedef Note
 * @type {object}
 * @property {string} id
 * @property {string} detail
 * @property {string} created_by
 * @property {string?} created_at
 * @property {string?} updated_at
 *
 * @typedef Properties
 * @type {object}
 * @property {{table: string, column: string, test: string}} test_label
 * @property {Array<Note>} notes
 * @property {string} current_user
 */
import van from '../van.min.js';
import { Button } from '../components/button.js';
import { Icon } from '../components/icon.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { ExpansionPanel } from '../components/expansion_panel.js';
import { formatTimestamp } from '../display_utils.js';

const minHeight = 400;
const { div, span, textarea, p } = van.tags;

/**
 * @param {Properties} props
 * @returns
 */
const TestDefinitionNotes = (props) => {
    loadStylesheet('test-definition-notes', stylesheet);
    window.testgen.isPage = true;

    // Form state: shared between add and edit modes
    const editNoteId = van.state(null);
    const noteText = van.state('');
    const isEdit = van.state(false);

    const resetForm = () => {
        editNoteId.val = null;
        noteText.val = '';
        isEdit.val = false;
    };

    /**
     * @param {Note} note
     * @param {string} currentUser
     * @returns
     */
    const NoteItem = (note, currentUser) => {
        const confirmingDelete = van.state(false);
        const isOwner = note.created_by === currentUser;

        return div(
            { class: () => `tdn-note ${isEdit.val && editNoteId.val === note.id ? 'tdn-editing' : ''}` },
            div(
                { class: 'flex-row fx-gap-2' },
                span({ class: 'text-bold text-small' }, `@${note.created_by}`),
                span({ class: 'tdn-note-separator' }, '\u2014'),
                span({ class: 'tdn-note-date' },
                    formatTimestamp(new Date(note.created_at), true),
                    note.updated_at ? ' (edited)' : '',
                ),
                isOwner ? div(
                    { class: 'tdn-note-actions' },
                    () => {
                        if (isEdit.val && editNoteId.val === note.id) {
                            return div(
                                { class: 'flex-row fx-gap-1 fx-align-center' },
                                Icon({ size: 18, classes: 'tdn-editing-indicator' }, 'edit'),
                                span({ class: 'tdn-editing-indicator text-caption' }, 'Editing'),
                            );
                        }
                        if (confirmingDelete.val) {
                            return div(
                                { class: 'flex-row fx-gap-1 fx-align-center' },
                                span({ class: 'text-caption' }, 'Delete?'),
                                Button({
                                    label: 'Yes',
                                    type: 'stroked',
                                    color: 'warn',
                                    onclick: () => emitEvent('NoteDeleted', { payload: { id: note.id } }),
                                }),
                                Button({
                                    label: 'No',
                                    type: 'stroked',
                                    color: 'basic',
                                    onclick: () => { confirmingDelete.val = false; },
                                }),
                            );
                        }
                        return div(
                            { class: 'flex-row fx-gap-1' },
                            Button({
                                type: 'icon',
                                icon: 'edit',
                                tooltip: 'Edit note',
                                onclick: () => {
                                    isEdit.val = true;
                                    editNoteId.val = note.id;
                                    noteText.val = note.detail;
                                },
                            }),
                            Button({
                                type: 'icon',
                                icon: 'delete',
                                tooltip: 'Delete note',
                                tooltipPosition: 'top-left',
                                onclick: () => { confirmingDelete.val = true; },
                            }),
                        );
                    },
                ) : null,
            ),
            p({ class: 'tdn-note-detail' }, note.detail),
        );
    };

    return div(
        { id: 'test-definition-notes', class: 'flex-column fx-gap-2', style: 'height: 100%; overflow-y: auto;' },
        () => {
            const label = getValue(props.test_label);
            return div(
                { class: 'flex-row fx-flex-wrap fx-gap-1' },
                span({ class: 'text-secondary' }, 'Table: '), span(label.table),
                span({ class: 'tdn-separator' }, '|'),
                span({ class: 'text-secondary' }, 'Column: '), span(label.column),
                span({ class: 'tdn-separator' }, '|'),
                span({ class: 'text-secondary' }, 'Test: '), span(label.test),
            );
        },
        () => ExpansionPanel(
            {
                title: isEdit.val
                    ? span({ class: 'tdn-editing-indicator' }, 'Edit Note')
                    : span({ class: 'text-green' }, 'Add Note'),
                expanded: isEdit.val || getValue(props.notes).length === 0,
            },
            div(
                { class: 'flex-column' },
                textarea({
                    class: 'tdn-form-textarea',
                    placeholder: 'Type a note...',
                    value: noteText,
                    oninput: (e) => noteText.val = e.target.value,
                    rows: 3,
                }),
                div(
                    { class: 'flex-row fx-justify-content-flex-end fx-gap-2 mt-3' },
                    () => isEdit.val
                        ? Button({
                            type: 'stroked',
                            label: 'Cancel',
                            width: 'auto',
                            onclick: resetForm,
                        })
                        : '',
                    Button({
                        type: 'stroked',
                        label: isEdit.val ? 'Save Changes' : 'Add Note',
                        width: 'auto',
                        disabled: () => !noteText.val.trim(),
                        onclick: () => {
                            const text = noteText.rawVal.trim();
                            if (isEdit.rawVal) {
                                const id = editNoteId.rawVal;
                                resetForm();
                                emitEvent('NoteUpdated', { payload: { id, text } });
                            } else {
                                resetForm();
                                emitEvent('NoteAdded', { payload: { text } });
                            }
                        },
                    }),
                ),
            ),
        ),
        () => {
            const notes = getValue(props.notes);
            const currentUser = getValue(props.current_user);
            Streamlit.setFrameHeight(Math.max(minHeight, 80 * notes.length + 200));

            return notes.length > 0
                ? div(
                    { class: 'flex-column fx-gap-2' },
                    ...notes.map(note => NoteItem(note, currentUser)),
                )
                : div(
                    { class: 'flex-column fx-gap-2 fx-align-flex-center mt-7 text-secondary' },
                    span({ class: 'text-large' }, 'No notes yet'),
                    span('Document context, decisions, or issues related to this test definition.'),
                );
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tdn-separator {
    color: var(--disabled-text-color);
    margin: 0 4px;
}
.tdn-form-textarea {
    box-sizing: border-box;
    width: 100%;
    border-radius: 8px;
    border: 1px solid transparent;
    transition: border-color 0.3s;
    background-color: var(--form-field-color);
    padding: 8px 12px;
    color: var(--primary-text-color);
    font-family: inherit;
    font-size: 14px;
    resize: vertical;
}
.tdn-form-textarea:focus,
.tdn-form-textarea:focus-visible {
    outline: none;
    border-color: var(--primary-color);
}
.tdn-form-textarea::placeholder {
    font-style: italic;
    color: var(--disabled-text-color);
}
.tdn-note {
    padding: 4px 12px 12px;
    border-radius: 8px;
    background-color: var(--app-background-color);
}
@media (prefers-color-scheme: dark) {
    .tdn-note {
        background-color: var(--dk-card-background);
    }
}
.tdn-note.tdn-editing {
    background-color: var(--select-hover-background);
}
.tdn-editing-indicator {
    color: var(--purple);
}
.tdn-note-separator {
    color: var(--disabled-text-color);
    font-size: 12px;
}
.tdn-note-date {
    font-size: 12px;
    color: var(--secondary-text-color);
}
.tdn-note-actions {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-left: auto;
    gap: 2px;
}
.tdn-note-detail {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
    color: var(--primary-text-color);
    white-space: pre-wrap;
}
`);

export { TestDefinitionNotes };
