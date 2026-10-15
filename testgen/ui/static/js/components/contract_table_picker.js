/**
 * @typedef Properties
 * @type {object}
 * @property {string[]} tables
 * @property {object} selected - VanJS state holding the selected table names
 * @property {((selected: string[]) => void)?} onChange
 * @property {boolean?} disabled
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { Select } from './select.js';
import { Button } from './button.js';

const { div, span } = van.tags;

const ContractTablePicker = (/** @type Properties */ props) => {
    const tables = getValue(props.tables) ?? [];
    const options = tables.map((name) => ({ label: name, value: name }));
    const selectAll = () => {
        props.selected.val = [...tables];
        props.onChange?.(props.selected.val);
    };

    return div(
        { class: 'flex-column fx-gap-1', 'data-testid': 'contract-table-picker' },
        div(
            { class: 'flex-row fx-gap-2 fx-align-flex-end' },
            Select({
                label: 'Tables',
                value: props.selected,
                options,
                multiSelect: true,
                filterable: true,
                required: true,
                disabled: props.disabled,
                style: 'flex: 1;',
                onChange: (value) => props.onChange?.(value),
            }),
            Button({
                type: 'stroked',
                label: 'Select all',
                width: 'auto',
                disabled: () => getValue(props.disabled) || !tables.length,
                onclick: selectAll,
            }),
        ),
        span(
            { class: 'text-caption' },
            () => `${props.selected.val.length} of ${tables.length} tables. The tables the contract covers.`,
        ),
    );
};

export { ContractTablePicker };
