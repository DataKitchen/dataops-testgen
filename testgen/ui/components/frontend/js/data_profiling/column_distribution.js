/**
 * @import { Column } from './data_profiling_utils.js';
 *
 * @typedef Properties
 * @type {object}
 * @property {boolean?} border
 * @property {boolean?} dataPreview
 * @property {boolean?} history
 */
import van from '../van.min.js';
import { Card } from '../components/card.js';
import { Attribute } from '../components/attribute.js';
import { Button } from '../components/button.js';
import { SummaryBar } from '../components/summary_bar.js';
import { PercentBar } from '../components/percent_bar.js';
import { FrequencyBars } from '../components/frequency_bars.js';
import { BoxPlot } from '../components/box_plot.js';
import { loadStylesheet, emitEvent, friendlyPercent, getValue } from '../utils.js';
import { formatNumber, formatTimestamp } from '../display_utils.js';

const { div, span } = van.tags;
const columnTypeFunctionMap = {
    A: AlphaColumn,
    B: BooleanColumn,
    D: DatetimeColumn,
    N: NumericColumn,
};
const attributeWidth = 250;
const percentWidth = 250;
const summaryWidth = 516;
const summaryHeight = 10;
const boxPlotWidth = 800;

const ColumnDistributionCard = (/** @type Properties */ props, /** @type Column */ item) => {
    loadStylesheet('column-distribution', stylesheet);
    const columnFunction = columnTypeFunctionMap[item.general_type];

    return Card({
        border: props.border,
        title: `Value Distribution ${item.is_latest_profile ? '*' : ''}`,
        content: item.profile_run_id
            ? (item.record_ct === 0
            ? BaseCounts(item)
            : columnFunction?.(item))
            : null,
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
                            onclick: () => emitEvent('DataPreviewClicked', { payload: item }),
                        })
                        : null,
                    getValue(props.history)
                        ? Button({
                            type: 'stroked',
                            label: 'History',
                            icon: 'history',
                            width: 'auto',
                            onclick: () => emitEvent('HistoryClicked', { payload: item }),
                        })
                        : null,
                ])
                : span(
                    { class: 'text-secondary' },
                    'No profiling data available',
                ),
        ),
    })
};

function AlphaColumn(/** @type ColumnProfile */ item) {
    const standardPatternLabels = {
        STREET_ADDR: 'Street Address',
        STATE_USA: 'State (USA)',
        PHONE_USA: 'Phone (USA)',
        EMAIL: 'Email',
        ZIP_USA: 'Zip Code (USA)',
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
                label: `Missing Values: ${formatNumber(missing)} (${friendlyPercent(missing * 100 / total)}%)`,
                items: [
                    { label: 'Actual Values', value: item.value_ct - item.zero_length_ct - item.filled_value_ct, color: 'green' },
                    { label: 'Null', value: item.null_value_ct, color: 'brownLight', showPercent: true },
                    { label: 'Zero Length', value: item.zero_length_ct, color: 'yellow' },
                    { label: 'Dummy Values', value: item.filled_value_ct, color: 'orange' },
                ],
            }),
            SummaryBar({
                height: summaryHeight,
                width: summaryWidth,
                label: `Duplicate Values: ${formatNumber(duplicates)} (${friendlyPercent(duplicates * 100 / item.value_ct)}%)`,
                items: [
                    { label: 'Distinct', value: item.distinct_value_ct, color: 'indigo' },
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
                        { label: 'Distinct', value: item.distinct_std_value_ct, color: 'indigo' },
                        { label: 'Duplicates', value: duplicatesStandardized, color: 'orange' },
                        { value: item.null_value_ct, color: 'empty' },
                    ],
                })
                : null,
            SummaryBar({
                height: summaryHeight,
                width: summaryWidth,
                label: 'Case Distribution',
                items: [
                    { label: 'Mixed Case', value: item.mixed_case_ct, color: 'purple' },
                    { label: 'Lower Case', value: item.lower_case_ct, color: 'blueLight' },
                    { label: 'Upper Case', value: item.upper_case_ct, color: 'blue' },
                    { label: 'Non-Alpha', value: item.non_alpha_ct, color: 'brown' },
                    { value: item.null_value_ct, color: 'empty' },
                ],
            }),
        ),
        item.top_freq_values || item.top_patterns ? div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-5 tg-profile--plot-block' },
            item.top_freq_values ? FrequencyBars({
                title: 'Frequent Values',
                total: item.record_ct,
                nullCount: item.null_value_ct,
                items: item.top_freq_values.substring(2).split('\n| ').map(parts => {
                    const [value, count] = parts.split(' | ');
                    return { value, count: Number(count) };
                }),
            }) : null,
            item.top_patterns ? FrequencyBars({
                title: 'Frequent Patterns',
                total: item.record_ct,
                nullCount: item.null_value_ct,
                items: item.top_patterns.split(' | ').reduce((array, item, index) => {
                    if (index % 2) {
                        array[(index - 1) / 2].value = item;
                    } else {
                        array.push({ count: Number(item) });
                    }
                    return array;
                }, []),
            }) : null,
        ) : null,
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            div(
                { class: 'flex-column fx-gap-3 tg-profile--percent-column' },
                PercentBar({ label: 'Includes Digits', value: item.includes_digit_ct, total, width: percentWidth }),
                PercentBar({ label: 'Numeric Values', value: item.numeric_ct, total, width: percentWidth }),
                PercentBar({ label: 'Zero Values', value: item.zero_value_ct, total, width: percentWidth }),
                PercentBar({ label: 'Date Values', value: item.date_ct, total, width: percentWidth }),
            ),
            div(
                { class: 'flex-column fx-gap-3 tg-profile--percent-column' },
                PercentBar({ label: 'Quoted Values', value: item.quoted_value_ct, total, width: percentWidth }),
                PercentBar({ label: 'Leading Spaces', value: item.lead_space_ct, total, width: percentWidth }),
                PercentBar({ label: 'Embedded Spaces', value: item.embedded_space_ct ?? 0, total, width: percentWidth }),
                Attribute({ label: 'Average Embedded Spaces', value: formatNumber(item.avg_embedded_spaces), width: attributeWidth }),
            ),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: 'Minimum Length', value: formatNumber(item.min_length), width: attributeWidth }),
            Attribute({ label: 'Maximum Length', value: formatNumber(item.max_length), width: attributeWidth }),
            Attribute({ label: 'Average Length', value: formatNumber(item.avg_length), width: attributeWidth }),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: 'Minimum Text', value: item.min_text, width: attributeWidth }),
            Attribute({ label: 'Maximum Text', value: item.max_text, width: attributeWidth }),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: 'Standard Pattern Match', value: standardPattern, width: attributeWidth }),
            Attribute({ label: 'Distinct Patterns', value: formatNumber(item.distinct_pattern_ct), width: attributeWidth }),
        ),
    );
}

function BooleanColumn(/** @type ColumnProfile */ item) {
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
                { label: 'Null', value: item.null_value_ct, color: 'brownDark' },
            ],
        }),
    );
}

function DatetimeColumn(/** @type ColumnProfile */ item) {
    const total = item.record_ct;

    return div(
        { class: 'flex-column fx-gap-5' },
        BaseCounts(item),
        SummaryBar({
            height: summaryHeight,
            width: summaryWidth,
            items: [
                { label: 'Values', value: item.record_ct - item.null_value_ct, color: 'blue' },
                { label: 'Null', value: item.null_value_ct, color: 'brownLight' },
            ],
        }),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            div(
                { class: 'flex-column fx-gap-3 tg-profile--percent-column' },
                PercentBar({ label: 'Before 1 Year', value: item.before_1yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: 'Before 5 Years', value: item.before_5yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: 'Before 20 Years', value: item.before_20yr_date_ct, total, width: percentWidth }),
            ),
            div(
                { class: 'flex-column fx-gap-3 tg-profile--percent-column' },
                PercentBar({ label: 'Within 1 Year', value: item.within_1yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: 'Within 1 Month', value: item.within_1mo_date_ct, total, width: percentWidth }),
                PercentBar({ label: 'Future Dates', value: item.future_date_ct, total, width: percentWidth }),
            ),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: 'Minimum Date', value: formatTimestamp(item.min_date, true), width: attributeWidth }),
            Attribute({ label: 'Maximum Date', value: formatTimestamp(item.max_date, true), width: attributeWidth }),
            Attribute({ label: 'Distinct Values', value: formatNumber(item.distinct_value_ct), width: attributeWidth }),
        ),
    );
}

function NumericColumn(/** @type ColumnProfile */ item) {
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
                    { label: 'Zero Values', value: item.zero_value_ct, color: 'brown' },
                    { label: 'Null', value: item.null_value_ct, color: 'brownLight' },
                ],
            }),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4 tg-profile--attribute-block' },
            Attribute({ label: 'Distinct Values', value: formatNumber(item.distinct_value_ct), width: attributeWidth }),
            Attribute({ label: 'Average Value', value: formatNumber(item.avg_value), width: attributeWidth }),
            Attribute({ label: 'Standard Deviation', value: formatNumber(item.stdev_value), width: attributeWidth }),
            Attribute({ label: 'Minimum Value', value: formatNumber(item.min_value), width: attributeWidth }),
            Attribute({ label: 'Minimum Value > 0', value: formatNumber(item.min_value_over_0), width: attributeWidth }),
            Attribute({ label: 'Maximum Value', value: formatNumber(item.max_value), width: attributeWidth }),
            Attribute({ label: '25th Percentile', value: formatNumber(item.percentile_25), width: attributeWidth }),
            Attribute({ label: 'Median Value', value: formatNumber(item.percentile_50), width: attributeWidth }),
            Attribute({ label: '75th Percentile', value: formatNumber(item.percentile_75), width: attributeWidth }),
        ),
        div(
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

const BaseCounts = (/** @type ColumnProfile */ item) => {
    const attributes = [
        { key: 'record_ct', label: 'Record Count' },
        { key: 'value_ct', label: 'Value Count' },
    ];
    return div(
        { class: 'flex-row fx-gap-4' },
        attributes.map(({ key, label }) => Attribute({ 
            label: item[key] === 0 ? span({ class: 'text-error' }, label) : label, 
            value: formatNumber(item[key]),
            width: attributeWidth,
        })),
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
