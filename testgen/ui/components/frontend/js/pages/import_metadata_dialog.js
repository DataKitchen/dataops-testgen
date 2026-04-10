/**
 * @typedef Properties
 * @type {object}
 * @property {object|null} preview
 * @property {object|null} result
 * @property {Function?} onAutoClose
 */
import van from '/app/static/js/van.min.js';
import { getValue, loadStylesheet} from '/app/static/js/utils.js';
import { RadioGroup } from '/app/static/js/components/radio_group.js';
import { FileInput } from '/app/static/js/components/file_input.js';
import { Button } from '/app/static/js/components/button.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Table } from '/app/static/js/components/table.js';
import { capitalize } from '/app/static/js/display_utils.js';
import { withTooltip } from '/app/static/js/components/tooltip.js';
import { sizeLimit } from '/app/static/js/form_validators.js';

const CSV_SIZE_LIMIT = 2 * 1024 * 1024; // 2 MB

const { div, i, span } = van.tags;

const ImportMetadataDialog = (/** @type Properties */ props) => {
    const emit = props.emit;
    loadStylesheet('import-metadata-dialog', stylesheet);

    const blankBehavior = van.state('keep');
    const fileValue = van.state(null);
    let autoCloseScheduled = false;

    return div(
        { class: 'flex-column fx-gap-4' },
        FileInput({
            name: 'csv_file',
            label: 'Upload metadata CSV file',
            help: 'Use the Export menu on the Data Catalog page to download the current metadata as a CSV template.',
            validators: [sizeLimit(CSV_SIZE_LIMIT)],
            value: fileValue,
            onChange: (value) => {
                const hadFile = fileValue.val?.content;
                fileValue.val = value;
                if (value?.content) {
                    const payload = { content: value.content, blank_behavior: blankBehavior.val };
                    if (props.onFileUploaded) {
                        props.onFileUploaded(payload);
                    } else {
                        emit('FileUploaded', { payload });
                    }
                } else if (hadFile) {
                    if (props.onFileCleared) {
                        props.onFileCleared();
                    } else {
                        emit('FileCleared', {});
                    }
                }
            },
        }),
        RadioGroup({
            label: 'When CSV values are blank',
            help: 'Controls whether blank cells in the CSV overwrite existing metadata or leave it unchanged.',
            options: [
                { label: 'Keep existing values', value: 'keep' },
                { label: 'Clear existing values', value: 'clear' },
            ],
            value: blankBehavior,
            onChange: (value) => blankBehavior.val = value,
            layout: 'default',
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

            const hasError = !!preview.error;
            const tableCount = hasError ? 0 : (preview.table_count || 0);
            const columnCount = hasError ? 0 : (preview.column_count || 0);
            const skippedCount = hasError ? 0 : (preview.skipped_count || 0);
            const hasMatches = tableCount + columnCount > 0;

            const plural = (n, word) => `${n} ${n === 1 ? word : word + 's'}`;
            const importedParts = [
                tableCount ? plural(tableCount, 'table') : '',
                columnCount ? plural(columnCount, 'column') : '',
            ].filter(Boolean);
            const importedText = importedParts.length
                ? `Metadata for ${importedParts.join(', ')} will be imported`
                : 'No metadata will be imported';
            const skippedText = skippedCount ? `${plural(skippedCount, 'row')} skipped` : '';
            const summaryText = [importedText, skippedText].filter(Boolean).join(' | ');

            return div(
                { class: 'flex-column fx-gap-3' },
                hasError
                    ? ''
                    : span(
                        { class: 'text-secondary' },
                        summaryText,
                    ),
                hasError
                    ? Alert({ type: 'error', icon: 'error' }, span(preview.error))
                    : PreviewTable(preview, emit),
                preview.pii_skipped
                    ? Alert(
                        { type: 'info', icon: 'info' },
                        'PII data in this CSV will be ignored because you do not have permission to edit PII flags.',
                    )
                    : null,
                preview.warn_cde || preview.warn_pii
                    ? Alert(
                        { type: 'warn', icon: 'warning' },
                        `This table group is currently configured to detect ${preview.warn_cde ? 'CDEs' : ''}${preview.warn_cde && preview.warn_pii ? ' and ' : ''}${preview.warn_pii ? 'PIIs' : ''} during profiling.
                            To preserve your imported edits, autodetection will be turned off.`,
                    )
                    : null,
                div(
                    { class: 'flex-row fx-justify-content-flex-end' },
                    Button({
                        type: 'stroked',
                        color: 'primary',
                        label: 'Import Metadata',
                        icon: 'upload',
                        width: 'auto',
                        disabled: !hasMatches,
                        onclick: () => props.onImportConfirmed ? props.onImportConfirmed() : emit('ImportConfirmed', {}),
                    }),
                ),
            );
        },
    );
};

const STATUS_ICONS = {
    ok: 'check_circle',
    warning: 'warning',
    error: 'error',
    unmatched: 'block',
};

const COLUMN_LABELS = {
    critical_data_element: 'CDE',
    excluded_data_element: 'XDE',
    pii_flag: 'PII',
};

const PreviewTable = (preview, emit) => {
    const metadataColumns = preview.metadata_columns || [];
    const previewRows = preview.preview_rows || [];

    const columns = [
        { name: '_status_icon', label: '', width: 32, overflow: 'visible', align: 'center' },
        { name: 'table_name', label: 'Table', width: 150, align: 'left' },
        { name: 'column_name', label: 'Column', width: 150, align: 'left' },
        ...metadataColumns.map(col => ({
            name: col,
            label: COLUMN_LABELS[col] ?? capitalize(col.replaceAll('_', ' ')),
            width: col === 'description' ? 200 : 120,
            align: 'left',
        })),
    ];

    const rows = previewRows.map(row => {
        const status = row._status || 'ok';
        const icon = STATUS_ICONS[status] || STATUS_ICONS.ok;
        const truncatedFields = row._truncated_fields || [];

        const statusIcon = i(
            {
                class: `material-symbols-rounded import-status-${status}`,
                style: 'font-size: 16px; cursor: default; overflow: visible; position: relative',
            },
            icon,
        );

        const tableRow = {
            _status: status,
            _status_icon: row._status_detail
                ? withTooltip(statusIcon, { text: row._status_detail, position: 'right', width: 200 })
                : statusIcon,
            table_name: row.table_name ?? '',
            column_name: row.column_name ?? '',
        };

        for (const col of metadataColumns) {
            let val = row[col] ?? '';
            if (truncatedFields.includes(col) && val) {
                val += '\u2026';
            }
            tableRow[col] = val;
        }

        return tableRow;
    });

    return Table(
        {
            emit,
            columns,
            height: 'auto',
            maxHeight: '300px',
            highDensity: true,
            rowClass: (row) => {
                if (row._status === 'unmatched') return 'import-row-unmatched';
                if (row._status === 'error') return 'import-row-error';
                if (row._status === 'warning') return 'import-row-warning';
                return '';
            },
        },
        rows,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.import-status-ok {
    color: var(--primary-color);
}

.import-status-warning {
    color: var(--orange);
}

.import-status-error {
    color: var(--error-color);
}

.import-status-unmatched {
    color: var(--disabled-text-color);
}

.import-row-unmatched > td {
    background-color: rgba(0, 0, 0, 0.03);
    color: var(--disabled-text-color);
}

.import-row-error > td {
    background-color: color-mix(in srgb, var(--error-color) 5%, transparent);
}

.import-row-warning > td {
    background-color: color-mix(in srgb, var(--orange) 8%, transparent);
}

@media (prefers-color-scheme: dark) {
    .import-row-unmatched > td {
        background-color: rgba(255, 255, 255, 0.03);
    }
}
`);

export { ImportMetadataDialog };
