/**
 * @typedef ColumnProfile
 * @type {object}
 * @property {'A' | 'B' | 'D' | 'N' | 'T' | 'X'} general_type
 * * Value Counts
 * @property {number} record_ct
 * @property {number} value_ct
 * @property {number} distinct_value_ct
 * @property {number} null_value_ct
 * @property {number} zero_value_ct
 * * Alpha
 * @property {number} zero_length_ct
 * @property {number} filled_value_ct
 * @property {number} includes_digit_ct
 * @property {number} numeric_ct
 * @property {number} date_ct
 * @property {number} quoted_value_ct
 * @property {number} lead_space_ct
 * @property {number} embedded_space_ct
 * @property {number} avg_embedded_spaces
 * @property {number} min_length
 * @property {number} max_length
 * @property {number} avg_length
 * @property {string} min_text
 * @property {string} max_text
 * @property {number} distinct_std_value_ct
 * @property {number} distinct_pattern_ct
 * @property {'STREET_ADDR' | 'STATE_USA' | 'PHONE_USA' | 'EMAIL' | 'ZIP_USA' | 'FILE_NAME' | 'CREDIT_CARD' | 'DELIMITED_DATA' | 'SSN'} std_pattern_match
 * @property {string} top_freq_values
 * @property {string} top_patterns
 * * Numeric
 * @property {number} min_value
 * @property {number} min_value_over_0
 * @property {number} max_value
 * @property {number} avg_value
 * @property {number} stdev_value
 * @property {number} percentile_25
 * @property {number} percentile_50
 * @property {number} percentile_75
 * * Date
 * @property {number} min_date
 * @property {number} max_date
 * @property {number} before_1yr_date_ct
 * @property {number} before_5yr_date_ct
 * @property {number} before_20yr_date_ct
 * @property {number} within_1yr_date_ct
 * @property {number} within_1mo_date_ct
 * @property {number} future_date_ct
 * * Boolean
 * @property {number} boolean_true_ct
 */
import van from '../van.min.js';
import { Attribute } from '../components/attribute.js';
import { SummaryBar } from './summary_bar.js';
import { PercentBar } from './percent_bar.js';
import { FrequencyBars } from './frequency_bars.js';
import { BoxPlot } from './box_plot.js';
import { loadStylesheet } from '../utils.js';
import { formatTimestamp, roundDigits } from '../display_utils.js';

const { div } = van.tags;
const columnTypeFunctionMap = {
    A: AlphaColumn,
    B: BooleanColumn,
    D: DatetimeColumn,
    N: NumericColumn,
};
const attributeWidth = 200;
const percentWidth = 250;
const summaryWidth = 400;
const summaryHeight = 10;
const boxPlotWidth = 800;

const ColumnProfile = (/** @type ColumnProfile */ item) => {
    loadStylesheet('column_profile', stylesheet);
    const columnFunction = columnTypeFunctionMap[item.general_type];
    return columnFunction ? columnFunction(item) : null;
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

    return div(
        { class: 'flex-column fx-gap-4' },
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4 tg-profile--fx-basis-content' },
            div(
                {
                    class: 'flex-column fx-gap-5',
                },
                DistinctsBar(item),
                SummaryBar({
                    height: summaryHeight,
                    width: summaryWidth,
                    label: `Missing Values: ${item.zero_length_ct + item.zero_value_ct + item.filled_value_ct + item.null_value_ct}`,
                    items: [
                        { label: 'Values', value: item.value_ct - item.zero_value_ct - item.filled_value_ct - item.zero_length_ct, color: 'green' },
                        { label: 'Zero Values', value: item.zero_value_ct, color: 'brown' },
                        { label: 'Dummy Values', value: item.filled_value_ct, color: 'orange' },
                        { label: 'Zero Length', value: item.zero_length_ct, color: 'yellow' },
                        { label: 'Null', value: item.null_value_ct, color: 'brownLight' },
                    ],
                }),
            ),
            div(
                {
                    class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-3 mb-1 tg-profile--fx-grow-content',
                },
                div(
                    { class: 'flex-column fx-gap-3' },
                    PercentBar({ label: 'Includes Digits', value: item.includes_digit_ct, total, width: percentWidth }),
                    PercentBar({ label: 'Numeric Values', value: item.numeric_ct, total, width: percentWidth }),
                    PercentBar({ label: 'Date Values', value: item.date_ct, total, width: percentWidth }),
                    PercentBar({ label: 'Quoted Values', value: item.quoted_value_ct, total, width: percentWidth }),
                ),
                div(
                    { class: 'flex-column fx-gap-3' },
                    PercentBar({ label: 'Leading Spaces', value: item.lead_space_ct, total, width: percentWidth }),
                    PercentBar({ label: 'Embedded Spaces', value: item.embedded_space_ct ?? 0, total, width: percentWidth }),
                    Attribute({ label: 'Average Embedded Spaces', value: roundDigits(item.avg_embedded_spaces), width: attributeWidth }),
                ),
            ),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: 'Minimum Length', value: item.min_length, width: attributeWidth }),
            Attribute({ label: 'Maximum Length', value: item.max_length, width: attributeWidth }),
            Attribute({ label: 'Average Length', value: roundDigits(item.avg_length), width: attributeWidth }),
            Attribute({ label: 'Minimum Text', value: item.min_text, width: attributeWidth }),
            Attribute({ label: 'Maximum Text', value: item.max_text, width: attributeWidth }),
            Attribute({ label: 'Distinct Standard Values', value: item.distinct_std_value_ct, width: attributeWidth }),
            Attribute({ label: 'Distinct Patterns', value: item.distinct_pattern_ct, width: attributeWidth }),
            Attribute({ label: 'Standard Pattern Match', value: standardPattern, width: attributeWidth }),
        ),
        item.top_freq_values || item.top_patterns ? div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4 mt-2 mb-2 tg-profile--fx-basis-content' },
            item.top_freq_values ? FrequencyBars({
                title: 'Frequent Values',
                total: item.record_ct,
                items: item.top_freq_values.substring(2).split('\n| ').map(parts => {
                    const [value, count] = parts.split(' | ');
                    return { value, count: Number(count) };
                }),
            }) : null,
            item.top_patterns ? FrequencyBars({
                title: 'Frequent Patterns',
                total: item.record_ct,
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
    );
}

function BooleanColumn(/** @type ColumnProfile */ item) {
    return SummaryBar({
        height: summaryHeight,
        width: summaryWidth,
        label: `Record count: ${item.record_ct}`,
        items: [
            { label: 'True', value: item.boolean_true_ct, color: 'brownLight' },
            { label: 'False', value: item.value_ct - item.boolean_true_ct, color: 'brown' },
            { label: 'Null', value: item.null_value_ct, color: 'brownDark' },
        ],
    });
}

function DatetimeColumn(/** @type ColumnProfile */ item) {
    const total = item.record_ct;

    return div(
        { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4 tg-profile--fx-basis-content' },
        div(
            DistinctsBar(item),
            div(
                { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-3 mt-5 tg-profile--fx-grow-content' },
                Attribute({ label: 'Minimum Date', value: formatTimestamp(item.min_date, true) }),
                Attribute({ label: 'Maximum Date', value: formatTimestamp(item.max_date, true) }),
            ),
        ),
        div(
            {
                class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-3 mb-1 tg-profile--fx-grow-content',
            },
            div(
                { class: 'flex-column fx-gap-3' },
                PercentBar({ label: 'Before 1 Year', value: item.before_1yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: 'Before 5 Year', value: item.before_5yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: 'Before 20 Year', value: item.before_20yr_date_ct, total, width: percentWidth }),
            ),
            div(
                { class: 'flex-column fx-gap-3' },
                PercentBar({ label: 'Within 1 Year', value: item.within_1yr_date_ct, total, width: percentWidth }),
                PercentBar({ label: 'Within 1 Month', value: item.within_1mo_date_ct, total, width: percentWidth }),
                PercentBar({ label: 'Future Dates', value: item.future_date_ct, total, width: percentWidth }),
            ),
        ),
    );
}

function NumericColumn(/** @type ColumnProfile */ item) {
    return [
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4 mb-5 tg-profile--fx-basis-content tg-profile--fx-grow-content' },
            div(
                DistinctsBar(item),
            ),
            div(
                PercentBar({ label: 'Zero Values', value: item.zero_value_ct, total: item.record_ct, width: percentWidth }),
            ),
        ),
        div(
            { class: 'flex-row fx-flex-wrap fx-align-flex-start fx-gap-4' },
            Attribute({ label: 'Minimum Value', value: item.min_value, width: attributeWidth }),
            Attribute({ label: 'Minimum Value > 0', value: item.min_value_over_0, width: attributeWidth }),
            Attribute({ label: 'Maximum Value', value: item.max_value, width: attributeWidth }),
            Attribute({ label: 'Average Value', value: roundDigits(item.avg_value), width: attributeWidth }),
            Attribute({ label: 'Standard Deviation', value: roundDigits(item.stdev_value), width: attributeWidth }),
            Attribute({ label: '25th Percentile', value: roundDigits(item.percentile_25), width: attributeWidth }),
            Attribute({ label: 'Median Value', value: roundDigits(item.percentile_50), width: attributeWidth }),
            Attribute({ label: '75th Percentile', value: roundDigits(item.percentile_75), width: attributeWidth }),
        ),
        div(
            { class: 'flex-row fx-justify-center mt-5 tg-profile--fx-grow-content' },
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
    ];
}

const DistinctsBar = (/** @type ColumnProfile */ item) => {
    return SummaryBar({
        height: summaryHeight,
        width: summaryWidth,
        label: `Record count: ${item.record_ct}`,
        items: [
            { label: 'Distinct', value: item.distinct_value_ct, color: 'blue' },
            { label: 'Non-Distinct', value: item.value_ct - item.distinct_value_ct, color: 'blueLight' },
            { label: 'Null', value: item.null_value_ct, color: 'brownLight' },
        ],
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-profile--fx-grow-content > * {
    flex-grow: 1;
}

.tg-profile--fx-basis-content > * {
    flex: 300px;
}
`);

export { ColumnProfile };
