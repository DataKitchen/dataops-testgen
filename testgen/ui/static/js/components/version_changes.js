/**
 * @typedef FieldChange
 * @type {object}
 * @property {string} label
 * @property {string} before
 * @property {string} after
 *
 * @typedef RuleRow
 * @type {object}
 * @property {string} change
 * @property {string} table
 * @property {string} column
 * @property {string} test_type
 * @property {FieldChange[]} fields
 *
 * @typedef RuleChanges
 * @type {object}
 * @property {string?} summary
 * @property {RuleRow[]} rows
 * @property {number} total_rows
 * @property {boolean} truncated
 * @property {string?} empty_state
 *
 * @typedef MetadataRow
 * @type {object}
 * @property {string} section
 * @property {string} field
 * @property {string} before
 * @property {string} after
 *
 * @typedef MetadataChanges
 * @type {object}
 * @property {string?} summary
 * @property {MetadataRow[]} rows
 * @property {string?} empty_state
 *
 * @typedef Changes
 * @type {object}
 * @property {number} source
 * @property {number} target
 * @property {string?} error
 * @property {RuleChanges?} rules
 * @property {MetadataChanges?} metadata
 *
 * @typedef Properties
 * @type {object}
 * @property {Changes} changes
 * @property {string} sourceLabel
 * @property {string} targetLabel
 */
import van from '../van.min.js';
import { loadStylesheet } from '../utils.js';
import { Alert } from './alert.js';
import { Icon } from './icon.js';
import { Table } from './table.js';

const { div, span } = van.tags;

const CHANGE_ICONS = {
    Added: ['add_circle', 'text-green'],
    Removed: ['remove_circle', 'text-error'],
};
const EDIT_ICON = ['edit', 'text-purple'];

const VersionChanges = (/** @type Properties */ props) => {
    loadStylesheet('version-changes', stylesheet);
    const { changes } = props;
    if (changes.error) {
        return Alert({ type: 'error', icon: 'error' }, span(changes.error));
    }
    return div(
        { class: 'flex-column fx-gap-4', 'data-testid': 'version-changes' },
        Section('Quality Rules', changes.rules, RuleTable(changes.rules)),
        Section('Contract Metadata', changes.metadata, MetadataTable(changes.metadata, props)),
    );
};

const Section = (title, half, content) => div(
    { class: 'flex-column fx-gap-2' },
    div(
        { class: 'flex-row fx-gap-3 fx-align-flex-end' },
        span({ class: 'title m' }, title),
        half.summary ? span({ class: 'text-secondary' }, half.summary) : '',
    ),
    half.empty_state ? span({ class: 'text-secondary', 'data-testid': 'version-changes-empty' }, half.empty_state) : content,
);

const RuleTable = (/** @type RuleChanges */ rules) => {
    if (!rules.rows.length) {
        return '';
    }
    const columns = [
        { name: '_change', label: 'Change', width: 190, overflow: 'visible', align: 'left' },
        { name: 'table', label: 'Table', width: 150, align: 'left' },
        { name: 'column', label: 'Column', width: 150, align: 'left' },
        { name: 'test_type', label: 'Test Type', width: 160, align: 'left' },
        { name: '_fields', label: 'Changed Fields', width: 340, overflow: 'visible', align: 'left' },
    ];
    const rows = rules.rows.map((row) => {
        const [icon, color] = CHANGE_ICONS[row.change] ?? EDIT_ICON;
        return {
            ...row,
            _change: div(
                { class: 'flex-row fx-gap-1' },
                Icon({ size: 18, classes: color }, icon),
                span(row.change),
            ),
            _fields: div(
                { class: 'flex-column fx-gap-1 tg-version-changes--fields' },
                ...row.fields.map((field) => div(
                    span({ class: 'text-secondary' }, `${field.label}  `),
                    span(field.before),
                    span({ class: 'text-secondary' }, '  →  '),
                    span(field.after),
                )),
            ),
        };
    });
    return div(
        { class: 'flex-column fx-gap-2' },
        Table({ columns, height: 'auto', maxHeight: '320px', highDensity: true }, rows),
        rules.truncated
            ? Alert({ type: 'info', icon: 'info' }, `Showing the first ${rules.rows.length} of ${rules.total_rows} changes.`)
            : '',
    );
};

const MetadataTable = (/** @type MetadataChanges */ metadata, /** @type Properties */ props) => {
    if (!metadata.rows.length) {
        return '';
    }
    const columns = [
        { name: 'section', label: 'Section', width: 140, align: 'left' },
        { name: 'field', label: 'Field', width: 360, align: 'left' },
        { name: 'before', label: props.sourceLabel, width: 230, align: 'left' },
        { name: 'after', label: props.targetLabel, width: 230, align: 'left' },
    ];
    return Table({ columns, height: 'auto', maxHeight: '320px', highDensity: true }, metadata.rows);
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-version-changes--fields {
    white-space: pre-wrap;
    word-break: break-word;
}
`);

export { VersionChanges };
