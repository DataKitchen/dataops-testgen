/**
 * @import { TableGroup } from '../components/table_group_form.js';
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
 * @property {boolean} can_be_deleted
 * @property {Result?} result
 */

import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Button } from '../components/button.js';
import { Toggle } from '../components/toggle.js';
import { Attribute } from '../components/attribute.js';
import { Alert } from '../components/alert.js';

const { div, h3, hr, span, b } = van.tags;

/**
 * @param {Properties} props 
 * @returns 
 */
const TableGroupDeleteConfirmation = (props) => {
    loadStylesheet('tablegroup-delete-confirmation', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const wrapperId = 'tablegroup-delete-wrapper';
    const tableGroup = getValue(props.table_group);
    const confirmDeleteRelated = van.state(false);
    const deleteDisabled = van.derive(() => !getValue(props.can_be_deleted) && !confirmDeleteRelated.val);

    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return div(
        { id: wrapperId, class: 'flex-column' },
        div(
            { class: 'flex-column fx-gap-4' },
            span(
                'Are you sure you want to delete the table group ',
                b(tableGroup.table_groups_name),
                '?',
            ),
            Attribute({
                label: 'ID',
                value: tableGroup.id,
            }),
            Attribute({
                label: 'Name',
                value: tableGroup.table_groups_name,
            }),
            Attribute({
                label: 'Schema',
                value: tableGroup.table_group_schema,
            }),
        ),
        () => !getValue(props.can_be_deleted)
            ? div(
                { class: 'flex-column fx-gap-4 mt-4' },
                Alert(
                    { type: 'warn' },
                    div('This Table Group has related data, which may include profiling, test definitions and test results.'),
                    div({ class: 'mt-2' }, 'If you proceed, all related data will be permanently deleted.'),
                ),
                Toggle({
                    name: 'confirm-delete-tablegroup',
                    label: span(
                        'Yes, delete the table group ',
                        b(tableGroup.table_groups_name),
                        ' and related TestGen data.',
                    ),
                    checked: confirmDeleteRelated,
                    onChange: (value) => confirmDeleteRelated.val = value,
                }),
            )
            : '',

        div(
            { class: 'flex-row fx-justify-content-flex-end' },
            Button({
                type: () => deleteDisabled.val ? 'stroked' : 'flat',
                color: () => deleteDisabled.val ? 'basic' : 'warn',
                label: 'Delete',
                style: 'width: auto;',
                disabled: deleteDisabled,
                onclick: () => emitEvent('DeleteTableGroupConfirmed'),
            }),
        ),
        () => {
            const result = getValue(props.result);
            return result
                ? Alert(
                    { type: result.success ? 'success' : 'error', class: 'mt-3' },
                    div(result.message),
                )
                : '';
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
`);

export { TableGroupDeleteConfirmation };
