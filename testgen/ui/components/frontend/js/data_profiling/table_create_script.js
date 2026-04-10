/**
 * @import { Table } from './data_profiling_utils.js';
 *
 * @typedef Properties
 * @type {object}
 */
import van from '/app/static/js/van.min.js';
import { Card } from '/app/static/js/components/card.js';
import { Button } from '/app/static/js/components/button.js';

const { div } = van.tags;

const TableCreateScriptCard = (/** @type Properties */ _props, /** @type Table */ item) => {
    const emit = _props.emit;
    return Card({
        title: 'Table CREATE Script with Suggested Data Types',
        content: div(
            Button({
                type: 'stroked',
                label: 'View Script',
                icon: 'sdk',
                width: 'auto',
                disabled: !item.column_ct,
                tooltip: item.column_ct ? null : 'No columns detected in table',
                tooltipPosition: 'right',
                onclick: () => emit('CreateScriptClicked', { payload: item }),
            }),
        ),
    });
};

export { TableCreateScriptCard };
