/**
 * @import { Column } from './data_profiling_utils.js';
 *
 * @typedef Properties
 * @type {object}
 * @property {boolean?} border
 * @property {boolean?} dataPreview
 * @property {boolean?} history
 */
import van from '/app/static/js/van.min.js';
import { Card } from '/app/static/js/components/card.js';
import { Attribute } from '/app/static/js/components/attribute.js';
import { Button } from '/app/static/js/components/button.js';
import { Alert } from '/app/static/js/components/alert.js';
import { SummaryBar } from '/app/static/js/components/summary_bar.js';
import { PercentBar } from '/app/static/js/components/percent_bar.js';
import { FrequencyBars } from '/app/static/js/components/frequency_bars.js';
import { BoxPlot } from '/app/static/js/components/box_plot.js';
import { Icon } from '/app/static/js/components/icon.js';
import { withTooltip } from '/app/static/js/components/tooltip.js';
import { loadStylesheet, friendlyPercent, getValue } from '/app/static/js/utils.js';
import { formatNumber, formatTimestamp, PII_REDACTED } from '/app/static/js/display_utils.js';
import { frequencyItems } from './data_profiling_utils.js';

const { div, span } = van.tags;
const columnTypeFunctionMap = {
    A: AlphaColumn,
    B: BooleanColumn,
    D: DatetimeColumn,
    N: NumericColumn,
    X: UnknownColumn,
};
const attributeWidth = 250;
const percentWidth = 250;
const summaryWidth = 516;
const summaryHeight = 10;
const boxPlotWidth = 800;

const ColumnDistributionCard = (/** @type Properties */ props, /** @type Column */ item) => {
    const emit = props.emit;
    loadStylesheet('column-distribution', stylesheet);
    const displayType = item.profile_run_id && item.record_ct !== 0 ? item.general_type : 'X'
    const columnFunction = columnTypeFunctionMap[displayType];

    return Card({
        border: props.border,
        title: `Value Distribution ${item.is_latest_profile ? '*' : ''}`,
        content: columnFunction?.(item),
        actionContent: div(
            { class: 'flex-row fx-gap-3' },
            item.profile_run_id
                ? ([
                    getValue(props.dataPreview)
                        ? Button({
                            type: 'stroked',
                            label: 'Data Preview',
                            icon: 'pageview',
                            width: 'auto',
                            onclick: () => emit('DataPreviewClicked', { payload: item }),
                        })
                        : null,
                    getValue(props.history)
                        ? Button({
                            type: 'stroked',
                            label: 'History',
                            icon: 'history',
                            width: 'auto',
                            onclick: () => emit('HistoryClicked', { payload: item }),
                        })
                        : null,
                ])
                : span(
                    { class: 'text-secondary' },
                    'No profiling results for column',
                ),
        ),
    })
};

function AlphaColumn(/** @type Column */ item) {
    const standardPatternLabels = {
        STREET_ADDR: 'Street Address',
        STATE_USA: 'State (USA)',
        PHONE_USA: 'Phone (USA)',
        EMAIL: 'Email',
        ZIP_USA: 'Zip Code (USA)',
        ZIP_US_CA: 'Zip Code (US/Canada)',
        FILE_NAME: 'Filename',
        CREDIT_CARD: 'Credit Card',
        DELIMITED_DATA: 'Delimited Data',
        SSN: 'SSN (USA)',
    };
    let standardPattern = standardPatternLabels[item.std_pattern_match];
    if (!standardPattern) {
        standardPattern = (item.std_pattern_match || '').split('_')
            .map(word => word ? (word[0].toUpperCase() + word.substring(1)) : '')
            .join(' ');
    }

    const total = item.record_ct;
    const missing = item.null_value_ct + item.zero_length_ct + item.filled_value_ct;
    const duplicates = item.value_ct - item.distinct_value_ct;
    const duplicatesStandardized = item.value_ct - item.distinct_std_value_ct;

    return div(
        { class: 'flex-column fx-gap-5' },
        BaseCounts(item),
        div(
            { class: 'flex-column fx-gap-4' },
            SummaryBar({
                height: summaryHeight,
                width: summaryWidth,
                label: withProvenanceMark(
                    `Missing Values: ${formatNumber(missing)} (${friendlyPercent(missing * 100 / total)}%)`,
                    item,
                    'filled_value_ct',
                ),
                items: [
                    { label: 'Actual Values', value: item.value_ct - item.zero_length_ct - item.filled_value_ct, color: 'green' },
                    { label: measureLabel(item, 'null_value_ct'), value: item.null_value_ct, color: 'brownLight', showPercent: true },
                    { label: measureLabel(item, 'zero_length_ct'), value: item.zero_length_ct, color: 'yellow' },
                    { label: measureLabel(item, 'filled_value_ct'), value: item.filled_value_ct, color: 'orange' },
                ],
            }),
            SummaryBar({
                height: summaryHeight,
                width: summaryWidth,
                label: `Duplicate Values: ${formatNumber(duplicates)} (${friendlyPercent(duplicates * 100 / item.value_ct)}%)`,
                items: [
                    { label: measureLabel(item, 'distinct_value_ct'), value: item.distinct_value_ct, color: 'indigo' },
                    { label: 'Duplicates', value: duplicates, color: 'orange' },
                    { value: item.null_value_ct, color: 'empty' },
                ],
            }),
            item.distinct_std_value_ct != item.distinct_value_ct
                ? SummaryBar({
                    height: summaryHeight,
                    width: summaryWidth,
                    label: `Duplicate Values, Standardized: ${formatNumber(duplicatesStandardized)} (${friendlyPercent(duplicatesStandardized * 100 / item.value_ct)}%)`,
                    items: [
                        { label: measureLabel(item, 'distinct_std_value_ct'), value: item.distinct_std_value_ct, color: 'indigo' },
                        { label: 'Duplicates', value: duplicatesStandardized, color: 'orange' },
                        { value: item.null_value_ct, color: 'empty' },
                    ],
                })
                : null,
            SummaryBar({
                height: summaryHeight,
                width: summaryWidth,
                label: withProvenanceMark('Case Distribution', item, 'upper_case_ct'),
                items: [
                    { label: measureLabel(item, 'mixed_case_ct'), value: item.mixed_case_ct, color: 'purple' },
                    { label: measureLabel(item, 'lower_case_ct'), value: item.lower_case_ct, color: 'blueLight' },
                    { label: measureLabel(item, 'upper_case_ct'), value: item.upper_case_ct, color: 'blue' },
                    { label: measureLabel(item, 'non_alpha_ct'), value: item.non_alpha_ct, color: 'brown' },
                    { value: item.null_value_ct, color: 'empty' },
                ],
            }),
        ),
        item.frequent_values || item.frequent_patterns ? div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-5 tg-profile--plot-block' },
            item.frequent_values === PII_REDACTED
                ? Attribute({ label: measureLabel(item, 'frequent_values'), value: PII_REDACTED, width: attributeWidth })
                : item.frequent_values ? FrequencyBars({
                    title: measureLabelWithMark(item, 'frequent_values'),
                    total: item.record_ct,
                    nullCount: item.null_value_ct,
                    items: frequencyItems(item.frequent_values),
                }) : null,
            item.frequent_patterns ? FrequencyBars({
                title: measureLabelWithMark(item, 'frequent_patterns'),
                total: item.record_ct,
                nullCount: item.null_value_ct,
                items: frequencyItems(item.frequent_patterns),
            }) : null,
        ) : null,
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            div(
                { class: 'flex-column fx-gap-3 tg-profile--percent-column' },
                PercentBar({ label: measureLabel(item, 'includes_digit_ct'), adornment: ProvenanceMark(item, 'includes_digit_ct'), value: item.includes_digit_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'numeric_ct'), adornment: ProvenanceMark(item, 'numeric_ct'), value: item.numeric_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'zero_value_ct'), value: item.zero_value_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'date_ct'), adornment: ProvenanceMark(item, 'date_ct'), value: item.date_ct, total, width: percentWidth }),
            ),
            div(
                { class: 'flex-column fx-gap-3 tg-profile--percent-column' },
                PercentBar({ label: measureLabel(item, 'quoted_value_ct'), adornment: ProvenanceMark(item, 'quoted_value_ct'), value: item.quoted_value_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'lead_space_ct'), adornment: ProvenanceMark(item, 'lead_space_ct'), value: item.lead_space_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'embedded_space_ct'), adornment: ProvenanceMark(item, 'embedded_space_ct'), value: item.embedded_space_ct ?? 0, total, width: percentWidth }),
                Attribute({ label: measureLabelWithMark(item, 'avg_embedded_spaces'), value: formatNumber(item.avg_embedded_spaces), width: attributeWidth }),
            ),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: measureLabel(item, 'min_length'), value: formatNumber(item.min_length), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'max_length'), value: formatNumber(item.max_length), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'avg_length'), value: formatNumber(item.avg_length), width: attributeWidth }),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: measureLabel(item, 'min_text'), value: item.min_text, width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'max_text'), value: item.max_text, width: attributeWidth }),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: measureLabelWithMark(item, 'std_pattern_match'), value: standardPattern, width: attributeWidth }),
            Attribute({ label: measureLabelWithMark(item, 'distinct_pattern_ct'), value: formatNumber(item.distinct_pattern_ct), width: attributeWidth }),
        ),
    );
}

function BooleanColumn(/** @type Column */ item) {
    return div(
        { class: 'flex-column fx-gap-5' },
        BaseCounts(item),
        SummaryBar({
            height: summaryHeight,
            width: summaryWidth,
            label: 'Boolean Distribution',
            items: [
                { label: 'True', value: item.boolean_true_ct, color: 'brownLight' },
                { label: 'False', value: item.value_ct - item.boolean_true_ct, color: 'brown' },
                { label: measureLabel(item, 'null_value_ct'), value: item.null_value_ct, color: 'brownDark' },
            ],
        }),
    );
}

function DatetimeColumn(/** @type Column */ item) {
    const total = item.record_ct;

    return div(
        { class: 'flex-column fx-gap-5' },
        BaseCounts(item),
        SummaryBar({
            height: summaryHeight,
            width: summaryWidth,
            items: [
                { label: 'Values', value: item.record_ct - item.null_value_ct, color: 'blue' },
                { label: measureLabel(item, 'null_value_ct'), value: item.null_value_ct, color: 'brownLight' },
            ],
        }),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            div(
                { class: 'flex-column fx-gap-3 tg-profile--percent-column' },
                PercentBar({ label: measureLabel(item, 'before_1yr_date_ct'), value: item.before_1yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'before_5yr_date_ct'), value: item.before_5yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'before_20yr_date_ct'), value: item.before_20yr_date_ct, total, width: percentWidth }),
            ),
            div(
                { class: 'flex-column fx-gap-3 tg-profile--percent-column' },
                PercentBar({ label: measureLabel(item, 'within_1yr_date_ct'), value: item.within_1yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'within_1mo_date_ct'), value: item.within_1mo_date_ct, total, width: percentWidth }),
                PercentBar({ label: measureLabel(item, 'future_date_ct'), value: item.future_date_ct, total, width: percentWidth }),
            ),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: measureLabel(item, 'min_date'), value: formatTimestamp(item.min_date, true), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'max_date'), value: formatTimestamp(item.max_date, true), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'distinct_value_ct'), value: formatNumber(item.distinct_value_ct), width: attributeWidth }),
        ),
    );
}

function NumericColumn(/** @type Column */ item) {
    return div(
        { class: 'flex-column fx-gap-5' },
        BaseCounts(item),
        div(
            SummaryBar({
                height: summaryHeight,
                width: summaryWidth,
                label: 'Numeric Distribution',
                items: [
                    { label: 'Non-Zero Values', value: item.record_ct - item.zero_value_ct - item.null_value_ct, color: 'blue' },
                    { label: measureLabel(item, 'zero_value_ct'), value: item.zero_value_ct, color: 'brown' },
                    { label: measureLabel(item, 'null_value_ct'), value: item.null_value_ct, color: 'brownLight' },
                ],
            }),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4 tg-profile--attribute-block' },
            Attribute({ label: measureLabel(item, 'distinct_value_ct'), value: formatNumber(item.distinct_value_ct), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'avg_value'), value: formatNumber(item.avg_value), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'stdev_value'), value: formatNumber(item.stdev_value), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'min_value'), value: formatNumber(item.min_value), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'min_value_over_0'), value: formatNumber(item.min_value_over_0), width: attributeWidth }),
            Attribute({ label: measureLabel(item, 'max_value'), value: formatNumber(item.max_value), width: attributeWidth }),
            Attribute({ label: measureLabelWithMark(item, 'percentile_25'), value: formatNumber(item.percentile_25), width: attributeWidth }),
            Attribute({ label: measureLabelWithMark(item, 'percentile_50'), value: formatNumber(item.percentile_50), width: attributeWidth }),
            Attribute({ label: measureLabelWithMark(item, 'percentile_75'), value: formatNumber(item.percentile_75), width: attributeWidth }),
        ),
        item.min_value === PII_REDACTED || item.max_value === PII_REDACTED ? null : div(
                { class: 'flex-row fx-justify-center tg-profile--plot-block' },
                BoxPlot({
                    minimum: item.min_value,
                    maximum: item.max_value,
                    median: item.percentile_50,
                    lowerQuartile: item.percentile_25,
                    upperQuartile: item.percentile_75,
                    average: item.avg_value,
                    standardDeviation: item.stdev_value,
                    width: boxPlotWidth,
                }),
            ),
    );
}

function UnknownColumn(/** @type Column */ item) {
    return div(
        { class: 'flex-column fx-gap-3' },
        BaseCounts(item),
        item.profiling_error
            ? Alert(
                { type: 'warn', icon: 'warning' },
                div({ style: 'font-size: 14px;' }, 'Profiling encountered an error for this column.'),
                div({ class: 'text-primary text-code', style: 'font-size: 12px;' }, item.profiling_error),
            )
            : null,
    );
}

/**
 * The name of a measure, as the profile row carries it.
 *
 * @param {Column} item
 * @param {string} measure
 * @returns {string}
 */
const measureLabel = (item, measure) => item.measure_labels?.[measure] ?? measure;

/**
 * A mark whose tooltip says how a measure was taken, or null when the measure is exact.
 *
 * @param {Column} item
 * @param {string} measure
 */
const ProvenanceMark = (item, measure) => {
    const kind = item.provenance?.kinds?.[measure];
    if (!kind) {
        return null;
    }
    const mark = Icon(
        { size: 12, classes: 'ml-1' },
        kind === 'approximate' ? 'airwave' : 'clock_loader_40',
    );
    return withTooltip(mark, { text: item.provenance.descriptions[kind], position: 'top' });
};

/**
 * A label followed by its measure's provenance mark, or the bare label when the measure is exact.
 *
 * @param {string} label
 * @param {Column} item
 * @param {string} measure
 */
const withProvenanceMark = (label, item, measure) => {
    const mark = ProvenanceMark(item, measure);
    return mark ? span({ class: 'flex-row fx-gap-1' }, label, mark) : label;
};

/**
 * A measure's name followed by its provenance mark, or the bare name when the measure is exact.
 *
 * @param {Column} item
 * @param {string} measure
 */
const measureLabelWithMark = (item, measure) => withProvenanceMark(measureLabel(item, measure), item, measure);

const BaseCounts = (/** @type Column */ item) => {
    const useApprox = item.record_ct === null;
    const attributes = [
        {
            label: `${measureLabel(item, 'record_ct')}${useApprox ? ' †' : ''}`,
            value: useApprox ? item.approx_record_ct : item.record_ct,
        }
    ];
    if (item.value_ct !== null) {
        attributes.push({ label: measureLabel(item, 'value_ct'), value: item.value_ct });
    }
    return div(
        div(
            { class: 'flex-row fx-gap-4' },
            attributes.map(({ label, value }) => Attribute({
                label: value === 0 ? span({ class: 'text-error' }, label) : label,
                value: formatNumber(value),
                width: attributeWidth,
            })),
        ),
        useApprox
            ? div({ class: 'text-caption text-right mt-1' }, '† Approximate count based on server statistics')
            : null,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-profile--plot-block > * {
    flex: 250px;
}
.tg-profile--percent-column {
    flex: 0 1 250px;
}
.tg-profile--attribute-block {
    max-width: 800px;
}
`);

export { ColumnDistributionCard };
