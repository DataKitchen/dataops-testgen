/**
 * @import { TableGroupStats } from './table_group_stats.js'
 * 
 * @typedef TablePreview
 * @type {object}
 * @property {number} column_ct
 * @property {number} approx_record_ct
 * @property {number} approx_data_point_ct
 * @property {boolean} can_access
 * 
 * @typedef TableGroupPreview
 * @type {object}
 * @property {TableGroupStats} stats
 * @property {Record<string, TablePreview>?} tables
 * @property {boolean?} success
 * @property {string?} message
 * 
 * @typedef ComponentOptions
 * @type {object}
 * @property {(() => void)?} onVerifyAcess
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { formatNumber } from '../display_utils.js';
import { Alert } from '../components/alert.js';
import { Icon } from '../components/icon.js';
import { Button } from '../components/button.js';
import { TableGroupStats } from './table_group_stats.js';

const { div, span } = van.tags;

/**
 * @param {TableGroupPreview?} preview
 * @param {ComponentOptions} options
 * @returns {HTMLElement}
 */
const TableGroupTest = (preview, options) => {
    return div(
        { class: 'flex-column fx-gap-2' },
        div(
            { class: 'flex-row fx-justify-space-between fx-align-flex-end' },
            span({ class: 'text-caption text-right' }, '* Approximate row counts based on server statistics'),
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
        () => getValue(preview)
            ? TableGroupStats({ hideWarning: true, hideApproxCaption: true }, getValue(preview).stats)
            : '',
        () => {
            const tableGroupPreview = getValue(preview);
            const wasPreviewExecuted = tableGroupPreview && typeof tableGroupPreview.success === 'boolean';

            if (!wasPreviewExecuted) {
                return '';
            }

            const tables = tableGroupPreview?.tables ?? {};
            const hasTables = Object.keys(tables).length > 0;
            const verifiedAccess = Object.values(tables).some(({ can_access }) => can_access != null);
            const tableAccessWarning = Object.values(tables).some(({ can_access }) => can_access != null && can_access === false)
                ? tableGroupPreview.message
                : '';

            const columns = ['50%', '14%', '14%', '14%', '8%'];

            return div(
                {class: 'flex-column fx-gap-2'},
                div(
                    { class: 'table hoverable p-3 pb-0' },
                    div(
                        { class: 'table-header flex-row' },
                        span({ style: `flex: 1 1 ${columns[0]}; max-width: ${columns[0]};` }, 'Tables'),
                        span({ style: `flex: 1 1 ${columns[1]};` }, 'Columns'),
                        span({ style: `flex: 1 1 ${columns[2]};` }, 'Rows *'),
                        span({ style: `flex: 1 1 ${columns[3]};` }, 'Data Points *'),
                        verifiedAccess
                            ? span({class: 'flex-row fx-justify-center', style: `flex: 1 1 ${columns[4]};`}, 'Can access?')
                            : '',
                    ),
                    div(
                        { class: 'flex-column', style: 'max-height: 400px; overflow-y: auto;' },
                        hasTables
                            ? Object.entries(tables).map(([ tableName, table ]) =>
                                div(
                                    { class: 'table-row flex-row fx-justify-space-between' },
                                    span(
                                        { style: `flex: 1 1 ${columns[0]}; max-width: ${columns[0]}; word-wrap: break-word;` },
                                        tableName,
                                    ),
                                    span({ style: `flex: 1 1 ${columns[1]};` }, formatNumber(table.column_ct)),
                                    span({ style: `flex: 1 1 ${columns[2]};` }, formatNumber(table.approx_record_ct)),
                                    span({ style: `flex: 1 1 ${columns[3]};` }, formatNumber(table.approx_data_point_ct)),
                                    table.can_access != null
                                        ? span(
                                            {class: 'flex-row fx-justify-center', style: `flex: 1 1 ${columns[4]};`},
                                            table.can_access
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
