/**
 * @import { Column, Table } from './data_profiling_utils.js';
 *
 * @typedef Properties
 * @type {object}
 * @property {boolean?} scores
 * @property {boolean?} border
 * @property {boolean?} allowRemove
 */
import van from '/app/static/js/van.min.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Card } from '/app/static/js/components/card.js';
import { Attribute } from '/app/static/js/components/attribute.js';
import { Button } from '/app/static/js/components/button.js';
import { ScoreMetric } from '/app/static/js/components/score_metric.js';
import { formatTimestamp } from '/app/static/js/display_utils.js';
import { loadStylesheet } from '/app/static/js/utils.js';
import { getColumnIcon } from './data_profiling_utils.js';

const { b, div, span, i } = van.tags;

const DataCharacteristicsCard = (/** @type Properties */ props, /** @type Column | Table */ item) => {
    const emit = props.emit;
    loadStylesheet('data-characteristics', stylesheet);
    const removeDialogOpen = van.state(false);

    let attributes = [];
    if (item.type === 'column') {
        attributes.push(
            { key: 'db_data_type', label: 'Data Type' },
            { key: 'functional_data_type', label: `Semantic Data Type ${item.is_latest_profile ? '*' : ''}` },
        );
        if (item.datatype_suggestion && item.datatype_suggestion.toLowerCase() !== item.db_data_type.toLowerCase()) {
            attributes.push(
                { key: 'datatype_suggestion', label: `Suggested Data Type ${item.is_latest_profile ? '*' : ''}` },
            );
        }
    } else {
        attributes.push(
            { key: 'functional_table_type', label: `Semantic Table Type ${item.is_latest_profile ? '*' : ''}` },
        );
    }
    if (item.add_date) {
        attributes.push({ key: 'add_date', label: 'First Detected' });
    }
    if (item.last_mod_date && item.last_mod_date !== item.add_date) {
        attributes.push({ key: 'last_mod_date', label: 'Modification Detected' });
    }
    if (item.drop_date) {
        attributes.push({ key: 'drop_date', label: 'Drop Detected' });
    }

    return div(
        Card({
            border: props.border,
            title: `${item.type} Characteristics`,
            content: div(
                { class: 'flex-row fx-gap-4 fx-justify-space-between' },
                div(
                    { class: 'flex-column fx-align-flex-start fx-gap-3' },
                    div(
                        { class: 'flex-row fx-flex-wrap fx-gap-4' },
                        attributes.map(({ key, label }) => {
                            let value = item[key];
                            if (key === 'db_data_type') {
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
                    props.allowRemove && item.drop_date && item.type === 'table'
                        ? Button({
                            type: 'stroked',
                            color: 'warn',
                            label: 'Remove from Catalog',
                            icon: 'delete',
                            width: 'auto',
                            disabled: item.test_suites.length,
                            tooltip: item.test_suites.length ? 'The table has associated test definitions and cannot be removed from Data Catalog. Delete the test definitions first.' : 'Remove the table and its columns from Data Catalog',
                            tooltipPosition: 'right',
                            onclick: () => { removeDialogOpen.val = true; },
                        })
                        : null,
                ),
                props.scores ? div(
                    { style: 'margin-top: -40px;' },
                    ScoreMetric(item.dq_score, item.dq_score_profiling, item.dq_score_testing),
                ) : null,
            ),
        }),
        Dialog(
            { title: 'Remove Table from Catalog', open: removeDialogOpen, onClose: () => removeDialogOpen.val = false },
            div(
                { class: 'flex-column fx-gap-4' },
                div('Are you sure you want to remove the table ', b(item.table_name), ' from the data catalog?'),
                div({ style: 'color: var(--orange);' }, 'This action cannot be undone.'),
                div(
                    { class: 'flex-row fx-justify-flex-end' },
                    Button({
                        label: 'Remove',
                        color: 'warn',
                        type: 'flat',
                        width: 'auto',
                        style: 'margin-left: auto;',
                        onclick: () => {
                            emit('RemoveTableConfirmed', { payload: item });
                            removeDialogOpen.val = false;
                        },
                    }),
                ),
            ),
        ),
    );
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
