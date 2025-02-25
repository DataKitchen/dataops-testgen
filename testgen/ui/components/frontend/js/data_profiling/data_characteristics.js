/**
 * @import { Column, Table } from './data_profiling_utils.js';
 *
 * @typedef Properties
 * @type {object}
 * @property {boolean?} scores
 * @property {boolean?} border
 */
import van from '../van.min.js';
import { Card } from '../components/card.js';
import { Attribute } from '../components/attribute.js';
import { ScoreMetric } from '../components/score_metric.js';
import { formatTimestamp } from '../display_utils.js';
import { loadStylesheet } from '../utils.js';
import { getColumnIcon } from './data_profiling_utils.js';

const { div, span, i } = van.tags;

const DataCharacteristicsCard = (/** @type Properties */ props, /** @type Column | Table */ item) => {
    loadStylesheet('data-characteristics', stylesheet);

    let attributes = [];
    if (item.type === 'column') {
        attributes.push(
            { key: 'column_type', label: 'Data Type' },
            { key: 'datatype_suggestion', label: `Suggested Data Type ${item.is_latest_profile ? '*' : ''}` },
            { key: 'functional_data_type', label: `Semantic Data Type ${item.is_latest_profile ? '*' : ''}` },
        );
    } else {
        attributes.push(
            { key: 'functional_table_type', label: `Semantic Table Type ${item.is_latest_profile ? '*' : ''}` },
        );
    }
    if (item.add_date) {
        attributes.push({ key: 'add_date', label: 'First Detected' });
    }
    if (item.last_mod_date !== item.add_date) {
        attributes.push({ key: 'last_mod_date', label: 'Modification Detected' });
    }
    if (item.drop_date) {
        attributes.push({ key: 'drop_date', label: 'Drop Detected' });
    }

    return Card({
        border: props.border,
        title: `${item.type} Characteristics`,
        content: div(
            { class: 'flex-row fx-gap-4 fx-justify-space-between' },
            div(
                { class: 'flex-row fx-flex-wrap fx-gap-4' },
                attributes.map(({ key, label }) => {
                    let value = item[key];
                    if (key === 'column_type') {
                        const { icon, iconSize } = getColumnIcon(item);
                        value = div(
                            { class: 'flex-row' },
                            i(
                                {
                                    class: 'material-symbols-rounded tg-data-chars--column-icon',
                                    style: `font-size: ${iconSize || 24}px;`,
                                },
                                icon,
                            ),
                            (value || 'unknown').toLowerCase(),
                        );
                    } else if (key === 'datatype_suggestion') {
                        value = (value || '').toLowerCase();
                    } else if (key === 'functional_table_type') {
                        value = (value || '').split('-')
                            .map(word => word ? (word[0].toUpperCase() + word.substring(1)) : '')
                            .join(' ');
                    } else if (['add_date', 'last_mod_date', 'drop_date'].includes(key)) {
                        value = formatTimestamp(value, true);
                        if (key === 'drop_date') {
                            label = span({ class: 'text-error' }, label);
                        }
                    }

                    return Attribute({ label, value, width: 250 });
                }),
            ),
            props.scores ? div(
                { style: 'margin-top: -40px;' },
                ScoreMetric(item.dq_score, item.dq_score_profiling, item.dq_score_testing),
            ) : null,
        ),
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-data-chars--column-icon {
    margin-right: 4px;
    width: 24px;
    color: #B0BEC5;
    text-align: center;
}
`);

export { DataCharacteristicsCard };
