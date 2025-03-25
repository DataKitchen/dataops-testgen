/**
 * @import { Table } from './data_profiling_utils.js';
 *
 * @typedef Properties
 * @type {object}
 */
import van from '../van.min.js';
import { Card } from '../components/card.js';
import { Attribute } from '../components/attribute.js';
import { Button } from '../components/button.js';
import { emitEvent } from '../utils.js';

const { div } = van.tags;

const TableSizeCard = (/** @type Properties */ _props, /** @type Table */ item) => {
    const attributes = [
        { key: 'column_ct', label: 'Column Count' },
        { key: 'record_ct', label: 'Row Count' },
        { key: 'data_point_ct', label: 'Data Point Count' },
    ]

    return Card({
        title: 'Table Size',
        content: div(
            { class: 'flex-row fx-flex-wrap fx-gap-4' },
            attributes.map(({ key, label }) => Attribute({ label, value: item[key], width: 250 })),
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
