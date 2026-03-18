/**
 * @import { Column, Table } from './data_profiling_utils.js';
 * 
 * @typedef TagProperties
 * @type {object}
 * @property {Object.<string, string[]>} tagOptions
 * @property {boolean} editable
 * @property {boolean} piiEditable
 * @property {AutoflagSettings} autoflagSettings
 * @property {(() => void)?} onCancel
 */
import van from '../van.min.js';
import { EditableCard } from '../components/editable_card.js';
import { Attribute } from '../components/attribute.js';
import { Input } from '../components/input.js';
import { Icon } from '../components/icon.js';
import { withTooltip } from '../components/tooltip.js';
import { emitEvent } from '../utils.js';
import { RadioGroup } from '../components/radio_group.js';
import { Checkbox } from '../components/checkbox.js';
import { capitalize } from '../display_utils.js';
import { Card } from '../components/card.js';
import { Dialog } from '../components/dialog.js';
import { Button } from '../components/button.js';
import { Alert } from '../components/alert.js';

const { div, span } = van.tags;

const attributeWidth = 300;
const descriptionWidth = 932;
const multiEditWidth = 400;

const booleanOptions = [
    { label: 'Yes', value: true },
    { label: 'No', value: false },
];

const piiOptions = [
    { label: 'Yes', value: 'MANUAL' },
    { label: 'No', value: null },
];

const pii_risk_map = {
    'A': 'High',
    'B': 'Moderate',
    'C': 'Low',
};
const pii_type_map = {
    'ID': 'ID',
    'NAME': 'Name',
    'DEMO': 'Demographic',
    'CONTACT': 'Contact',
};

const TAG_KEYS = [
    'data_source',
    'source_system',
    'source_process',
    'business_domain',
    'stakeholder_group',
    'transform_level',
    'aggregation_level',
    'data_product',
];
const TAG_HELP = {
    data_source: 'Original source of the dataset',
    source_system: 'Enterprise system source for the dataset',
    source_process: 'Process, program, or data flow that produced the dataset',
    business_domain: 'Business division responsible for the dataset, e.g., Finance, Sales, Manufacturing',
    stakeholder_group: 'Data owners or stakeholders responsible for the dataset',
    transform_level: 'Data warehouse processing stage, e.g., Raw, Conformed, Processed, Reporting, or Medallion level (bronze, silver, gold)',
    aggregation_level: 'Data granularity of the dataset, e.g. atomic, historical, snapshot, aggregated, time-rollup, rolling, summary',
    data_product: 'Data domain that comprises the dataset',
};

/**
 * @param {TagProperties} props
 * @param {Table | Column} item
 * @returns
 */
const MetadataTagsCard = (props, item) => {
    const title = `${item.type} Tags `;
    const attributes = [
        'critical_data_element',
        ...(item.type === 'column' ? ['excluded_data_element', 'pii_flag'] : []),
        'description',
        ...TAG_KEYS,
    ].map(key => {
        let value = item[key];
        if (['excluded_data_element', 'pii_flag'].includes(key) || (item.type === 'table' && key === 'critical_data_element')) {
            value = value ?? false;
        }
        return {
            key,
            help: TAG_HELP[key],
            label: key === 'pii_flag' ? 'PII Data' : capitalize(key.replaceAll('_', ' ')),
            state: van.state(value),
            inheritTableGroup: item[`table_group_${key}`] ?? null, // Table group values inherited by table or column
            inheritTable: item[`table_${key}`] ?? null, // Table values inherited by column
        };
    });

    const content = div(
        { class: 'flex-row fx-flex-wrap fx-gap-4' },
        attributes.map(({ key, label, help, state, inheritTable, inheritTableGroup }) => {
            let value = state.rawVal ?? inheritTable ?? inheritTableGroup;

            if (key === 'critical_data_element') {
                return CdeDisplay(value, item.type === 'column', state.rawVal === null);
            }
            if (key === 'excluded_data_element') {
                return XdeDisplay(value);
            }
            if (key === 'pii_flag') {
                return PiiDisplay(value);
            }

            const inheritedFrom = state.rawVal !== null ? null
                : inheritTable !== null ? 'table'
                : inheritTableGroup !== null ? 'table group'
                : null;

            if (inheritedFrom && value) {
                value = span(
                    { class: 'flex-row fx-gap-1' },
                    InheritedIcon(inheritedFrom),
                    value,
                );
            }
            return Attribute({ label, help, value, width: key === 'description' ? descriptionWidth : attributeWidth });
        }),
    );

    if (!props.editable) {
        return Card({ title, content });
    }

    // Define as function so the block is re-rendered with reset values when re-editing after a cancel
    const editingContent = () => div(
        { class: 'flex-row fx-flex-wrap fx-gap-4' },
        attributes.map(({ key, label, help, state, inheritTable, inheritTableGroup }) => {
            if (key === 'critical_data_element') {
                return RadioGroup({
                    label,
                    options: item.type === 'column' ? [...booleanOptions, { label: 'Inherit', value: null }] : booleanOptions,
                    width: attributeWidth,
                    value: state.rawVal,
                    onChange: (value) => state.val = value,
                });
            }
            if (key === 'excluded_data_element') {
                return RadioGroup({
                    label,
                    options: booleanOptions,
                    width: attributeWidth,
                    value: state.rawVal,
                    onChange: (value) => state.val = value,
                });
            }
            if (key === 'pii_flag') {
                return RadioGroup({
                    label,
                    options: piiOptions,
                    width: attributeWidth,
                    value: state.rawVal ? 'MANUAL' : null,
                    onChange: (value) => state.val = value,
                    disabled: !props.piiEditable,
                });
            }
            return Input({
                label, help,
                width: key === 'description' ? descriptionWidth : attributeWidth,
                height: 32,
                value: state.rawVal,
                placeholder: (inheritTable || inheritTableGroup) ? `Inherited: ${inheritTable ?? inheritTableGroup}` : null,
                autocompleteOptions: props.tagOptions?.[key],
                onChange: (value) => state.val = value || null,
            });
        }),
    );

    const warningDialogOpen = van.state(false);
    const pendingSaveAction = van.state(null);
    const warnCde = van.state(false);
    const warnPii = van.state(false);

    return div(
        EditableCard({
            title: `${item.type} Tags `,
            content, editingContent,
            onSave: () => {
                const items = [{ type: item.type, id: item.id }];
                const tags = attributes.reduce((object, { key, state }) => {
                    object[key] = state.rawVal;
                    return object;
                }, {});

                warnCde.val = props.autoflagSettings.profile_flag_cdes && tags.critical_data_element !== item.critical_data_element;
                warnPii.val = props.autoflagSettings.profile_flag_pii && tags.pii_flag !== item.pii_flag;

                if (warnCde.val || warnPii.val) {
                    const disableFlags = [];
                    if (warnCde.val) {
                        disableFlags.push('profile_flag_cdes');
                    }
                    if (warnPii.val) {
                        disableFlags.push('profile_flag_pii');
                    }
                    pendingSaveAction.val = () => emitEvent('TagsChanged', { payload: { items, tags, disable_flags: disableFlags } });
                    warningDialogOpen.val = true;
                } else {
                    emitEvent('TagsChanged', { payload: { items, tags } })
                } 
            },
            // Reset states to original values on cancel
            onCancel: () => attributes.forEach(({ key, state }) => state.val = item[key]),
            hasChanges: () => attributes.some(({ key, state }) => state.val !== item[key]),
        }),
        WarningDialog(warningDialogOpen, pendingSaveAction, warnCde, warnPii),
    );
};

const InheritedIcon = (/** @type string */ inheritedFrom) => withTooltip(
    Icon({ size: 18, classes: 'text-disabled' }, 'layers'),
    { text: `Inherited from ${inheritedFrom} tags`, position: 'top-right'},
);

/**
 * @param {boolean|null} value
 * @param {boolean} isColumn
 * @param {boolean} isInherited
 * @returns
 */
const CdeDisplay = (value, isColumn, isInherited) => {
    return span(
        { class: 'flex-row fx-gap-1', style: `width: ${attributeWidth}px` },
        Icon(
            { size: value ? 24 : 20, classes: value ? 'text-purple' : 'text-disabled' },
            value ? 'star' : 'cancel',
        ),
        span(
            { class: value ? '' : 'text-secondary' },
            isColumn
                ? (value ? 'Critical data element' : 'Not a critical data element')
                : (value ? 'All critical data elements' : 'Not all critical data elements'),
        ),
        (isColumn && isInherited) ? InheritedIcon('table') : null,
    );
}

const XdeDisplay = (/** @type boolean */ value) => {
    return span(
        { class: 'flex-row fx-gap-1', style: `width: ${attributeWidth}px` },
        Icon(
            { size: 20, classes: value ? 'text-brown' : 'text-disabled' },
            value ? 'visibility_off' : 'visibility',
        ),
        span(
            { class: value ? '' : 'text-secondary' },
            value ? 'Excluded data element' : 'Not an excluded data element',
        ),
    );
}

const PiiDisplay = (/** @type string|null */ value) => {
    if (value) {
        let caption = null;
        if (value !== 'MANUAL') {
            const [ risk, type, detail ] = value.split('/'); // e.g., A/ID/Passport, B/DEMO/Financial
            const typeLabel = pii_type_map[type];
            caption = `${pii_risk_map[risk] ?? 'Moderate'} Risk${typeLabel ? ' - ' + typeLabel : ''}${detail && detail !== typeLabel ? ' / ' + detail : ''}`;
        }
        return span(
            { class: 'flex-row fx-gap-1', style: `width: ${attributeWidth}px` },
            Icon({ size: 24, classes: 'text-orange' }, 'shield_person'),
            div(
                { class: 'flex-column fx-gap-1' },
                span('PII data'),
                caption ? span({ class: 'text-caption' }, caption) : null,
            ),
        );
    }
    return span(
        { class: 'flex-row fx-gap-1', style: `width: ${attributeWidth}px` },
        Icon({ classes: 'text-disabled' }, 'remove_moderator'),
        span({ class: 'text-secondary' }, 'Not PII data'),
    );
};

/**
 * @param {TagProperties} props
 * @param {Object} selectedItems
 * @returns
 */
const MetadataTagsMultiEdit = (props, selectedItems) => {
    const columnCount = van.derive(() => selectedItems.val?.reduce((count, { children }) => count + children.length, 0));

    const attributes = [
        'critical_data_element',
        'excluded_data_element',
        'pii_flag',
        ...TAG_KEYS,
    ].map(key => ({
        key,
        help: TAG_HELP[key],
        label: key === 'pii_flag' ? 'PII' : capitalize(key.replaceAll('_', ' ')),
        checkedState: van.state(null),
        valueState: van.state(null),
    }));

    const warningDialogOpen = van.state(false);
    const pendingSaveAction = van.state(null);
    const warnCde = van.state(false);
    const warnPii = van.state(false);

    return div(
        Card({
            title: 'Edit Tags for Selection',
            actionContent: span(
                { class: 'text-secondary mr-4' },
                span({ style: 'font-weight: 500' }, columnCount),
                () => ` column${columnCount.val > 1 ? 's' : ''} selected`
            ),
            content: div(
                { class: 'flex-column' },
                attributes.map(({ key, label, help, checkedState, valueState }) => div(
                    { class: 'flex-row fx-gap-3' },
                    Checkbox({
                        checked: checkedState,
                        onChange: (checked) => checkedState.val = checked,
                    }),
                    div(
                        {
                            class: 'pb-4 flex-row',
                            style: `min-width: ${multiEditWidth}px`,
                            onclick: () => checkedState.val = true,
                        },
                        ['critical_data_element', 'excluded_data_element', 'pii_flag'].includes(key)
                            ? RadioGroup({
                                label,
                                width: multiEditWidth,
                                options: key === 'pii_flag' ? piiOptions : booleanOptions,
                                onChange: (value) => valueState.val = value,
                                disabled: key === 'pii_flag' && !props.piiEditable,
                            })
                            : Input({
                                label, help,
                                width: multiEditWidth,
                                height: 32,
                                placeholder: () => checkedState.val ? null : '(keep current values)',
                                autocompleteOptions: props.tagOptions?.[key],
                                onChange: (value) => valueState.val = value || null,
                            }),
                    ),
                )),
                div(
                    { class: 'flex-row fx-justify-content-flex-end fx-gap-3 mt-4' },
                    Button({
                        type: 'stroked',
                        label: 'Cancel',
                        width: 'auto',
                        onclick: props.onCancel,
                    }),
                    Button({
                        type: 'stroked',
                        color: 'primary',
                        label: 'Save',
                        width: 'auto',
                        disabled: () => attributes.every(({ checkedState }) => !checkedState.val),
                        onclick: () => {
                            const items = selectedItems.val.reduce((array, table) => {
                                const [ type, id ] = table.id.split('_');
                                array.push({ type, id });

                                table.children.forEach(column => {
                                    const [ type, id ] = column.id.split('_');
                                    array.push({ type, id });
                                });

                                return array;
                            }, []);

                            const tags = attributes.reduce((object, { key, checkedState, valueState }) => {
                                if (checkedState.val) {
                                    object[key] = valueState.rawVal;
                                }
                                return object;
                            }, {});

                            warnCde.val = props.autoflagSettings.profile_flag_cdes && tags.critical_data_element !== undefined;
                            warnPii.val = props.autoflagSettings.profile_flag_pii &&  tags.pii_flag !== undefined;

                            if (warnCde.val || warnPii.val) {
                                const disableFlags = [];
                                if (warnCde.val) {
                                    disableFlags.push('profile_flag_cdes');
                                }
                                if (warnPii.val) {
                                    disableFlags.push('profile_flag_pii');
                                }
                                pendingSaveAction.val = () => emitEvent('TagsChanged', { payload: { items, tags, disable_flags: disableFlags } });;
                                warningDialogOpen.val = true;
                            } else {
                                emitEvent('TagsChanged', { payload: { items, tags } });
                                // Don't set multiEditMode to false here
                                // Otherwise this event gets superseded by the ItemSelected event
                                // Let the Streamlit rerun handle the state reset with 'last_saved_timestamp'
                            }
                        },
                    }),
                ),
            ),
        }),
        WarningDialog(warningDialogOpen, pendingSaveAction, warnCde, warnPii),
    );
};

const WarningDialog = (open, pendingAction, warnCde, warnPii) => {
    return Dialog(
        { open, width: '40rem', onClose: () => open.val = false },
        div(
            { class: 'flex-column fx-gap-4' },
            span(() => `This table group is currently configured to detect ${warnCde.val ? 'CDEs' : ''}${warnCde.val && warnPii.val ? ' and ' : ''}${warnPii.val ? 'PIIs' : ''} during profiling.`),
            Alert(
                { type: 'warn', icon: 'warning' },
                'To preserve your manual edits, autodetection will be turned off.',
            ),
            div(
                { class: 'flex-row fx-justify-content-flex-end fx-gap-3 mt-4' },
                Button({
                    type: 'stroked',
                    label: 'Cancel',
                    width: 'auto',
                    onclick: () => open.val = false,
                }),
                Button({
                    type: 'stroked',
                    color: 'primary',
                    label: 'OK',
                    width: 'auto',
                    onclick: () => {
                        open.val = false;
                        pendingAction.val?.();
                    },
                }),
            ),
        ),
    );
};

export { MetadataTagsCard, MetadataTagsMultiEdit, TAG_KEYS };
