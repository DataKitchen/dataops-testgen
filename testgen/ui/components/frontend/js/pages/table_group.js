/**
 * @import { TableGroup } from '../components/table_group_form.js';
 * @import { Connection } from '../components/connection_form.js';
 * 
 * @typedef TableGroupPreview
 * @type {object}
 * @property {string} schema
 * @property {string[]?} tables
 * @property {number?} column_count
 * @property {boolean?} success
 * @property {string?} message
 *
 * @typedef Result
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} project_code
 * @property {TableGroup} table_group
 * @property {Connection[]} connections
 * @property {TableGroupPreview?} table_group_preview
 * @property {Result?} result
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { Button } from '../components/button.js';
import { getValue, emitEvent, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { TableGroupForm } from '../components/table_group_form.js';
import { Tab, Tabs } from '../components/tabs.js';
import { Alert } from '../components/alert.js';

const { div, span, strong } = van.tags;

/**
 * @param {Properties} props
 * @returns {HTMLElement}
 */
const TableGroup = (props) => {
    loadStylesheet('tablegroupchange', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const connections = getValue(props.connections) ?? [];
    const enableConnectionSelector = getValue(props.table_group)?.connection_id === undefined;
    const updatedTableGroup = van.state(getValue(props.table_group) ?? {});
    const disableSave = van.state(true);
    const wrapperId = 'tablegroup-change-wrapper';

    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return Tabs(
        { id: wrapperId },
        Tab(
            { label: 'Table Group Settings'},
            () => {
                const tableGroup = updatedTableGroup.rawVal;
                const result = getValue(props.result);
        
                return div(
                    { class: 'flex-column fx-gap-3' },
                    TableGroupForm({
                        tableGroup,
                        connections,
                        enableConnectionSelector,
                        showConnectionSelector: connections.length > 1,
                        onChange: (newTableGroup, state) => {
                            updatedTableGroup.val = newTableGroup;
                            disableSave.val = !state.valid;
                        },
                    }),
                    result
                        ? Alert(
                            { type: result.success ? 'success' : 'error', closeable: true },
                            span({}, result.message),
                        )
                        : undefined,
                );
            },
            div(
                { class: 'flex-row fx-gap-2 fx-justify-content-flex-end mt-3' },
                Button({
                    label: 'Save',
                    type: 'stroked',
                    color: 'primary',
                    style: 'width: auto;',
                    disabled: disableSave,
                    onclick: () => emitEvent('TableGroupSaveClicked', { payload: updatedTableGroup.val }),
                }),
            ),
        ),
        Tab(
            { label: 'Test' },
            () => {
                const currentSchema = updatedTableGroup.val.table_group_schema ?? tableGroupPreview?.schema ?? '--';
                const tableGroupPreview = getValue(props.table_group_preview);
                const wasPreviewExecuted = tableGroupPreview && typeof tableGroupPreview.success === 'boolean';
                const alertMessage = tableGroupPreview.success ? 'Operation has finished successfully.' : 'Operation was unsuccessful.';

                return div(
                    { class: 'flex-column fx-gap-2' },
                    div(
                        { class: 'flex-row fx-justify-space-between' },
                        div(
                            { class: 'flex-column fx-gap-2' },
                            div(
                                { class: 'flex-row fx-gap-1' },
                                strong({}, 'Schema:'),
                                span({}, currentSchema),
                            ),
                            div(
                                { class: 'flex-row fx-gap-1' },
                                strong({}, 'Table Count:'),
                                span({}, tableGroupPreview?.tables?.length ?? '--'),
                            ),
                            div(
                                { class: 'flex-row fx-gap-1' },
                                strong({}, 'Column Count:'),
                                span({}, tableGroupPreview?.column_count ?? '--'),
                            ),
                        ),
                        wasPreviewExecuted
                            ? Alert(
                                { type: tableGroupPreview.success ? 'success' : 'error' },
                                span({}, alertMessage),
                            )
                            : undefined,
                    ),
                    wasPreviewExecuted ?
                        div(
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
                        )
                        : undefined,
                );
            },
            div(
                {class: 'flex-row fx-gap-2 fx-justify-content-flex-end mt-3'},
                Button({
                    label: 'Test Table Group',
                    type: 'stroked',
                    color: 'primary',
                    style: 'width: auto;',
                    onclick: () => emitEvent('PreviewTableGroupClicked', { payload: updatedTableGroup.val }),
                }),
            ),
        ),
    );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
`);

export { TableGroup };
