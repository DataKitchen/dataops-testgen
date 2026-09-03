/**
 * @typedef Properties
 * @type {object}
 * @property {object|null} preview
 * @property {object|null} result
 * @property {object} behavior
 * @property {object} deleteConfirmed
 * @property {object} fileValue
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

const BEHAVIOR_OPTIONS = [
    {
        label: 'Add and update tests',
        value: 'upsert',
        caption: 'Create tests from the file and update matching ones. Locked tests are left alone.',
    },
    {
        label: 'Update existing tests only',
        value: 'update_only',
        caption: 'Update matching tests. Nothing is created.',
    },
    {
        label: 'Add new tests only',
        value: 'insert_only',
        caption: 'Create tests that do not already exist. Matching tests are left alone.',
    },
    {
        label: 'Promote from another environment',
        value: 'promote',
        caption: 'Create and update tests, and lock what is created so test generation does not overwrite it.',
    },
    {
        label: 'Replace all tests in this test suite',
        value: 'replace',
        caption: 'Create and update tests from the file, and delete every test that is not in it.',
    },
];

const { div, span } = van.tags;

const ImportTestDefinitionsDialog = (/** @type Properties */ props) => {
    const emit = props.emit;
    loadStylesheet('import-test-definitions-dialog', stylesheet);

    const behavior = props.behavior;
    const deleteConfirmed = props.deleteConfirmed;
    const fileValue = props.fileValue;
    let autoCloseScheduled = false;

    const requestPreview = () => {
        if (fileValue.val?.content) {
            const payload = { content: fileValue.val.content, behavior: behavior.val };
            if (props.onFileUploaded) {
                props.onFileUploaded(payload);
            } else {
                emit('FileUploaded', { payload });
            }
        }
    };

    return div(
        { class: 'flex-column fx-gap-4' },
        FileInput({
            name: 'test_definitions_file',
            label: 'Upload test definitions JSON file',
            help: 'Use the Export menu on this page to download the current test definitions JSON as a starting point.',
            validators: [sizeLimit(JSON_SIZE_LIMIT)],
            value: fileValue,
            onChange: (value) => {
                // FileInput replays onChange when it mounts. The caller owns fileValue, so on a
                // rebuild that replay arrives holding the same file and would re-request a preview.
                if (value === fileValue.val) {
                    return;
                }
                const hadFile = fileValue.val?.content;
                fileValue.val = value;
                deleteConfirmed.val = false;
                if (value?.content) {
                    requestPreview();
                } else if (hadFile) {
                    if (props.onFileCleared) {
                        props.onFileCleared();
                    } else {
                        emit('FileCleared', {});
                    }
                }
            },
        }),
        Select({
            label: 'Behavior',
            value: behavior,
            options: BEHAVIOR_OPTIONS,
            allowNull: false,
            onChange: (value) => {
                behavior.val = value;
                deleteConfirmed.val = false;
                requestPreview();
            },
        }),
        () => {
            const result = getValue(props.result);
            if (result) {
                if (result.success && props.onAutoClose && !autoCloseScheduled) {
                    autoCloseScheduled = true;
                    setTimeout(() => props.onAutoClose(), 2000);
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
                        disabled: nothingToDo || (deleting && !deleteConfirmed.val),
                        onclick: () => props.onImportConfirmed
                            ? props.onImportConfirmed()
                            : emit('ImportConfirmed', {}),
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
