/**
 * @typedef MergeField
 * @type {object}
 * @property {string} name
 * @property {string} label
 * @property {string} source - the value as displayed, formatted by the caller: `—` when empty, `[PII Redacted]` when withheld
 * @property {string} target - the value as displayed, formatted like source
 * @property {boolean?} withheld - greys the values out; the caller redacts them
 *
 * @typedef MergeTest
 * @type {object}
 * @property {string} key
 * @property {'add'|'update'|'remove'|'conflict'} action
 * @property {('changed_both'|'removed_in_source'|'removed_in_target')?} reason
 * @property {string} table
 * @property {string} column
 * @property {string} test_type
 * @property {MergeField[]} fields
 *
 * @typedef Properties
 * @type {object}
 * @property {string} sourceLabel
 * @property {string} targetLabel
 * @property {MergeTest[]} tests
 * @property {object} decisions - VanJS state owned by the caller: { [key]: { [field]: 'source'|'target' } }, or
 *     { [key]: 'source'|'target' } for a removal conflict
 * @property {((allDecided: boolean) => void)?} onDecidedChange - called on mount and whenever the result changes
 * @property {object?} pageIndex - VanJS state for the page shown, for a caller that keeps it across re-renders
 * @property {object?} conflictsOnly - VanJS state for the filter, for a caller that keeps it across re-renders
 * @property {number?} pageSize
 */
import van from '../van.min.js';
import { getRandomId, loadStylesheet } from '../utils.js';
import { Button } from './button.js';
import { Icon } from './icon.js';
import { Paginator } from './paginator.js';
import { RadioGroup } from './radio_group.js';
import { Toggle } from './toggle.js';

const { col, colgroup, div, input, label, span, table, thead, tbody, tr, th, td } = van.tags;

const ACTIONS = {
    conflict: { label: 'Conflict', icon: 'warning', color: 'text-warning', order: 0 },
    remove: { label: 'Remove', icon: 'remove_circle', color: 'text-error', order: 1 },
    update: { label: 'Update', icon: 'edit', color: 'text-purple', order: 2 },
    add: { label: 'Add', icon: 'add_circle', color: 'text-green', order: 3 },
};

const COLUMNS = ['Action', 'Table', 'Column', 'Test Type', 'Decision'];
const COLUMN_WIDTHS = ['110px', '18%', '18%', '22%', 'auto'];

const pluralize = (count, noun) => `${count} ${noun}${count === 1 ? '' : 's'}`;

const joinSerial = (items) => {
    if (items.length <= 2) {
        return items.join(' and ');
    }
    return `${items.slice(0, -1).join(', ')}, and ${items[items.length - 1]}`;
};

const summaryText = (tests, sourceLabel, targetLabel) => {
    const counts = { add: 0, update: 0, remove: 0 };
    tests.forEach((test) => test.action in counts && counts[test.action]++);
    const actions = [];
    if (counts.add) actions.push(`add ${pluralize(counts.add, 'test')}`);
    if (counts.update) actions.push(`update ${pluralize(counts.update, 'test')}`);
    if (counts.remove) actions.push(`remove ${pluralize(counts.remove, 'test')}`);
    const merging = `Merging ${sourceLabel} into ${targetLabel}`;
    return actions.length ? `${merging} will ${joinSerial(actions)}.` : `${merging}.`;
};

const REASONS = {
    changed_both: () => 'Changed in both versions.',
    removed_in_source: (props) => `Removed in ${props.sourceLabel}, changed in ${props.targetLabel}.`,
    removed_in_target: (props) => `Changed in ${props.sourceLabel}, removed in ${props.targetLabel}.`,
};

const isRemoval = (/** @type MergeTest */ test) => test.reason === 'removed_in_source' || test.reason === 'removed_in_target';

/**
 * The side every field of a conflict is decided on, 'combined' when its fields are split between sides, or null
 * while any field is undecided and the decided ones agree.
 */
const rowSide = (/** @type MergeTest */ test, decisions) => {
    const decision = decisions[test.key];
    if (isRemoval(test)) {
        return decision ?? null;
    }
    const sides = new Set(test.fields.map((field) => decision?.[field.name]));
    if (sides.has('source') && sides.has('target')) {
        return 'combined';
    }
    return sides.size === 1 && !sides.has(undefined) ? [...sides][0] : null;
};

const isDecided = (/** @type MergeTest */ test, decisions) => {
    const decision = decisions[test.key];
    if (isRemoval(test)) {
        return !!decision;
    }
    return test.fields.every((field) => decision?.[field.name]);
};

const conflictText = (conflicts, decisions) => {
    const open = conflicts.filter((test) => !isDecided(test, decisions)).length;
    if (!open) {
        return 'All conflicts have a decision.';
    }
    return open === 1 ? '1 conflict needs a decision.' : `${open} conflicts need a decision.`;
};

const decideRow = (/** @type MergeTest */ test, side, decisionsState) => {
    const value = isRemoval(test) ? side : Object.fromEntries(test.fields.map((field) => [field.name, side]));
    decisionsState.val = { ...decisionsState.val, [test.key]: value };
};

const decideAll = (conflicts, side, decisionsState) => {
    const decisions = { ...decisionsState.val };
    for (const test of conflicts) {
        decisions[test.key] = isRemoval(test) ? side : Object.fromEntries(test.fields.map((field) => [field.name, side]));
    }
    decisionsState.val = decisions;
};

const decideField = (/** @type MergeTest */ test, fieldName, side, decisionsState) => {
    const current = decisionsState.val[test.key] ?? {};
    decisionsState.val = { ...decisionsState.val, [test.key]: { ...current, [fieldName]: side } };
};

const MergePreview = (/** @type Properties */ props) => {
    loadStylesheet('merge-preview', stylesheet);
    const pageSize = props.pageSize ?? 10;
    const tests = [...props.tests].sort((a, b) => ACTIONS[a.action].order - ACTIONS[b.action].order);

    if (!tests.length) {
        props.onDecidedChange?.(true);
        return div(
            { class: 'flex-row fx-justify-center p-4 text-secondary', 'data-testid': 'merge-preview-empty' },
            'No changes to merge',
        );
    }

    const groupName = getRandomId();
    const conflicts = tests.filter((test) => test.action === 'conflict');
    const pageIndex = props.pageIndex ?? van.state(0);
    const conflictsOnly = props.conflictsOnly ?? van.state(conflicts.length > 0);
    const shown = () => conflicts.length && conflictsOnly.val ? conflicts : tests;
    const shownCount = conflicts.length && conflictsOnly.rawVal ? conflicts.length : tests.length;
    if (pageIndex.rawVal * pageSize >= shownCount) {
        pageIndex.val = 0;
    }
    const hasFieldConflicts = conflicts.some((test) => !isRemoval(test));

    let reported = null;
    van.derive(() => {
        const decisions = props.decisions.val;
        const decided = conflicts.every((test) => isDecided(test, decisions));
        if (decided !== reported) {
            reported = decided;
            props.onDecidedChange?.(decided);
        }
    });

    return div(
        { class: 'flex-column fx-gap-3', 'data-testid': 'merge-preview' },
        div(
            { class: 'flex-column fx-gap-1' },
            div(
                { class: 'text-bold', 'data-testid': 'merge-preview-summary' },
                summaryText(tests, props.sourceLabel, props.targetLabel),
            ),
            conflicts.length
                ? div(
                    { class: 'flex-row fx-gap-4 fx-align-flex-center fx-flex-wrap' },
                    div(
                        { class: 'fx-flex', 'data-testid': 'merge-preview-conflicts' },
                        () => conflictText(conflicts, props.decisions.val),
                    ),
                    Toggle({
                        name: 'merge-preview-conflicts-only',
                        label: 'Show conflicts only',
                        checked: conflictsOnly,
                        onChange: (value) => {
                            conflictsOnly.val = value;
                            pageIndex.val = 0;
                        },
                    }),
                    div(
                        { class: 'flex-row fx-gap-2 fx-align-flex-center', 'data-testid': 'merge-preview-resolve-all' },
                        span('Resolve all:'),
                        Button({
                            type: 'stroked',
                            label: `Use ${props.sourceLabel}`,
                            width: 'auto',
                            onclick: () => decideAll(conflicts, 'source', props.decisions),
                        }),
                        Button({
                            type: 'stroked',
                            label: `Use ${props.targetLabel}`,
                            width: 'auto',
                            onclick: () => decideAll(conflicts, 'target', props.decisions),
                        }),
                    ),
                )
                : '',
            hasFieldConflicts
                ? div(
                    { class: 'text-secondary text-small', 'data-testid': 'merge-preview-help' },
                    `To use a value neither version holds, edit the test in ${props.sourceLabel} and preview the merge again.`,
                )
                : '',
        ),
        div(
            { class: 'tg-merge-preview border border-radius-1' },
            div(
                { class: 'tg-merge-preview--scrollable' },
                table(
                    colgroup(COLUMN_WIDTHS.map((width) => col({ style: `width: ${width}` }))),
                    thead(tr(COLUMNS.map((label) => th({ class: 'text-caption' }, label)))),
                    () => {
                        const start = pageIndex.val * pageSize;
                        return tbody(
                            shown().slice(start, start + pageSize).flatMap((test) => TestRows(test, props, groupName)),
                        );
                    },
                ),
            ),
            () => shown().length > pageSize
                ? div(
                    { class: 'tg-merge-preview--paginator' },
                    Paginator({
                        count: shown().length,
                        pageSize,
                        pageIndex,
                        onChange: (index) => pageIndex.val = index,
                    }),
                )
                : '',
        ),
    );
};

const TestRows = (/** @type MergeTest */ test, /** @type Properties */ props, groupName) => {
    const action = ACTIONS[test.action];
    const rows = [
        tr(
            { class: `tg-merge-preview--row tg-merge-preview--${test.action}`, 'data-testid': 'merge-preview-row' },
            td(
                div(
                    { class: 'flex-row fx-gap-1' },
                    Icon({ size: 18, classes: action.color }, action.icon),
                    span(action.label),
                ),
            ),
            td(test.table),
            td(test.column),
            td(test.test_type),
            td(test.action === 'conflict' ? RowDecision(test, props) : ''),
        ),
    ];
    if (test.action === 'conflict') {
        rows.push(tr(
            { class: 'tg-merge-preview--detail tg-merge-preview--conflict' },
            td(
                { colspan: COLUMNS.length },
                div(
                    { class: 'flex-column fx-gap-1' },
                    span({ class: 'text-secondary', 'data-testid': 'merge-preview-reason' }, REASONS[test.reason]?.(props) ?? ''),
                    isRemoval(test) ? '' : FieldComparison(test, props, groupName),
                ),
            ),
        ));
    } else if (test.action === 'update' && test.fields.length) {
        rows.push(tr(
            { class: 'tg-merge-preview--detail' },
            td({ colspan: COLUMNS.length }, FieldComparison(test, props, null)),
        ));
    }
    return rows;
};

const RowDecision = (/** @type MergeTest */ test, /** @type Properties */ props) => div(
    { class: 'flex-row fx-gap-2', 'data-testid': 'merge-preview-decision' },
    RadioGroup({
        layout: 'inline',
        options: [
            { label: `Use ${props.sourceLabel}`, value: 'source' },
            { label: `Use ${props.targetLabel}`, value: 'target' },
        ],
        value: () => rowSide(test, props.decisions.val),
        onChange: (side) => decideRow(test, side, props.decisions),
    }),
    () => rowSide(test, props.decisions.val) === 'combined'
        ? span({ class: 'text-secondary', 'data-testid': 'merge-preview-combined' }, 'Combined')
        : '',
);

const FieldComparison = (/** @type MergeTest */ test, /** @type Properties */ props, groupName) => div(
    { class: 'tg-merge-preview--fields', 'data-testid': 'merge-preview-fields' },
    span({ class: 'text-caption' }, 'Field'),
    span({ class: 'text-caption' }, props.sourceLabel),
    span({ class: 'text-caption' }, props.targetLabel),
    ...test.fields.flatMap((field) => [
        span({ class: 'text-secondary' }, field.label),
        groupName ? FieldChoice(test, field, 'source', props, groupName) : FieldValue(field, field.source),
        groupName ? FieldChoice(test, field, 'target', props, groupName) : FieldValue(field, field.target),
    ]),
);

const FieldChoice = (/** @type MergeTest */ test, /** @type MergeField */ field, side, /** @type Properties */ props, groupName) => label(
    { class: 'flex-row fx-gap-2 clickable', 'data-testid': 'merge-preview-field-choice' },
    input({
        type: 'radio',
        class: 'tg-radio-group--input',
        name: `${groupName}:${JSON.stringify([test.key, field.name])}`,
        checked: () => props.decisions.val[test.key]?.[field.name] === side,
        onchange: () => decideField(test, field.name, side, props.decisions),
    }),
    FieldValue(field, field[side]),
);

const FieldValue = (/** @type MergeField */ field, value) => span(
    { class: field.withheld ? 'text-secondary' : '' },
    value,
);

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-merge-preview {
    background: var(--dk-card-background);
}

.tg-merge-preview--scrollable {
    overflow: auto;
    max-height: 480px;
}

.tg-merge-preview table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
}

.tg-merge-preview thead {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--table-header-background, var(--dk-card-background));
    border-bottom: var(--button-stroked-border);
}

.tg-merge-preview th {
    font-weight: normal;
    text-align: left;
    text-transform: uppercase;
    padding: 0 8px;
    height: 27px;
}

.tg-merge-preview td {
    padding: 0 8px;
    height: 27px;
    overflow-wrap: anywhere;
}

.tg-merge-preview--row:not(:first-child) {
    border-top: var(--button-stroked-border);
}

.tg-merge-preview--conflict > td {
    background-color: color-mix(in srgb, var(--orange) 6%, transparent);
}

.tg-merge-preview--row.tg-merge-preview--conflict > td {
    height: 36px;
}

.tg-merge-preview--detail > td {
    padding: 0 8px 8px 34px;
}

.tg-merge-preview--fields {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr) minmax(0, 1fr);
    align-items: center;
    column-gap: 24px;
    row-gap: 4px;
    max-width: 960px;
    word-break: break-word;
}

.tg-merge-preview--paginator {
    border-top: var(--button-stroked-border);
}
`);

export { MergePreview };
