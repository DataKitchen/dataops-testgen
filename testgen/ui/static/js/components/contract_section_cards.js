/**
 * @typedef SectionResult
 * @type {object}
 * @property {string} token - a new value for each save attempt
 * @property {string} section
 * @property {boolean} success
 * @property {string?} message
 * @property {string[]?} problems
 *
 * @typedef Overview
 * @type {object}
 * @property {string} name
 * @property {string} status
 * @property {string?} domain
 * @property {string?} tenant
 * @property {string[]} tags
 * @property {string?} purpose
 * @property {string?} usage
 * @property {string?} limitations
 *
 * @typedef TeamMember
 * @type {object}
 * @property {number?} index
 * @property {string} username
 * @property {string?} name
 * @property {string?} role
 * @property {string?} dateIn
 * @property {string?} dateOut
 *
 * @typedef Team
 * @type {object}
 * @property {string?} name
 * @property {string?} description
 * @property {boolean} deprecated_form
 * @property {TeamMember[]} members
 *
 * @typedef ListRow
 * @type {object}
 * @property {number?} index
 *
 * @typedef SectionCardProperties
 * @type {object}
 * @property {function(): object} value - the section as the version stores it
 * @property {function(): object} current - the same, read without subscribing to it
 * @property {function(): boolean} editable
 * @property {object} editing - VanJS state holding whether the card's form is open
 * @property {function(): SectionResult?} refusal - the refused save to show in the form, if any
 * @property {function(): void} onDismiss - called when the form changes after a refusal, or is canceled
 * @property {function(object): void} onSave
 */
import van from '../van.min.js';
import { getRandomId, isEqual, loadStylesheet } from '../utils.js';
import { Alert } from './alert.js';
import { Attribute } from './attribute.js';
import { EditableCard } from './editable_card.js';
import { Input } from './input.js';
import { RowListEditor, rowsValid } from './row_list_editor.js';
import { Table } from './table.js';
import { Textarea } from './textarea.js';

const { div, li, span, ul } = van.tags;

const RefusalAlert = (/** @type {{message: string, problems: string[]?}?} */ result) => result
    ? Alert(
        { type: 'error', icon: 'error' },
        div(
            { class: 'flex-column' },
            span(result.message),
            result.problems?.length
                ? ul({ class: 'mt-1 mb-0 pl-4' }, result.problems.map((problem) => li(problem)))
                : null,
        ),
    )
    : '';

const OVERVIEW_TEXT_FIELDS = ['domain', 'tenant', 'purpose', 'usage', 'limitations'];

const overviewForm = (/** @type Overview */ overview) => ({
    ...Object.fromEntries(OVERVIEW_TEXT_FIELDS.map((field) => [field, overview[field] ?? ''])),
    tags: (overview.tags ?? []).join(', '),
});

const formTags = (text) => text.split(',').map((tag) => tag.trim()).filter(Boolean);

const OverviewCard = (/** @type SectionCardProperties */ props) => {
    loadStylesheet('contract-section-cards', stylesheet);
    const form = van.state(overviewForm({}));
    van.derive(() => {
        if (props.editing.val) {
            form.val = overviewForm(props.current() ?? {});
        }
    });
    const update = (field, value) => {
        if (value !== form.rawVal[field]) {
            form.val = { ...form.rawVal, [field]: value };
            props.onDismiss();
        }
    };

    const field = (name, label, Component = Input, extra = {}) => Component({
        name: `overview-${name}`,
        label,
        value: form.rawVal[name],
        onChange: (value) => update(name, value),
        ...extra,
    });

    return EditableCard({
        title: 'Overview',
        testId: 'contract-overview',
        editable: props.editable,
        editing: props.editing,
        content: () => OverviewContent(props.value() ?? {}),
        editingContent: () => {
            const overview = props.value() ?? {};
            return div(
                { class: 'flex-column fx-gap-3' },
                div(
                    { class: 'flex-row fx-gap-5' },
                    Attribute({ label: 'Name', value: overview.name, width: 240 }),
                    Attribute({ label: 'Status', value: overview.status, width: 240 }),
                ),
                div(
                    { class: 'flex-row fx-gap-3' },
                    div({ class: 'fx-flex' }, field('domain', 'Domain')),
                    div({ class: 'fx-flex' }, field('tenant', 'Tenant')),
                ),
                field('tags', 'Tags', Input, { help: 'Separate tags with commas.' }),
                field('purpose', 'Purpose', Textarea, { height: 72 }),
                field('usage', 'Usage', Textarea, { height: 72 }),
                field('limitations', 'Limitations', Textarea, { height: 72 }),
                () => RefusalAlert(props.refusal()),
            );
        },
        hasChanges: () => !isEqual(
            { ...form.val, tags: formTags(form.val.tags) },
            { ...overviewForm(props.value() ?? {}), tags: props.value()?.tags ?? [] },
        ),
        onCancel: props.onDismiss,
        onSave: () => props.onSave({ ...form.rawVal, tags: formTags(form.rawVal.tags) }),
    });
};

const OverviewContent = (/** @type Overview */ overview) => div(
    { class: 'flex-column fx-gap-4 contract-section-multiline' },
    div(
        { class: 'flex-row fx-flex-wrap fx-gap-5' },
        Attribute({ label: 'Name', value: overview.name, width: 240 }),
        Attribute({ label: 'Status', value: overview.status, width: 160 }),
        Attribute({ label: 'Domain', value: overview.domain, width: 200 }),
        Attribute({ label: 'Tenant', value: overview.tenant, width: 200 }),
    ),
    overview.tags?.length ? Attribute({ label: 'Tags', value: overview.tags.join(' · ') }) : '',
    overview.purpose ? Attribute({ label: 'Purpose', value: overview.purpose }) : '',
    overview.usage ? Attribute({ label: 'Usage', value: overview.usage }) : '',
    overview.limitations ? Attribute({ label: 'Limitations', value: overview.limitations }) : '',
);

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const date = (value) => value && !DATE_PATTERN.test(value.trim()) ? 'Use the format YYYY-MM-DD.' : null;

const MEMBER_COLUMNS = [
    { name: 'username', label: 'Username', required: true, flex: 3 },
    { name: 'name', label: 'Name', flex: 3 },
    { name: 'role', label: 'Role', flex: 2 },
    { name: 'dateIn', label: 'Date Joined', flex: 2, type: 'date', validators: [date] },
    { name: 'dateOut', label: 'Date Left', flex: 2, type: 'date', validators: [date] },
];

/** Rows as the form compares them: every column's text trimmed, empty as '', and no editor key. */
const comparableRows = (columns, rows) => rows.map((row) => ({
    index: row.index ?? null,
    ...Object.fromEntries(columns.map((column) => [column.name, (row[column.name] ?? '').trim()])),
}));

const teamForm = (/** @type Team */ team) => ({
    name: team.name ?? '',
    description: team.description ?? '',
    members: (team.members ?? []).map((member) => ({ ...member, key: getRandomId() })),
});

const comparableTeam = (form) => ({
    name: form.name.trim(),
    description: form.description.trim(),
    members: comparableRows(MEMBER_COLUMNS, form.members),
});

const TeamCard = (/** @type SectionCardProperties */ props) => {
    loadStylesheet('contract-section-cards', stylesheet);
    const form = van.state(teamForm({}));
    van.derive(() => {
        if (props.editing.val) {
            form.val = teamForm(props.current() ?? {});
        }
    });
    const update = (changes) => {
        form.val = { ...form.rawVal, ...changes };
        props.onDismiss();
    };
    const text = (name, label, Component = Input, extra = {}) => Component({
        name: `team-${name}`,
        label,
        value: form.rawVal[name],
        onChange: (value) => value !== form.rawVal[name] && update({ [name]: value }),
        ...extra,
    });

    return EditableCard({
        title: 'Team',
        testId: 'contract-team',
        editable: props.editable,
        editing: props.editing,
        content: () => TeamContent(props.value() ?? {}),
        editingContent: () => div(
            { class: 'flex-column fx-gap-3' },
            text('name', 'Name'),
            text('description', 'Description', Textarea, { height: 72 }),
            div(
                { class: 'flex-column fx-gap-2' },
                span({ class: 'text-caption' }, 'Members'),
                RowListEditor({
                    columns: MEMBER_COLUMNS,
                    rows: form.rawVal.members,
                    onChange: (members) => update({ members }),
                    addLabel: 'Add Member',
                    emptyText: 'The contract lists no team members.',
                    testId: 'contract-team-members',
                }),
            ),
            () => RefusalAlert(props.refusal()),
        ),
        hasChanges: () => rowsValid(MEMBER_COLUMNS, form.val.members)
            && !isEqual(comparableTeam(form.val), comparableTeam(teamForm(props.value() ?? {}))),
        onCancel: props.onDismiss,
        onSave: () => props.onSave({
            name: form.rawVal.name,
            description: form.rawVal.description,
            members: form.rawVal.members.map(({ key, ...member }) => member),
        }),
    });
};

const TeamContent = (/** @type Team */ team) => {
    const members = team.members ?? [];
    if (!team.name && !team.description && !members.length) {
        return span({ class: 'text-secondary' }, 'The contract names no team.');
    }
    return div(
        { class: 'flex-column fx-gap-4 contract-section-multiline' },
        div(
            { class: 'flex-row fx-flex-wrap fx-gap-5' },
            Attribute({ label: 'Name', value: team.name, width: 240 }),
            Attribute({ label: 'Description', value: team.description }),
        ),
        members.length
            ? Table(
                {
                    columns: MEMBER_COLUMNS.map((column) => ({ name: column.name, label: column.label, width: 200, align: 'left' })),
                    height: 'auto',
                    maxHeight: '320px',
                    highDensity: true,
                },
                members.map((member) => Object.fromEntries(
                    MEMBER_COLUMNS.map((column) => [column.name, member[column.name] ?? '—']),
                )),
            )
            : span({ class: 'text-secondary' }, 'The team lists no members.'),
    );
};

const ROLE_COLUMNS = [
    { name: 'role', label: 'Role', required: true, flex: 2 },
    { name: 'access', label: 'Access', flex: 1 },
    { name: 'description', label: 'Description', flex: 3 },
    { name: 'firstLevelApprovers', label: 'First-Level Approvers', flex: 2 },
    { name: 'secondLevelApprovers', label: 'Second-Level Approvers', flex: 2 },
];

const SUPPORT_COLUMNS = [
    { name: 'channel', label: 'Channel', required: true, flex: 2 },
    { name: 'tool', label: 'Tool', flex: 2, type: 'select',
      options: ['email', 'slack', 'teams', 'discord', 'ticket', 'googlechat', 'other'] },
    { name: 'scope', label: 'Scope', flex: 2, type: 'select',
      options: ['interactive', 'announcements', 'issues', 'notifications'] },
    { name: 'url', label: 'URL', flex: 3 },
    { name: 'description', label: 'Description', flex: 3 },
];

const SERVICE_LEVEL_COLUMNS = [
    { name: 'property', label: 'Property', required: true, flex: 2 },
    { name: 'value', label: 'Value', required: true, flex: 1 },
    { name: 'unit', label: 'Unit', flex: 1 },
    { name: 'element', label: 'Element', flex: 2 },
    { name: 'driver', label: 'Driver', flex: 2, type: 'select', options: ['regulatory', 'analytics', 'operational'] },
    { name: 'description', label: 'Description', flex: 3 },
];

/**
 * A card over one list section: a table of its rows, and a row editor as its form.
 *
 * @param {{title: string, testId: string, columns: object[], addLabel: string, emptyText: string,
 *     info: (function(): string)?}} section
 */
const ListSectionCard = (section) => (/** @type SectionCardProperties */ props) => {
    const rows = van.state([]);
    van.derive(() => {
        if (props.editing.val) {
            rows.val = (props.current() ?? []).map((row) => ({ ...row, key: getRandomId() }));
        }
    });
    const info = () => section.info?.() ? Alert({ type: 'info', icon: 'info' }, span(section.info())) : '';

    return EditableCard({
        title: section.title,
        testId: section.testId,
        editable: props.editable,
        editing: props.editing,
        content: () => {
            const stored = props.value() ?? [];
            return div(
                { class: 'flex-column fx-gap-3' },
                info(),
                stored.length
                    ? Table(
                        {
                            columns: section.columns.map((column) => ({
                                name: column.name, label: column.label, width: 120 * (column.flex ?? 1), align: 'left',
                            })),
                            height: 'auto',
                            maxHeight: '320px',
                            highDensity: true,
                        },
                        stored.map((row) => Object.fromEntries(section.columns.map((column) => [column.name, row[column.name] ?? '—']))),
                    )
                    : span({ class: 'text-secondary' }, section.emptyText),
            );
        },
        editingContent: () => div(
            { class: 'flex-column fx-gap-3' },
            info(),
            RowListEditor({
                columns: section.columns,
                rows: rows.rawVal,
                onChange: (changed) => {
                    rows.val = changed;
                    props.onDismiss();
                },
                addLabel: section.addLabel,
                emptyText: section.emptyText,
                testId: `${section.testId}-rows`,
            }),
            () => RefusalAlert(props.refusal()),
        ),
        hasChanges: () => rowsValid(section.columns, rows.val)
            && !isEqual(comparableRows(section.columns, rows.val), comparableRows(section.columns, props.value() ?? [])),
        onCancel: props.onDismiss,
        onSave: () => props.onSave({ rows: rows.rawVal.map(({ key, ...row }) => row) }),
    });
};

const RolesCard = ListSectionCard({
    title: 'Roles', testId: 'contract-roles', columns: ROLE_COLUMNS, addLabel: 'Add Role',
    emptyText: 'The contract declares no roles.',
});

const SupportCard = ListSectionCard({
    title: 'Support', testId: 'contract-support', columns: SUPPORT_COLUMNS, addLabel: 'Add Channel',
    emptyText: 'The contract lists no support channels.',
});

const serviceLevelsCard = (info) => ListSectionCard({
    title: 'Service Levels', testId: 'contract-service-levels', columns: SERVICE_LEVEL_COLUMNS,
    addLabel: 'Add Service Level', emptyText: 'The contract declares no service levels.', info,
});

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.contract-section-multiline .attribute-value {
    white-space: pre-wrap;
}
`);

export { OverviewCard, RefusalAlert, RolesCard, serviceLevelsCard, SupportCard, TeamCard };
