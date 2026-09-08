/**
 * @typedef Properties
 * @type {object}
 * @property {object|null} preview
 * @property {object|null} result
 * @property {string?} fileName
 * @property {object} onNew
 * @property {object} onMatch
 * @property {object} onAbsence
 * @property {object} deleteConfirmed
 * @property {object} fileValue
 * @property {object} autoCloseTimer
 * @property {Function} onFileUploaded
 * @property {Function} onPolicyChanged
 * @property {Function} onFileCleared
 * @property {Function} onImportConfirmed
 * @property {Function?} onAutoClose
 */
import van from '/app/static/js/van.min.js';
import { getValue, loadStylesheet } from '/app/static/js/utils.js';
import { Select } from '/app/static/js/components/select.js';
import { FileInput } from '/app/static/js/components/file_input.js';
import { Button } from '/app/static/js/components/button.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Icon } from '/app/static/js/components/icon.js';
import { Table } from '/app/static/js/components/table.js';
import { Toggle } from '/app/static/js/components/toggle.js';
import { withTooltip } from '/app/static/js/components/tooltip.js';
import { sizeLimit } from '/app/static/js/form_validators.js';

const JSON_SIZE_LIMIT = 10 * 1024 * 1024; // 10 MB

// The service's three policy axes, the same ones the REST and MCP surfaces take.
const POLICY_OPTIONS = {
    onNew: [
        {
            label: 'Create',
            value: 'create',
            caption: 'Add the test to this test suite.',
        },
        {
            label: 'Create and lock',
            value: 'create_and_lock',
            caption: 'Add the test and lock it, so test generation does not overwrite its values.',
        },
        {
            label: 'Do not create',
            value: 'skip',
            caption: 'Leave the test out of this test suite.',
        },
    ],
    onMatch: [
        {
            label: 'Update unlocked tests',
            value: 'overwrite_unlocked',
            caption: 'Overwrite matching tests. Locked tests are skipped.',
        },
        {
            label: 'Update all tests',
            value: 'overwrite_all',
            caption: 'Overwrite matching tests, including locked ones.',
        },
        {
            label: 'Do not update',
            value: 'skip',
            caption: 'Leave matching tests as they are.',
        },
    ],
    onAbsence: [
        {
            label: 'Leave alone',
            value: 'do_nothing',
            caption: 'Keep tests that are not in the file.',
        },
        {
            label: 'Delete unlocked tests',
            value: 'delete_unlocked',
            caption: 'Permanently delete tests that are not in the file. Locked tests are kept.',
        },
        {
            label: 'Delete all tests',
            value: 'delete_all',
            caption: 'Permanently delete tests that are not in the file, including locked ones.',
        },
    ],
};

const { div, span } = van.tags;

const ImportTestDefinitionsDialog = (/** @type Properties */ props) => {
    const emit = props.emit;
    loadStylesheet('import-test-definitions-dialog', stylesheet);

    const { onNew, onMatch, onAbsence, deleteConfirmed, fileValue, autoCloseTimer } = props;

    const policy = () => ({
        on_new: onNew.val,
        on_match: onMatch.val,
        on_absence: onAbsence.val,
    });

    const PolicySelect = (label, stateKey) => div(
        { class: 'fx-flex' },
        Select({
            label,
            value: props[stateKey],
            options: POLICY_OPTIONS[stateKey],
            allowNull: false,
            onChange: (value) => {
                props[stateKey].val = value;
                deleteConfirmed.val = false;
                // Python still holds the uploaded document, so a policy change asks it to
                // reproject rather than shipping the file back up.
                if (fileValue.val?.content || getValue(props.fileName)) {
                    props.onPolicyChanged(policy());
                }
            },
        }),
    );

    return div(
        { class: 'flex-column fx-gap-4' },
        FileInput({
            name: 'test_definitions_file',
            label: 'Upload test definitions JSON file',
            help: 'Use the Export menu on this page to download the current test definitions JSON as a starting point.',
            validators: [sizeLimit(JSON_SIZE_LIMIT)],
            value: fileValue,
            onChange: (value, state) => {
                // FileInput replays onChange when it mounts. The caller owns fileValue, so on a
                // rebuild that replay arrives holding the same file and would re-request a preview.
                if (value === fileValue.val) {
                    return;
                }
                const hadFile = fileValue.val?.content;
                // A file that fails a validator is held as nothing at all. Keeping it would
                // leave the picker naming one document while Python still holds the previous
                // one armed, and the import applies what Python holds.
                const accepted = value?.content && state?.valid !== false ? value : null;
                fileValue.val = accepted;
                deleteConfirmed.val = false;
                if (accepted) {
                    props.onFileUploaded({ content: accepted.content, file_name: accepted.name, ...policy() });
                } else if (hadFile) {
                    props.onFileCleared();
                }
            },
        }),
        () => {
            const armedName = getValue(props.fileName);
            return !fileValue.val?.content && armedName
                ? span(
                    { class: 'text-caption text-secondary' },
                    `Using the previously uploaded file ${armedName}. Upload another file to replace it.`,
                )
                : '';
        },
        div(
            { class: 'flex-row fx-gap-3' },
            PolicySelect('Tests in the file with no match', 'onNew'),
            PolicySelect('Tests in the file that match', 'onMatch'),
            PolicySelect('Tests not in the file', 'onAbsence'),
        ),
        span(
            { class: 'text-caption text-secondary' },
            'Only the fields present in the file are written. A matching test keeps its existing values for anything the file omits.',
        ),
        () => {
            const result = getValue(props.result);
            if (result) {
                if (result.success && props.onAutoClose && !autoCloseTimer.val) {
                    autoCloseTimer.val = setTimeout(() => props.onAutoClose(), 2000);
                }
                return Alert(
                    { type: result.success ? 'success' : 'error', icon: result.success ? 'check_circle' : 'error' },
                    span(result.message),
                );
            }

            const preview = getValue(props.preview);
            if (!preview) {
                return '';
            }

            if (preview.error) {
                return Alert({ type: 'error', icon: 'error' }, span(preview.error));
            }

            const summary = preview.summary ?? {};
            const previewToken = preview.token;
            const deleting = summary.deleted > 0;
            const nothingToDo = !(summary.created || summary.updated || summary.deleted);

            return div(
                { class: 'flex-column fx-gap-3' },
                span({ class: 'text-secondary' }, summaryText(summary)),
                PreviewTable(preview, emit),
                preview.truncated
                    ? Alert(
                        { type: 'info', icon: 'info' },
                        span(`Showing the first ${preview.preview_rows.length} of ${preview.total_rows} test definitions. Every one of them is included in this import.`),
                    )
                    : null,
                deleting
                    ? Alert(
                        { type: 'warn', icon: 'warning' },
                        span(`${plural(summary.deleted, 'test')} in this test suite ${summary.deleted === 1 ? 'is' : 'are'} not in the file and will be permanently deleted.`),
                    )
                    : null,
                deleting
                    ? Toggle({
                        name: 'confirm-delete-test-definitions',
                        label: `Yes, delete the ${plural(summary.deleted, 'test')} that ${summary.deleted === 1 ? 'is' : 'are'} not in the file.`,
                        checked: deleteConfirmed,
                        onChange: (value) => deleteConfirmed.val = value,
                    })
                    : null,
                div(
                    { class: 'flex-row fx-justify-content-flex-end' },
                    Button({
                        type: 'stroked',
                        color: 'primary',
                        label: 'Import Tests',
                        icon: 'upload',
                        width: 'auto',
                        // A function, so the button owns the deleteConfirmed dependency. Read
                        // eagerly it would belong to this child and rebuild the whole preview
                        // table on every toggle click.
                        disabled: () => nothingToDo || (deleting && !deleteConfirmed.val),
                        onclick: () => props.onImportConfirmed({
                            delete_confirmed: deleteConfirmed.val,
                            preview_token: previewToken,
                        }),
                    }),
                ),
            );
        },
    );
};

const plural = (count, word) => `${count} ${count === 1 ? word : word + 's'}`;

const summaryText = (summary) => {
    const actions = [
        summary.created ? `create ${plural(summary.created, 'test')}` : '',
        summary.updated ? `update ${plural(summary.updated, 'test')}` : '',
        summary.deleted ? `delete ${plural(summary.deleted, 'test')}` : '',
    ].filter(Boolean);
    const main = actions.length
        ? `This import will ${actions.join(', ')}`
        : 'This import will not change any test definitions';
    const skipped = summary.skipped ? `${plural(summary.skipped, 'test')} skipped` : '';
    return [main, skipped].filter(Boolean).join(' | ');
};

const ACTION_ICONS = {
    create: 'add_circle',
    update: 'edit',
    skip: 'block',
    delete: 'remove_circle',
};

const ACTION_CLASSES = {
    create: 'text-green',
    update: 'text-purple',
    skip: 'text-disabled',
    delete: 'text-error',
};

const PreviewTable = (preview, emit) => {
    const columns = [
        { name: '_action_icon', label: '', width: 32, overflow: 'visible', align: 'center' },
        { name: 'test_name', label: 'Test type', width: 170, align: 'left' },
        { name: 'table_name', label: 'Table', width: 170, align: 'left' },
        { name: 'column_name', label: 'Column', width: 170, align: 'left' },
    ];

    const rows = (preview.preview_rows ?? []).map(row => {
        const icon = Icon(
            { size: 18, classes: `${ACTION_CLASSES[row.action_code] ?? ''} display-table-cell` },
            ACTION_ICONS[row.action_code] ?? 'help',
        );

        return {
            ...row,
            _action_icon: withTooltip(icon, { text: `${row.action}: ${row.reason}`, position: 'right', width: 200 }),
        };
    });

    return Table(
        {
            emit,
            columns,
            height: 'auto',
            maxHeight: '300px',
            highDensity: true,
            rowClass: (row) => `td-import-row-${row.action_code}`,
        },
        rows,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.td-import-row-skip > td {
    color: var(--disabled-text-color);
    background-color: rgba(0, 0, 0, 0.03);
}

.td-import-row-delete > td {
    background-color: color-mix(in srgb, var(--error-color) 5%, transparent);
}

@media (prefers-color-scheme: dark) {
    .td-import-row-skip > td {
        background-color: rgba(255, 255, 255, 0.03);
    }
}
`);

export { ImportTestDefinitionsDialog };
