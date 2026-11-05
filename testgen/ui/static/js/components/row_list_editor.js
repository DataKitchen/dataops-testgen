/**
 * @typedef RowColumn
 * @type {object}
 * @property {string} name
 * @property {string} label
 * @property {boolean?} required
 * @property {number?} flex - the column's share of the row's width; defaults to 1
 * @property {('text' | 'date' | 'select')?} type - defaults to 'text'; a date column uses the browser's date
 *     picker, and a select column offers `options` and accepts any other value typed and entered
 * @property {string[]?} options - a select column's values
 * @property {string?} placeholder
 * @property {Array<function(string): string?>?} validators
 *
 * @typedef Row
 * @type {object}
 * @property {string} key - identifies the row while the form is open
 *
 * @typedef Properties
 * @type {object}
 * @property {RowColumn[]} columns
 * @property {Row[]} rows - the rows the editor opens with
 * @property {function(Row[]): void} onChange - called with every row on each change
 * @property {string} addLabel
 * @property {string} emptyText
 * @property {string?} testId
 */
import van from '../van.min.js';
import { getRandomId, loadStylesheet } from '../utils.js';
import { required } from '../form_validators.js';
import { Button } from './button.js';
import { DateInput } from './date_input.js';
import { Input } from './input.js';
import { Select } from './select.js';

const { div, span } = van.tags;

// The header marks a required column once, so a cell's validator must not be the one Input recognizes by name
// and marks again with an asterisk of its own.
const requiredCell = (value) => required(value);

const columnValidators = (/** @type RowColumn */ column) => [
    ...(column.required ? [requiredCell] : []),
    ...(column.validators ?? []),
];

/** Whether every row passes its columns' validators, a required column included. */
const rowsValid = (/** @type RowColumn[] */ columns, /** @type Row[] */ rows) => rows.every(
    (row) => columns.every((column) => columnValidators(column).every((validate) => !validate(row[column.name] ?? ''))),
);

const RowListEditor = (/** @type Properties */ props) => {
    loadStylesheet('row-list-editor', stylesheet);

    const byKey = new Map(props.rows.map((row) => [row.key, { ...row }]));
    const keys = van.state(props.rows.map((row) => row.key));
    const emit = () => props.onChange(keys.rawVal.map((key) => ({ ...byKey.get(key) })));

    const add = () => {
        const row = { key: getRandomId(), index: null };
        byKey.set(row.key, row);
        keys.val = [...keys.rawVal, row.key];
        emit();
    };
    const remove = (key) => {
        byKey.delete(key);
        keys.val = keys.rawVal.filter((existing) => existing !== key);
        emit();
    };

    const cell = (column, content) => div({ class: 'tg-row-list-editor--cell', style: `flex: ${column.flex ?? 1}` }, content);

    const RowFields = (/** @type Row */ row) => div(
        { class: 'flex-row fx-align-flex-start fx-gap-2', 'data-testid': 'row-list-editor-row' },
        props.columns.map((column) => {
            const onChange = (value) => {
                if ((value ?? '') !== (row[column.name] ?? '')) {
                    row[column.name] = value ?? '';
                    emit();
                }
            };
            if (column.type === 'select') {
                return cell(column, Select({
                    name: column.name,
                    value: row[column.name] || null,
                    options: column.options.map((option) => ({ label: option, value: option })),
                    allowNull: true,
                    filterable: true,
                    acceptNewOptions: true,
                    onChange,
                }));
            }
            return cell(column, (column.type === 'date' ? DateInput : Input)({
                name: column.name,
                value: row[column.name] ?? '',
                placeholder: column.placeholder,
                validators: columnValidators(column),
                onChange,
            }));
        }),
        Button({ type: 'icon', icon: 'delete', tooltip: 'Remove', tooltipPosition: 'left', onclick: () => remove(row.key) }),
    );

    return div(
        { class: 'flex-column fx-gap-2', 'data-testid': props.testId ?? 'row-list-editor' },
        () => keys.val.length
            ? div(
                { class: 'flex-column fx-gap-2' },
                div(
                    { class: 'flex-row fx-gap-2 text-caption tg-row-list-editor--header' },
                    props.columns.map((column) => cell(column, span(
                        column.label,
                        column.required ? span({ class: 'text-error' }, ' *') : '',
                    ))),
                ),
                keys.val.map((key) => RowFields(byKey.get(key))),
            )
            : span({ class: 'text-secondary' }, props.emptyText),
        div(Button({ type: 'stroked', icon: 'add', label: props.addLabel, width: 'auto', onclick: add })),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-row-list-editor--cell {
    min-width: 0;
}

.tg-row-list-editor--cell .tg-select--field {
    min-width: 0;
}

.tg-row-list-editor--cell .tg-select--field--content,
.tg-row-list-editor--cell .tg-select--field--content > input {
    min-width: 0;
}

.tg-row-list-editor--cell .tg-select--field--icon {
    flex-shrink: 0;
}

.tg-row-list-editor--header {
    padding-right: 48px;
}
`);

export { RowListEditor, rowsValid };
