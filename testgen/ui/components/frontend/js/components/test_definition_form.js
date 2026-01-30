/**
 * @typedef TestDefinition
 * @type {object}
 * @property {string} id
 * @property {string} table_groups_id
 * @property {string?} profile_run_id
 * @property {string} test_type
 * @property {string} test_suite_id
 * @property {string?} test_description
 * @property {string} schema_name
 * @property {string?} table_name
 * @property {string?} column_name
 * @property {number?} skip_errors
 * @property {string?} baseline_ct
 * @property {string?} baseline_unique_ct
 * @property {string?} baseline_value
 * @property {string?} baseline_value_ct
 * @property {string?} threshold_value
 * @property {string?} baseline_sum
 * @property {string?} baseline_avg
 * @property {string?} baseline_sd
 * @property {string?} lower_tolerance
 * @property {string?} upper_tolerance
 * @property {string?} subset_condition
 * @property {string?} groupby_names
 * @property {string?} having_condition
 * @property {string?} window_date_column
 * @property {number?} window_days
 * @property {string?} match_schema_name
 * @property {string?} match_table_name
 * @property {string?} match_column_names
 * @property {string?} match_subset_condition
 * @property {string?} match_groupby_names
 * @property {string?} match_having_condition
 * @property {string?} custom_query
 * @property {string?} history_calculation
 * @property {string?} history_calculation_upper
 * @property {number?} history_lookback
 * @property {boolean} test_active
 * @property {string?} test_definition_status
 * @property {string?} severity
 * @property {boolean} lock_refresh
 * @property {number?} last_auto_gen_date
 * @property {number?} profiling_as_of_date
 * @property {number?} last_manual_update
 * @property {boolean} export_to_observability
 * @property {string} test_name_short
 * @property {string} default_test_description
 * @property {string} measure_uom
 * @property {string} measure_uom_description
 * @property {string} default_parm_columns
 * @property {string} default_parm_prompts
 * @property {string} default_parm_help
 * @property {string} default_severity
 * @property {'column'|'referential'|'table'|'tablegroup'|'custom'} test_scope
 * @property {string?} prediction
 *
 * @typedef Properties
 * @type {object}
 * @property {TestDefinition} definition
 * @property {(changes: object, valid: boolean) => void} onChange
 */

import van from '../van.min.js';
import { getValue, isEqual, loadStylesheet } from '../utils.js';
import { Input } from './input.js';
import { Select } from './select.js';
import { Textarea } from './textarea.js';

const { div, span } = van.tags;

const parameterConfig = {
    subset_condition: {
        type: 'text',
    },
    custom_query: {
        type: 'textarea',
    },
    history_calculation: {
        type: 'select',
        options: [
            { label: 'Value', value: 'Value' },
            { label: 'Minimum', value: 'Minimum' },
            { label: 'Maximum', value: 'Maximum' },
            { label: 'Sum', value: 'Sum' },
            { label: 'Average', value: 'Average' },
            { label: 'Use Prediction Model', value: 'PREDICT' },
        ],
    },
    history_calculation_upper: {
        type: 'select',
        options: [
            { label: 'Value', value: 'Value' },
            { label: 'Minimum', value: 'Minimum' },
            { label: 'Maximum', value: 'Maximum' },
            { label: 'Sum', value: 'Sum' },
            { label: 'Average', value: 'Average' },
        ],
    },
    history_lookback: {
        type: 'number',
        default: 10,
        min: 1,
        max: 1000,
        step: 1,
    },
};

const TestDefinitionForm = (/** @type Properties */ props) => {
    loadStylesheet('test-definition-form', stylesheet);

    const definition = getValue(props.definition);

    const paramColumns = (definition.default_parm_columns || '').split(',').map(v => v.trim());
    const paramLabels = (definition.default_parm_prompts || '').split(',').map(v => v.trim());
    const paramHelp = (definition.default_parm_help || '').split('|').map(v => v.trim());

    const updatedDefinition = van.state({ ...definition });
    const validityPerField = van.state({});

    van.derive(() => {
        const newDefinition = updatedDefinition.val
        const fieldsValidity = validityPerField.val;
        const isValid = Object.keys(fieldsValidity).length > 0 &&
            Object.values(fieldsValidity).every(v => v);

        const changes = {};
        for (const key in newDefinition) {
            if (!isEqual(newDefinition[key], definition[key])) {
                changes[key] = newDefinition[key];
            }
        }
        props.onChange?.(changes, { dirty: !!Object.keys(changes).length, valid: isValid });
    });

    const setFieldValue = (field, value) => {
        updatedDefinition.val = { ...updatedDefinition.rawVal, [field]: value };
    };

    const setFieldValidity = (field, validity) => {
        validityPerField.val = { ...validityPerField.rawVal, [field]: validity };
    };

    const usingPrediction = van.derive(() => updatedDefinition.val.history_calculation === 'PREDICT');

    return div(
        div(
            { class: 'mb-2' },
            div({ class: 'text-large' }, definition.test_name_short),
            definition.test_description || definition.default_test_description
                ? span({ class: 'text-caption mt-2' }, definition.test_description ?? definition.default_test_description)
                : null,
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-gap-3' },
            paramColumns.map((column, index) => {
                if (usingPrediction.val && ['history_calculation_upper', 'history_lookback'].includes(column)) {
                    return '';
                }
                const config = parameterConfig[column] || { type: 'text' };
                const label = paramLabels[index] || column.replaceAll('_', ' ');
                const help = paramHelp[index] || null;
                const currentValue = () => updatedDefinition.val[column] ?? config.default;

                if (config.type === 'select') {
                    return div(
                        { class: 'td-form--field' },
                        () => Select({
                            label,
                            options: config.options,
                            value: currentValue(),
                            onChange: (value) => setFieldValue(column, value),
                        }),
                    );
                }

                if (config.type === 'number') {
                    return div(
                        { class: 'td-form--field' },
                        () => Input({
                            name: column,
                            label,
                            type: 'number',
                            value: currentValue(),
                            help,
                            step: config.step,
                            onChange: (value, state) => {
                                setFieldValue(column, value || null);
                                setFieldValidity(column, state.valid);
                            },
                        }),
                    );
                }

                if (config.type === 'textarea') {
                    return div(
                        { class: 'td-form--field-wide' },
                        () => Textarea({
                            name: column,
                            label,
                            value: currentValue(),
                            help,
                            height: 150,
                            onChange: (value) => {
                                setFieldValue(column, value || null);
                            },
                        }),
                    );
                }

                return div(
                    { class: 'td-form--field' },
                    () => Input({
                        name: column,
                        label,
                        value: currentValue(),
                        help,
                        onChange: (value, state) => {
                            setFieldValue(column, value || null);
                            setFieldValidity(column, state.valid);
                        },
                    }),
                );
            }),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.td-form--field {
    flex: calc(50% - 8px) 0 0;
}

.td-form--field-wide {
    flex: 100% 1 1;
}
`);

export { TestDefinitionForm };
