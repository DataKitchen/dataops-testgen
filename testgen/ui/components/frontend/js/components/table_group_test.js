/**
 * @typedef TableGroupPreview
 * @type {object}
 * @property {string} schema
 * @property {Record<string, boolean | null>?} tables
 * @property {number?} column_count
 * @property {boolean?} success
 * @property {string?} message
 * 
 * @typedef ComponentOptions
 * @type {object}
 * @property {(() => void)?} onVerifyAcess
 */
import van from '../van.min.js';
import { emitEvent, getValue } from '../utils.js';
import { Alert } from '../components/alert.js';
import { Icon } from '../components/icon.js';
import { Button } from '../components/button.js';

const { div, span, strong } = van.tags;

/**
 * 
 * @param {string} schema
 * @param {TableGroupPreview?} preview
 * @param {ComponentOptions} options
 * @returns {HTMLElement}
 */
const TableGroupTest = (schema, preview, options) => {
    return div(
        { class: 'flex-column fx-gap-2' },
        div(
            { class: 'flex-row fx-justify-space-between' },
            div(
                { class: 'flex-column fx-gap-2' },
                div(
                    { class: 'flex-row fx-gap-1' },
                    strong({}, 'Schema:'),
                    span({}, schema),
                ),
                div(
                    { class: 'flex-row fx-gap-1' },
                    strong({}, 'Table Count:'),
                    () => span({}, Object.keys(getValue(preview)?.tables ?? {})?.length ?? '--'),
                ),
                div(
                    { class: 'flex-row fx-gap-1' },
                    strong({}, 'Column Count:'),
                    () => span({}, getValue(preview)?.column_count ?? '--'),
                ),
            ),
            options.onVerifyAcess
                ? div(
                    { class: 'flex-row' },
                    span({ class: 'fx-flex' }),
                    Button({
                        label: 'Verify Access',
                        width: 'fit-content',
                        type: 'stroked',
                        onclick: options.onVerifyAcess,
                    }),
                )
                : '',
        ),
        () => {
            const tableGroupPreview = getValue(preview);
            const wasPreviewExecuted = tableGroupPreview && typeof tableGroupPreview.success === 'boolean';

            if (!wasPreviewExecuted) {
                return '';
            }

            const tables = tableGroupPreview?.tables ?? {};
            const hasTables = Object.keys(tables).length > 0;
            const verifiedAccess = Object.values(tables).some(v => v != null);
            const tableAccessWarning = Object.values(tables).some(v => v != null && v === false)
                ? tableGroupPreview.message
                : '';

            return div(
                {class: 'flex-column fx-gap-2'},
                div(
                    { class: 'table hoverable p-3' },
                    div(
                        { class: 'table-header flex-row fx-justify-space-between' },
                        span('Tables'),
                        verifiedAccess
                            ? span({class: 'flex-row fx-justify-center', style: 'width: 100px;'}, 'Has access?')
                            : '',
                    ),
                    div(
                        { class: 'flex-column', style: 'max-height: 200px; overflow-y: auto;' },
                        hasTables
                            ? Object.entries(tables).map(([tableName, hasAccess]) =>
                                div(
                                    { class: 'table-row flex-row fx-justify-space-between' },
                                    span(tableName),
                                    hasAccess != null
                                        ? span(
                                            {class: 'flex-row fx-justify-center', style: 'width: 100px;'},
                                            hasAccess
                                                ? Icon({classes: 'text-green', size: 20}, 'check_circle')
                                                : Icon({classes: 'text-error', size: 20}, 'dangerous'),
                                        )
                                        : '',
                                ),
                            )
                            : div(
                                { class: 'flex-row fx-justify-center', style: 'height: 50px; font-size: 16px;'},
                                tableGroupPreview.message ?? 'No tables found.'
                            ),
                    ),
                ),
                tableAccessWarning ?
                    Alert({type: 'warn', closeable: true, icon: 'warning'}, span(tableAccessWarning))
                    : '',
            );
        },
    );
};

export { TableGroupTest };
