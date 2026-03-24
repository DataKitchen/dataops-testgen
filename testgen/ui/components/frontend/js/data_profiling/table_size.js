/**
 * @import { Table } from './data_profiling_utils.js';
 *
 * @typedef Properties
 * @type {object}
 */
import van from '/app/static/js/van.min.js';
import { Card } from '/app/static/js/components/card.js';
import { Attribute } from '/app/static/js/components/attribute.js';
import { Button } from '/app/static/js/components/button.js';
import { emitEvent } from '/app/static/js/utils.js';
import { formatNumber, formatTimestamp } from '/app/static/js/display_utils.js';

const { div, span } = van.tags;

const TableSizeCard = (/** @type Properties */ _props, /** @type Table */ item) => {
    const useApprox = item.record_ct === null;
    const rowCount = useApprox ? item.approx_record_ct : item.record_ct;
    const attributes = [
        { label: 'Column Count', value: item.column_ct },
        { label: `Row Count${useApprox ? ' †': ''}`, value: rowCount },
        {
            label: `Data Point Count${useApprox ? ' †': ''}`,
            value: rowCount !== null ? (item.column_ct * rowCount) : null,
        }
    ];

    return Card({
        title: 'Table Size **',
        content: div(
            div(
                { class: 'flex-row fx-flex-wrap fx-gap-4' },
                attributes.map(({ label, value }) => Attribute({ 
                    label: value === 0 ? span({ class: 'text-error' }, label) : label, 
                    value: formatNumber(value),
                    width: 250,
                })),
            ),
            div({ class: 'text-caption text-right mt-1' }, `** as of ${formatTimestamp(item.last_refresh_date)}`),
            useApprox
                ? div({ class: 'text-caption text-right mt-1' }, '† Approximate counts based on server statistics')
                : null,
        ),
        actionContent: Button({
            type: 'stroked',
            label: 'Data Preview',
            icon: 'pageview',
            width: 'auto',
            onclick: () => emitEvent('DataPreviewClicked', { payload: item }),
        }),
    });
};

export { TableSizeCard };
