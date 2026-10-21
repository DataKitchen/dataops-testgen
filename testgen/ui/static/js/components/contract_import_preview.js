/**
 * @typedef PreviewRow
 * @type {object}
 * @property {'create'|'update'|'skip'|'delete'} action_code
 * @property {string} reason
 * @property {string} table_name
 * @property {string} column_name
 * @property {string} test_name
 *
 * @typedef ImportPreview
 * @type {object}
 * @property {boolean} creating
 * @property {{create: number, update: number, delete: number, skip: number}} summary
 * @property {PreviewRow[]} rows
 * @property {number} total_rows
 * @property {boolean} truncated
 * @property {number} unverifiable_count
 * @property {string?} server_type_warning
 * @property {string[]} tables_not_in_catalog
 * @property {string?} error
 * @property {string[]?} problems
 *
 * @typedef Properties
 * @type {object}
 * @property {object} preview - VanJS state (or derive) holding an ImportPreview or null
 * @property {object} deleteConfirmed - VanJS state holding whether the deletion was confirmed
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { Alert } from './alert.js';
import { Icon } from './icon.js';
import { Table } from './table.js';
import { Toggle } from './toggle.js';
import { withTooltip } from './tooltip.js';

const { div, li, span, ul } = van.tags;

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

const pluralize = (count, noun) => `${count} ${noun}${count === 1 ? '' : 's'}`;

const summaryText = (preview) => {
    const { create, update, delete: deleted } = preview.summary;
    const verbs = [];
    if (create) verbs.push(`create ${pluralize(create, 'term')}`);
    if (update) verbs.push(`update ${pluralize(update, 'term')}`);
    if (deleted) verbs.push(`delete ${pluralize(deleted, 'term')}`);
    const subject = preview.creating && !update && !deleted ? 'This file will' : 'This import will';
    const head = verbs.length ? `${subject} ${verbs.join(', ')}` : 'This file changes no terms';
    const unverifiable = preview.unverifiable_count
        ? ` | ${pluralize(preview.unverifiable_count, 'rule')} cannot be verified`
        : '';
    return `${head}${unverifiable}`;
};

const ContractImportPreview = (/** @type Properties */ props) => {
    loadStylesheet('contract-import-preview', stylesheet);

    return div(
        { class: 'flex-column fx-gap-3' },
        () => {
            const preview = getValue(props.preview);
            if (!preview) {
                return '';
            }

            if (preview.error) {
                return Alert(
                    { type: 'error', icon: 'error' },
                    div(preview.error),
                    preview.problems?.length ? ul({ class: 'mt-1 mb-0 pl-4' }, preview.problems.map((problem) => li(problem))) : null,
                );
            }

            const deleting = preview.summary.delete;
            const notInCatalog = preview.tables_not_in_catalog ?? [];

            return div(
                { class: 'flex-column fx-gap-3' },
                div({ class: 'text-bold' }, summaryText(preview)),
                PreviewTable(preview),
                preview.truncated
                    ? Alert({ type: 'info', icon: 'info' }, `Showing the first ${preview.rows.length} of ${preview.total_rows} changes.`)
                    : null,
                preview.unverifiable_count
                    ? Alert(
                        { type: 'info', icon: 'info' },
                        `${pluralize(preview.unverifiable_count, 'rule')} cannot be verified by TestGen. ${preview.unverifiable_count === 1 ? 'It is' : 'They are'} kept in the contract metadata.`,
                    )
                    : null,
                preview.server_type_warning
                    ? Alert({ type: 'warn', icon: 'warning' }, preview.server_type_warning)
                    : null,
                notInCatalog.length
                    ? Alert({ type: 'warn', icon: 'warning' }, `Not in the data catalog: ${notInCatalog.join(', ')}.`)
                    : null,
                deleting > 0
                    ? Alert(
                        { type: 'warn', icon: 'warning' },
                        `${pluralize(deleting, 'term')} in the draft ${deleting === 1 ? 'is' : 'are'} not in the file and will be permanently deleted.`,
                    )
                    : null,
                deleting > 0
                    ? Toggle({
                        name: 'confirm-delete-contract-terms',
                        label: `Yes, delete the ${pluralize(deleting, 'term')} that ${deleting === 1 ? 'is' : 'are'} not in the file.`,
                        checked: props.deleteConfirmed,
                        onChange: (value) => props.deleteConfirmed.val = value,
                    })
                    : null,
            );
        },
    );
};

const PreviewTable = (preview) => {
    const columns = [
        { name: '_action_icon', label: '', width: 32, overflow: 'visible', align: 'center' },
        { name: 'table_name', label: 'Table', width: 170, align: 'left' },
        { name: 'column_name', label: 'Column', width: 170, align: 'left' },
        { name: 'test_name', label: 'Test Type', width: 170, align: 'left' },
        { name: 'reason', label: 'Reason', width: 260, align: 'left' },
    ];

    const rows = (preview.rows ?? []).map((row) => {
        const icon = Icon(
            { size: 18, classes: `${ACTION_CLASSES[row.action_code] ?? ''} display-table-cell` },
            ACTION_ICONS[row.action_code] ?? 'help',
        );

        return {
            ...row,
            _action_icon: withTooltip(icon, { text: `${row.action_code}: ${row.reason}`, position: 'right', width: 200 }),
        };
    });

    return div(
        { 'data-testid': 'contract-import-preview' },
        Table(
            {
                columns,
                height: 'auto',
                maxHeight: '300px',
                highDensity: true,
                rowClass: (row) => `contract-import-row-${row.action_code}`,
            },
            rows,
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.contract-import-row-skip > td {
    color: var(--disabled-text-color);
    background-color: rgba(0, 0, 0, 0.03);
}

.contract-import-row-delete > td {
    background-color: color-mix(in srgb, var(--error-color) 5%, transparent);
}

@media (prefers-color-scheme: dark) {
    .contract-import-row-skip > td {
        background-color: rgba(255, 255, 255, 0.03);
    }
}
`);

export { ContractImportPreview };
