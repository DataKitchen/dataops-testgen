/**
 * @typedef TableGroupPreview
 * @type {object}
 * @property {string} schema
 * @property {string[]?} tables
 * @property {number?} column_count
 * @property {boolean?} success
 * @property {string?} message
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { Alert } from '../components/alert.js';

const { div, span, strong } = van.tags;

/**
 * 
 * @param {string} schema
 * @param {TableGroupPreview?} preview
 * @returns {HTMLElement}
 */
const TableGroupTest = (schema, preview) => {
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
                    () => span({}, getValue(preview)?.tables?.length ?? '--'),
                ),
                div(
                    { class: 'flex-row fx-gap-1' },
                    strong({}, 'Column Count:'),
                    () => span({}, getValue(preview)?.column_count ?? '--'),
                ),
            ),
        ),
        () => {
            const tableGroupPreview = getValue(preview);
            const wasPreviewExecuted = tableGroupPreview && typeof tableGroupPreview.success === 'boolean';

            if (!wasPreviewExecuted) {
                return '';
            }

            return div(
                { class: 'table hoverable p-3' },
                div(
                    { class: 'table-header' },
                    span('Tables'),
                ),
                div(
                    { class: 'flex-column', style: 'max-height: 200px; overflow-y: auto;' },
                    tableGroupPreview?.tables?.length
                        ? tableGroupPreview.tables.map((table) =>
                            div({ class: 'table-row' }, table),
                        )
                        : div(
                            { class: 'flex-row fx-justify-center', style: 'height: 50px; font-size: 16px;'},
                            tableGroupPreview.message ?? 'No tables found.'
                        ),
                ),
            );
        },
    );
};

export { TableGroupTest };
