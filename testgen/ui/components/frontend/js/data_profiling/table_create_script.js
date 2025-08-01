/**
 * @import { Table } from './data_profiling_utils.js';
 *
 * @typedef Properties
 * @type {object}
 */
import van from '../van.min.js';
import { Card } from '../components/card.js';
import { Button } from '../components/button.js';
import { emitEvent } from '../utils.js';

const { div } = van.tags;

const TableCreateScriptCard = (/** @type Properties */ _props, /** @type Table */ item) => {
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
                onclick: () => emitEvent('CreateScriptClicked', { payload: item }),
            }),
        ),
    });
};

export { TableCreateScriptCard };
