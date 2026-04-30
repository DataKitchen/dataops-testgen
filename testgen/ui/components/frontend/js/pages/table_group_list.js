/**
 * @import { ProjectSummary } from '../types.js';
 * @import { TableGroup } from '/app/static/js/components/table_group_form.js';
 * @import { Connection } from '/app/static/js/components/connection_form.js';
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {string?} connection_id
 * @property {string?} table_group_name
 * @property {Connection[]} connections
 * @property {TableGroup[]} table_groups
 * @property {Permissions} permissions
 * @property {object?} run_profiling_dialog
 * @property {object?} schedule_dialog
 * @property {object?} notifications_dialog
 */
import van from '/app/static/js/van.min.js';
import { Button } from '/app/static/js/components/button.js';
import { Card } from '/app/static/js/components/card.js';
import { Caption } from '/app/static/js/components/caption.js';
import { Link } from '/app/static/js/components/link.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '/app/static/js/components/empty_state.js';
import { Select } from '/app/static/js/components/select.js';
import { Icon } from '/app/static/js/components/icon.js';
import { Input } from '/app/static/js/components/input.js';
import { TruncatedText } from '/app/static/js/components/truncated_text.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Toggle } from '/app/static/js/components/toggle.js';
import { Attribute } from '/app/static/js/components/attribute.js';
import { RunProfilingDialog } from '/app/static/js/components/run_profiling_dialog.js';
import { ScheduleList } from '/app/static/js/components/schedule_list.js';
import { NotificationSettings } from '/app/static/js/components/notification_settings.js';
import { TableGroupWizard } from '/app/static/js/components/table_group_wizard.js';
import { TableGroupEditDialog } from '/app/static/js/components/table_group_edit_dialog.js';

const { div, h4, span, b } = van.tags;

/**
 * @param {Properties} props
 * @returns {HTMLElement}
 */
const TableGroupList = (props) => {
    const { emit } = props;
    loadStylesheet('tablegrouplist', stylesheet);

    const wrapperId = 'tablegroup-list-wrapper';

    const confirmDeleteRelated = van.state(false);
    const deleteDialogInfo = van.derive(() => getValue(props.delete_dialog) ?? null);
    const deleteDialogOpen = van.state(false);
    van.derive(() => { if (deleteDialogInfo.val?.open) deleteDialogOpen.val = true; });
    const closeDeleteDialog = () => {
        deleteDialogOpen.val = false;
        confirmDeleteRelated.val = false;
        emit('DeleteDialogDismissed', {});
    };

    const scheduleDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.schedule_dialog)?.open === true) scheduleDialogOpen.val = true; });
    const notificationsDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.notifications_dialog)?.open === true) notificationsDialogOpen.val = true; });

    // Wizard: create once per wizard session (keyed by steps+id), then keep alive
    // so internal state (currentStepIndex, form values, expansion panels) survives reruns.
    const wizardContainer = div({ style: 'display: contents' });
    let wizardKey = null;
    van.derive(() => {
        const wizardData = getValue(props.wizard);
        if (!wizardData) {
            if (wizardKey !== null) {
                wizardContainer.innerHTML = '';
                wizardKey = null;
            }
            return;
        }
        const key = wizardData.steps?.join(',') ?? 'default';
        if (key !== wizardKey) {
            wizardContainer.innerHTML = '';
            wizardKey = key;
            van.add(wizardContainer, TableGroupWizard({ emit, 
                project_code: van.derive(() => getValue(props.wizard)?.project_code),
                connections: van.derive(() => getValue(props.wizard)?.connections),
                table_group: van.derive(() => getValue(props.wizard)?.table_group),
                is_in_use: van.derive(() => getValue(props.wizard)?.is_in_use),
                table_group_preview: van.derive(() => getValue(props.wizard)?.table_group_preview),
                steps: van.derive(() => getValue(props.wizard)?.steps),
                dialog: van.derive(() => getValue(props.wizard)?.dialog),
                results: van.derive(() => getValue(props.wizard)?.results),
                standard_cron_sample: van.derive(() => getValue(props.wizard)?.standard_cron_sample),
                monitor_cron_sample: van.derive(() => getValue(props.wizard)?.monitor_cron_sample),
            }));
        }
    });

    // Edit dialog: same stable container pattern
    const editDialogContainer = div({ style: 'display: contents' });
    let editDialogKey = null;
    van.derive(() => {
        const editData = getValue(props.edit_dialog);
        if (!editData) {
            if (editDialogKey !== null) {
                editDialogContainer.innerHTML = '';
                editDialogKey = null;
            }
            return;
        }
        const key = editData.table_group?.id || 'none';
        if (key !== editDialogKey) {
            editDialogContainer.innerHTML = '';
            editDialogKey = key;
            van.add(editDialogContainer, TableGroupEditDialog({ emit, 
                dialog: van.derive(() => getValue(props.edit_dialog)?.dialog),
                connections: van.derive(() => getValue(props.edit_dialog)?.connections),
                table_group: van.derive(() => getValue(props.edit_dialog)?.table_group),
                is_in_use: van.derive(() => getValue(props.edit_dialog)?.is_in_use),
                table_group_preview: van.derive(() => getValue(props.edit_dialog)?.table_group_preview),
                result: van.derive(() => getValue(props.edit_dialog)?.result),
            }));
        }
    });

    // Toolbar must persist across reruns: filter inputs debounce on `oninput`,
    // and recreating the input element while a debounce timer is pending drops
    // the user's typed value (the timer commits to a discarded derive). We
    // mount it once into a stable container and tear down only when the page
    // transitions out of the populated state.
    const toolbarContainer = div({ style: 'display: contents' });
    let toolbarMounted = false;
    van.derive(() => {
        const connections = getValue(props.connections) ?? [];
        const projectSummary = getValue(props.project_summary);
        const shouldShow = connections.length > 0 && (projectSummary?.table_group_count ?? 0) > 0;
        if (shouldShow && !toolbarMounted) {
            van.add(toolbarContainer, Toolbar(
                getValue(props.permissions) ?? {can_edit: false},
                props.connections,
                getValue(props.connection_id),
                getValue(props.table_group_name),
                emit,
            ));
            toolbarMounted = true;
        } else if (!shouldShow && toolbarMounted) {
            toolbarContainer.innerHTML = '';
            toolbarMounted = false;
        }
    });

    return div(
        { id: wrapperId, 'data-testid': 'table-group-list', class: 'tg-tablegroups' },
        () => {
            const permissions = getValue(props.permissions) ?? {can_edit: false};
            const connections = getValue(props.connections) ?? [];
            const projectSummary = getValue(props.project_summary);

            if (connections.length <= 0) {
                return EmptyState({ emit,
                    icon: 'table_view',
                    label: 'Your project is empty',
                    message: EMPTY_STATE_MESSAGE.connection,
                    link: {
                        label: 'Go to Connections',
                        href: 'connections',
                        params: { project_code: projectSummary.project_code },
                        disabled: !permissions.can_edit,
                    },
                });
            }

            if ((projectSummary?.table_group_count ?? 0) <= 0) {
                return EmptyState({ emit,
                    icon: 'table_view',
                    label: 'No table groups yet',
                    class: 'mt-4',
                    message: EMPTY_STATE_MESSAGE.tableGroup,
                    button: Button({
                        type: 'stroked',
                        icon: 'add',
                        label: 'Add Table Group',
                        color: 'primary',
                        style: 'width: unset;',
                        disabled: !permissions.can_edit,
                        onclick: () => emit('AddTableGroupClicked', {}),
                    }),
                });
            }

            return '';
        },
        toolbarContainer,
        () => {
            const connections = getValue(props.connections) ?? [];
            const projectSummary = getValue(props.project_summary);
            if (connections.length <= 0 || (projectSummary?.table_group_count ?? 0) <= 0) {
                return '';
            }

            const permissions = getValue(props.permissions) ?? {can_edit: false};
            const tableGroups = getValue(props.table_groups) ?? [];

            return tableGroups.length
                ? div(
                    { class: 'flex-column fx-gap-4' },
                    ...tableGroups.map((tableGroup) => Card({
                        testId: 'table-group-card',
                        class: '',
                        title: div(
                            { class: 'flex-column fx-gap-2 tg-tablegroup--card-title', 'data-testid': 'tablegroup-card-title' },
                            h4({'data-testid': 'tablegroup-card-title-name'}, tableGroup.table_groups_name),
                            div(
                                {class: 'flex-row fx-gap-1 fx-align-center'},
                                Icon({ size: 14 }, tableGroup.connection.flavor.icon),
                                Caption({ content: tableGroup.connection.name }),
                            ),
                        ),
                        border: true,
                        content: div(
                            { class: 'flex-column fx-gap-3' },
                            div(
                                { class: 'flex-row fx-gap-3' },
                                div(
                                    { class: 'flex-column fx-flex fx-gap-3' },
                                    Link({ emit, 
                                        label: 'View test suites',
                                        href: 'test-suites',
                                        params: { 'project_code': projectSummary.project_code, 'table_group_id': tableGroup.id },
                                        right_icon: 'chevron_right',
                                        right_icon_size: 20,
                                    }),
                                    div(
                                        { class: 'flex-row fx-flex fx-gap-3' },
                                        div(
                                            { class: 'flex-column fx-flex fx-gap-4' },
                                            div(
                                                { class: 'flex-column fx-flex' },
                                                Caption({content: 'DB Schema', style: 'margin-bottom: 4px;'}),
                                                span(tableGroup.table_group_schema || '--'),
                                            ),
                                            div(
                                                { class: 'flex-column fx-flex' },
                                                Caption({content: 'Explicit Table List', style: 'margin-bottom: 4px;'}),
                                                tableGroup.profiling_table_set
                                                    ? TruncatedText(
                                                        {max: 3, tooltipPosition: 'top-right'},
                                                        ...tableGroup.profiling_table_set.split(',').map(t => t.trim())
                                                    )
                                                    : '--',
                                            ),
                                        ),
                                        div(
                                            { class: 'flex-column fx-flex fx-gap-4' },
                                            div(
                                                { class: 'flex-column fx-flex' },
                                                Caption({content: 'Tables to Include Mask', style: 'margin-bottom: 4px;'}),
                                                span(tableGroup.profiling_include_mask || '--'),
                                            ),
                                            div(
                                                { class: 'flex-column fx-flex' },
                                                Caption({content: 'Uses Record Sampling', style: 'margin-bottom: 4px;'}),
                                                span(tableGroup.profile_use_sampling ? 'Yes' : 'No'),
                                            ),
                                        ),
                                        div(
                                            { class: 'flex-column fx-flex fx-gap-4' },
                                            div(
                                                { class: 'flex-column fx-flex' },
                                                Caption({content: 'Tables to Exclude Mask', style: 'margin-bottom: 4px;'}),
                                                span(tableGroup.profiling_exclude_mask || '--'),
                                            ),
                                            div(
                                                { class: 'flex-column fx-flex' },
                                                Caption({content: 'Min Profiling Age (Days)', style: 'margin-bottom: 4px;'}),
                                                span(tableGroup.profiling_delay_days || '--'),
                                            ),
                                        ),
                                        span({ class: 'fx-flex' }),
                                    ),
                                ),
                                permissions.can_edit
                                    ? div(
                                        { class: 'flex-column' },
                                        Button({
                                            type: 'stroked',
                                            color: 'primary',
                                            label: 'Run Profiling',
                                            onclick: () => emit('RunProfilingClicked', { payload: tableGroup.id }),
                                        }),
                                    )
                                    : '',
                            )
                        ),
                        actionContent: permissions.can_edit
                            ? div(
                                { class: 'flex-row fx-align-center' },
                                Button({
                                    type: 'icon',
                                    icon: 'edit',
                                    iconSize: 18,
                                    tooltip: 'Edit table group',
                                    tooltipPosition: 'left',
                                    color: 'basic',
                                    onclick: () => emit('EditTableGroupClicked', { payload: tableGroup.id }),
                                }),
                                Button({
                                    type: 'icon',
                                    icon: 'delete',
                                    iconSize: 18,
                                    tooltip: 'Delete table group',
                                    tooltipPosition: 'left',
                                    color: 'basic',
                                    onclick: () => emit('DeleteTableGroupClicked', { payload: tableGroup.id }),
                                }),
                            )
                            : undefined,
                    })),
                )
                : div(
                    { class: 'mt-7 text-secondary', style: 'text-align: center;' },
                    'No table groups found matching filters',
                );
        },
        () => {
            const info = deleteDialogInfo.val;
            if (!info) return div();
            const tableGroup = info.table_group;
            const canBeDeleted = info.can_be_deleted;
            const deleteDisabled = van.derive(() => !canBeDeleted && !confirmDeleteRelated.val);
            return Dialog(
                {
                    title: 'Delete Table Group',
                    open: deleteDialogOpen,
                    onClose: closeDeleteDialog,
                    width: '36rem',
                },
                div(
                    { class: 'flex-column fx-gap-4' },
                    span('Are you sure you want to delete the table group ', b(tableGroup.table_groups_name), '?'),
                    Attribute({ label: 'ID', value: tableGroup.id }),
                    Attribute({ label: 'Name', value: tableGroup.table_groups_name }),
                    Attribute({ label: 'Schema', value: tableGroup.table_group_schema }),
                    !canBeDeleted
                        ? div(
                            { class: 'flex-column fx-gap-4 mt-4' },
                            Alert(
                                { type: 'warn' },
                                div('This Table Group has related data, which may include profiling, test definitions, test results, and monitor history.'),
                                div({ class: 'mt-2' }, 'If you proceed, all related data will be permanently deleted.'),
                            ),
                            Toggle({
                                name: 'confirm-delete-tablegroup',
                                label: span('Yes, delete the table group ', b(tableGroup.table_groups_name), ' and related TestGen data.'),
                                checked: confirmDeleteRelated,
                                onChange: (value) => confirmDeleteRelated.val = value,
                            }),
                        )
                        : '',
                    div(
                        { class: 'flex-row fx-justify-content-flex-end' },
                        () => Button({
                            type: deleteDisabled.val ? 'stroked' : 'flat',
                            color: deleteDisabled.val ? 'basic' : 'warn',
                            label: 'Delete',
                            width: 'auto',
                            style: 'margin-left: auto;',
                            disabled: deleteDisabled,
                            onclick: () => emit('DeleteTableGroupConfirmed', { payload: tableGroup.id }),
                        }),
                    ),
                ),
            );
        },
    () => {
        const info = getValue(props.run_profiling_dialog);
        if (!info) return div();
        return RunProfilingDialog({ emit,
            dialog: { title: info.title ?? 'Run Profiling', open: true },
            table_groups: info.table_groups ?? [],
            allow_selection: info.allow_selection ?? false,
            selected_id: info.selected_id,
            result: info.result,
            onClose: () => emit('RunProfilingDialogClosed', {}),
        });
    },
    ScheduleList({ emit,
        dialog: van.derive(() => ({ title: getValue(props.schedule_dialog)?.title ?? 'Schedules', open: scheduleDialogOpen })),
        items: van.derive(() => getValue(props.schedule_dialog)?.items ?? []),
        permissions: van.derive(() => getValue(props.schedule_dialog)?.permissions ?? { can_edit: false }),
        arg_label: van.derive(() => getValue(props.schedule_dialog)?.arg_label ?? ''),
        arg_values: van.derive(() => getValue(props.schedule_dialog)?.arg_values ?? []),
        sample: van.derive(() => getValue(props.schedule_dialog)?.sample),
        results: van.derive(() => getValue(props.schedule_dialog)?.results),
        onClose: () => emit('ScheduleDialogClosed', {}),
    }),
    NotificationSettings({ emit,
        dialog: van.derive(() => ({ title: getValue(props.notifications_dialog)?.title ?? 'Notifications', open: notificationsDialogOpen })),
        smtp_configured: van.derive(() => getValue(props.notifications_dialog)?.smtp_configured ?? false),
        event: van.derive(() => getValue(props.notifications_dialog)?.event),
        items: van.derive(() => getValue(props.notifications_dialog)?.items ?? []),
        permissions: van.derive(() => getValue(props.notifications_dialog)?.permissions ?? { can_edit: false }),
        scope_label: van.derive(() => getValue(props.notifications_dialog)?.scope_label),
        scope_options: van.derive(() => getValue(props.notifications_dialog)?.scope_options ?? []),
        trigger_options: van.derive(() => getValue(props.notifications_dialog)?.trigger_options ?? []),
        result: van.derive(() => getValue(props.notifications_dialog)?.result),
        onClose: () => emit('NotificationsDialogClosed', {}),
    }),
    wizardContainer,
    editDialogContainer,
    );
}

/**
 *
 * @param {Permissions} permissions
 * @param {Connection[]} connections
 * @param {string?} selectedConnection
 * @param {string?} tableGroupNameFilter
 * @returns
 */
const Toolbar = (permissions, connections, selectedConnection, tableGroupNameFilter, emit) => {
    const connection = van.state(selectedConnection || null);
    const tableGroupFilter = van.state(tableGroupNameFilter || null);

    // Track last value sent to Streamlit so the comparison stays correct across
    // reruns (Toolbar is now mounted once; captured initial values would go stale).
    let lastSent = {
        connection_id: selectedConnection || null,
        table_group_name: tableGroupNameFilter || null,
    };
    van.derive(() => {
        const newConnection = connection.val || null;
        const newFilter = tableGroupFilter.val || null;
        if (newConnection !== lastSent.connection_id || newFilter !== lastSent.table_group_name) {
            const payload = { connection_id: newConnection, table_group_name: newFilter };
            emit('TableGroupsFiltered', { payload });
            lastSent = payload;
        }
    });

    return div(
        { class: 'flex-row fx-align-flex-end fx-justify-space-between fx-gap-4 fx-flex-wrap mb-4' },
        div(
            {class: 'flex-row fx-align-flex-end fx-gap-3'},
            () => (getValue(connections) ?? [])?.length > 1
                ? Select({
                    testId: 'connection-select',
                    label: 'Connection',
                    allowNull: true,
                    value: connection,
                    options: (getValue(connections) ?? []).map((conn) => ({
                        label: conn.connection_name,
                        value: String(conn.connection_id),
                    })),
                    onChange: (value) => connection.val = value,
                })
                : '',
            Input({
                testId: 'table-groups-name-filter',
                icon: 'search',
                label: '',
                placeholder: 'Search table group names',
                width: 300,
                clearable: true,
                value: tableGroupFilter,
                onChange: (value) => tableGroupFilter.val = value || null,
            }),
        ),
        div(
            { class: 'flex-row fx-gap-3' },
            Button({
                icon: 'notifications',
                type: 'stroked',
                label: 'Notifications',
                tooltip: 'Configure email notifications for profiling runs',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('RunNotificationsClicked', {}),
            }),
            Button({
                icon: 'today',
                type: 'stroked',
                label: 'Schedules',
                tooltip: 'Manage when profiling should run for table groups',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('RunSchedulesClicked', {}),
            }),
            permissions.can_edit
                ? Button({
                    type: 'stroked',
                    icon: 'add',
                    label: 'Add Table Group',
                    color: 'basic',
                    style: 'background: var(--button-generic-background-color); width: unset;',
                    onclick: () => emit('AddTableGroupClicked', {}),
                })
                : '',
        )
    );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-tablegroups {
    overflow-y: auto;
    min-height: 400px;
}

.tg-tablegroup--card-title h4 {
    margin: 0;
    color: var(--primary-text-color);
    font-size: 1.5rem;
    text-transform: initial;
}

.tg-empty-state.mt-4 {
    margin-top: 16px;
}
`);

export { TableGroupList };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, TableGroupList(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
