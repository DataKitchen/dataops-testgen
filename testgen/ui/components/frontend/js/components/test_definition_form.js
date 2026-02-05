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
 * @property {string?} class
 * @property {(changes: object, valid: boolean) => void} onChange
 */

import van from '../van.min.js';
import { getValue, isEqual, loadStylesheet } from '../utils.js';
import { Input } from './input.js';
import { Select } from './select.js';
import { Textarea } from './textarea.js';
import { RadioGroup } from './radio_group.js';
import { Caption } from './caption.js';
import { numberBetween } from '../form_validators.js';

const { div, span } = van.tags;

const subsetConditionColumns = ['subset_condition', 'match_subset_condition'];
const subsetConditionNoopValues = ['1=1', 'true', 'TRUE'];

const thresholdColumns = [
    'history_calculation',
    'history_calculation_upper',
    'history_lookback',
    'lower_tolerance',
    'upper_tolerance',
];

// Columns using the default { type: 'text' } do not need to be specified here
const PARAMETER_CONFIG = { 
    custom_query: { type: 'textarea' },
    lower_tolerance: { type: 'number' },
    upper_tolerance: { type: 'number' },
};


const TestDefinitionForm = (/** @type Properties */ props) => {
    loadStylesheet('test-definition-form', stylesheet);

    const definition = getValue(props.definition);

    const paramColumns = (definition.default_parm_columns || '').split(',').map(v => v.trim());
    const paramLabels = (definition.default_parm_prompts || '').split(',').map(v => v.trim());
    const paramHelp = (definition.default_parm_help || '').split('|').map(v => v.trim());

    const hasThresholds = paramColumns.includes('history_calculation');
    const dynamicParamColumns = paramColumns
        .map((column, index) => ({
            ...(PARAMETER_CONFIG[column] || { type: 'text' }),
            column,
            label: paramLabels[index] || column.replaceAll('_', ' '),
            help: paramHelp[index] || null,
        }))
        .filter(config => !hasThresholds || !thresholdColumns.includes(config.column))

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

    const setFieldValues = (updatedValues) => {
        updatedDefinition.val = { ...updatedDefinition.rawVal, ...updatedValues };
    };

    const setFieldValidity = (field, validity) => {
        validityPerField.val = { ...validityPerField.rawVal, [field]: validity };
    };

    return div(
        { class: props.class },
        div(
            { class: 'mb-2' },
            div({ class: 'text-large' }, definition.test_name_short),
            definition.test_description || definition.default_test_description
                ? span({ class: 'text-caption mt-2' }, definition.test_description ?? definition.default_test_description)
                : null,
        ),
        () => div(
            { class: 'flex-row fx-flex-wrap fx-gap-3' },
            dynamicParamColumns.map(config => {
                const column = config.column;
                const currentValue = () => updatedDefinition.val[column] ?? config.default;

                if (config.type === 'select') {
                    return div(
                        { class: 'td-form--field' },
                        () => Select({
                            label: config.label,
                            options: config.options,
                            value: currentValue(),
                            onChange: (value) => setFieldValues({ [column]: value }),
                        }),
                    );
                }

                if (config.type === 'number') {
                    return div(
                        { class: 'td-form--field' },
                        () => Input({
                            name: column,
                            label: config.label,
                            help: config.help,
                            type: 'number',
                            value: currentValue(),
                            step: config.step,
                            onChange: (value, state) => {
                                setFieldValues({ [column]: value || null })
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
                            label: config.label,
                            help: config.help,
                            value: currentValue(),
                            height: 100,
                            onChange: (value) => {
                                setFieldValues({ [column]: value || null })
                            },
                        }),
                    );
                }

                const isSubsetCondition = subsetConditionColumns.includes(column);
                const originalValue = currentValue();

                return div(
                    { class: 'td-form--field' },
                    () => Input({
                        name: column,
                        label: config.label,
                        help: config.help,
                        // The no-op values are not intuitive for users, so we display empty input to imply no condition
                        // But we save it as "1=1" to not break the SQL templates
                        value: isSubsetCondition && subsetConditionNoopValues.includes(originalValue) ? '' : originalValue,
                        onChange: (value, state) => {
                            setFieldValues({ [column]: isSubsetCondition && !value ? '1=1' : value })
                            setFieldValidity(column, state.valid);
                        },
                    }),
                );
            }),
        ),
        hasThresholds
            ? ThresholdForm(
                { setFieldValues, setFieldValidity },
                definition,
            )
            : null,
    );
};

const thresholdModeOptions = [
    {
        label: 'Prediction Model',
        value: 'prediction',
        help: 'Use time series prediction to automatically determine expected bounds',
    },
    {
        label: 'Historical Calculation',
        value: 'historical',
        help: 'Calculate bounds based on historical results',
    },
    {
        label: 'Static Thresholds',
        value: 'static',
        help: 'Manually specify fixed upper and lower bounds',
    },
];

const historyCalcOptions = [
    { label: 'Value', value: 'Value' },
    { label: 'Minimum', value: 'Minimum' },
    { label: 'Maximum', value: 'Maximum' },
    { label: 'Sum', value: 'Sum' },
    { label: 'Average', value: 'Average' },
    { label: 'Expression', value: 'Expression' },
];

/**
 * @typedef ThresholdFormOptions
 * @type {object}
 * @property {(updatedValues: object) => void} setFieldValues
 * @property {(field: string, valid: boolean) => void} setFieldValidity
 * 
 * @param {ThresholdFormOptions} options 
 * @param {TestDefinition} definition 
 */
const ThresholdForm = (options, definition) => {
    const { setFieldValues, setFieldValidity } = options;
    const isFreshnessTrend = definition.test_type === 'Freshness_Trend';
    const initialHistoryCalc = definition.history_calculation;

    const initialMode = initialHistoryCalc === 'PREDICT' ? 'prediction' : initialHistoryCalc ? 'historical' : 'static';
    const mode = van.state(initialMode);

    const historyCalc = van.state(initialHistoryCalc === 'PREDICT' || !initialHistoryCalc ? 'Minimum' : initialHistoryCalc);
    const historyCalcUpper = van.state(definition.history_calculation_upper ?? 'Maximum');
    const historyLookback = van.state(definition.history_lookback || 10);
    const lowerTolerance = van.state(definition.lower_tolerance);
    const upperTolerance = van.state(definition.upper_tolerance);

    const lowerParsed = van.derive(() => parseExpressionValue(historyCalc.val));
    const upperParsed = van.derive(() => parseExpressionValue(historyCalcUpper.val));

    return div(
        { class: 'flex-column fx-gap-4 border border-radius-1 p-3 mt-5', style: 'position: relative;' },
        Caption({ content: 'Thresholds', style: 'position: absolute; top: -10px; background: var(--app-background-color); padding: 0px 8px;' }),
        RadioGroup({
            name: 'threshold_mode',
            options: isFreshnessTrend
                ? thresholdModeOptions.filter(option => option.value !== 'historical')
                : thresholdModeOptions,
            value: mode,
            layout: 'vertical',
            onChange: (newMode) => {
                mode.val = newMode;
                options.setFieldValues({
                    'history_calculation': newMode === 'prediction' ? 'PREDICT' : newMode === 'historical' ? historyCalc.val : null,
                    'history_calculation_upper': newMode === 'historical' ? historyCalcUpper.val : null,
                    'history_lookback': newMode === 'historical' ? historyLookback.val : null,
                    'lower_tolerance': newMode === 'static' ? lowerTolerance.val : newMode === 'prediction' ? definition.lower_tolerance : null,
                    'upper_tolerance': newMode === 'static' ? upperTolerance.val : newMode === 'prediction' ? definition.upper_tolerance : null,
                });
            },
        }),
        () => {
            if (mode.val === 'historical') {
                return div(
                    { class: 'flex-column fx-gap-3 mt-2' },
                    div(
                        { class: 'flex-row fx-align-flex-start fx-gap-3 fx-flex-wrap' },
                        div(
                            { class: 'td-form--field flex-column fx-gap-3' },
                            () => Select({
                                label: 'Lower Bound Calculation',
                                options: historyCalcOptions,
                                value: lowerParsed.val.selectValue,
                                onChange: (value) => {
                                    const fieldValue = value === 'Expression' ? formatExpressionValue('') : value;
                                    historyCalc.val = fieldValue;
                                    setFieldValues({ history_calculation: fieldValue });
                                },
                            }),
                            () => lowerParsed.val.isExpression
                                ? Input({
                                    name: 'history_calculation_expression',
                                    label: 'Lower Bound Expression',
                                    value: lowerParsed.val.expression,
                                    help: 'Use {VALUE}, {MINIMUM}, {MAXIMUM}, {SUM}, {AVERAGE}, {STANDARD_DEVIATION} to reference historical aggregates. Example: 0.5 * {AVERAGE}',
                                    onChange: (value) => {
                                        const fieldValue = formatExpressionValue(value);
                                        setFieldValues({ history_calculation: fieldValue });
                                    },
                                })
                                : '',
                        ),
                        div(
                            { class: 'td-form--field flex-column fx-gap-3' },
                            () => Select({
                                label: 'Upper Bound Calculation',
                                options: historyCalcOptions,
                                value: upperParsed.val.selectValue,
                                onChange: (value) => {
                                    const fieldValue = value === 'Expression' ? formatExpressionValue('') : value;
                                    historyCalcUpper.val = fieldValue;
                                    setFieldValues({ history_calculation_upper: fieldValue });
                                },
                            }),
                            () => upperParsed.val.isExpression
                                ? Input({
                                    name: 'history_calculation_upper_expression',
                                    label: 'Upper Bound Expression',
                                    value: upperParsed.val.expression,
                                    help: 'Use {VALUE}, {MINIMUM}, {MAXIMUM}, {SUM}, {AVERAGE}, {STANDARD_DEVIATION} to reference historical aggregates. Example: 1.5 * {AVERAGE}',
                                    onChange: (value) => {
                                        const fieldValue = formatExpressionValue(value);
                                        setFieldValues({ history_calculation_upper: fieldValue });
                                    },
                                })
                                : '',
                        ),
                    ),
                    div(
                        { class: 'flex-row fx-gap-3' },
                        div(
                            { class: 'td-form--field' },
                            Input({
                                name: 'history_lookback',
                                label: 'History Lookback',
                                type: 'number',
                                value: historyLookback,
                                help: 'Number of historical runs to use for calculation',
                                step: 1,
                                disabled: () => lowerParsed.val.selectValue === 'Value' && upperParsed.val.selectValue === 'Value',
                                onChange: (value, state) => {
                                    historyLookback.val = value;
                                    setFieldValues({ history_lookback: value });
                                    setFieldValidity('history_lookback', state.valid);
                                },
                                validators: [numberBetween(1, 1000, 1)],
                            }),
                        ),
                    )
                );
            }

            if (mode.val === 'static') {
                return div(
                    { class: 'flex-row fx-gap-3 fx-flex-wrap mt-2' },
                    !isFreshnessTrend 
                        ? div(
                            { class: 'td-form--field' },
                            Input({
                                name: 'lower_tolerance',
                                label: 'Lower Bound',
                                type: 'number',
                                value: lowerTolerance,
                                onChange: (value, state) => {
                                    lowerTolerance.val = value;
                                    setFieldValues({ lower_tolerance: value });
                                    setFieldValidity('lower_tolerance', state.valid);
                                },
                            }),
                        )
                        : null,
                    div(
                        { class: 'td-form--field' },
                        Input({
                            name: 'upper_tolerance',
                            label: isFreshnessTrend ? 'Maximum interval since last update (minutes)' : 'Upper Bound',
                            type: 'number',
                            value: upperTolerance,
                            onChange: (value, state) => {
                                upperTolerance.val = value;
                                setFieldValues({ upper_tolerance: value });
                                setFieldValidity('upper_tolerance', state.valid);
                            },
                        }),
                    ),
                );
            }

            return span({ class: 'text-caption mt-2' }, 'The prediction model will automatically determine expected bounds based on historical patterns.');
        },
    );
};

/**
 * @param {string?} value
 * @returns {{ isExpression: boolean, selectValue: string?, expression: string? }}
 */
const parseExpressionValue = (value) => {
    if (!value) {
        return { isExpression: false, selectValue: value, expression: null };
    }
    // Format: EXPR:[...]
    const match = value.match(/^EXPR:\[(.*)\]$/);
    if (match) {
        return { isExpression: true, selectValue: 'Expression', expression: match[1] };
    }
    return { isExpression: false, selectValue: value, expression: null };
};

/**
 * @param {string?} expression
 * @returns {string}
 */
const formatExpressionValue = (expression) => `EXPR:[${expression || ''}]`;

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
