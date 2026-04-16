/**
 * @import { ProjectSummary } from '../types.js';
 * @import { TableGroup } from '../components/table_group_form.js';
 * @import { Connection } from '../components/connection_form.js';
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
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { Button } from '../components/button.js';
import { Card } from '../components/card.js';
import { Caption } from '../components/caption.js';
import { Link } from '../components/link.js';
import { getValue, emitEvent, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { EMPTY_STATE_MESSAGE, EmptyState } from '../components/empty_state.js';
import { Select } from '../components/select.js';
import { Icon } from '../components/icon.js';
import { Input } from '../components/input.js';
import { TruncatedText } from '../components/truncated_text.js';

const { button, div, h4, i, span } = van.tags;

/**
 * @param {Properties} props
 * @returns {HTMLElement}
 */
const DcButton = ({ tableGroupId, projectCode }) => button(
    { class: 'tg-dc-pill', title: 'View Data Contract', 'aria-label': 'View Data Contract', onclick: () => emitEvent('LinkClicked', { href: 'data-contracts', params: { project_code: projectCode, table_group_id: tableGroupId } }) },
    i({ class: 'material-symbols-rounded' }, 'contract'),
    span({ class: 'tg-dc-label' }, 'Data Contract'),
);

const ActionIcon = ({ icon, label, tooltip, onclick }) => button(
    { class: 'tg-action-icon', title: tooltip, 'aria-label': tooltip, onclick },
    i({ class: 'material-symbols-rounded' }, icon),
    span({ class: 'tg-action-label', 'aria-hidden': 'true' }, label),
);

const TableGroupList = (props) => {
    loadStylesheet('tablegrouplist', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const wrapperId = 'tablegroup-list-wrapper';

    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return div(
        { id: wrapperId, class: 'tg-tablegroups' },
        () => {
            const permissions = getValue(props.permissions) ?? {can_edit: false};
            const connections = getValue(props.connections) ?? [];
            const connectionId = getValue(props.connection_id);
            const tableGroupNameFilter = getValue(props.table_group_name);
            const tableGroups = getValue(props.table_groups) ?? [];
            const projectSummary = getValue(props.project_summary);

            if (connections.length <= 0) {
                return EmptyState({
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

            return projectSummary.table_group_count > 0
            ? div(
                Toolbar(permissions, connections, connectionId, tableGroupNameFilter),
                tableGroups.length
                    ? tableGroups.map((tableGroup) => Card({
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
                                    Link({
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
                                            onclick: () => emitEvent('RunProfilingClicked', { payload: tableGroup.id }),
                                        }),
                                    )
                                    : '',
                            )
                        ),
                        actionContent: div(
                            { class: 'tg-action-group' },
                            DcButton({ tableGroupId: tableGroup.id, projectCode: projectSummary.project_code }),
                            permissions.can_edit
                                ? ActionIcon({
                                    icon: 'edit',
                                    label: 'Edit',
                                    tooltip: 'Edit table group',
                                    onclick: () => emitEvent('EditTableGroupClicked', { payload: tableGroup.id }),
                                  })
                                : '',
                            permissions.can_edit
                                ? ActionIcon({
                                    icon: 'delete',
                                    label: 'Delete',
                                    tooltip: 'Delete table group',
                                    onclick: () => emitEvent('DeleteTableGroupClicked', { payload: tableGroup.id }),
                                  })
                                : '',
                        ),
                    }))
                    : div(
                        { class: 'mt-7 text-secondary', style: 'text-align: center;' },
                        'No table groups found matching filters',
                    ),
                )
            : EmptyState({
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
                    onclick: () => emitEvent('AddTableGroupClicked', {}),
                }),
            });
        },
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
const Toolbar = (permissions, connections, selectedConnection, tableGroupNameFilter) => {
    const connection = van.state(selectedConnection || null);
    const tableGroupFilter = van.state(tableGroupNameFilter || null);

    van.derive(() => {
        if (connection.val !== selectedConnection || tableGroupFilter.val !== tableGroupNameFilter) {
            emitEvent('TableGroupsFiltered', { payload: { connection_id: connection.val || null, table_group_name: tableGroupFilter.val || null } });
        }
    });

    return div(
        { class: 'flex-row fx-align-flex-end fx-justify-space-between fx-gap-4 fx-flex-wrap mb-4' },
        div(
            {class: 'flex-row fx-align-flex-end fx-gap-3'},
            (getValue(connections) ?? [])?.length > 1
                ? Select({
                    testId: 'connection-select',
                    label: 'Connection',
                    allowNull: true,
                    value: connection,
                    options: getValue(connections)?.map((connection) => ({
                        label: connection.connection_name,
                        value: String(connection.connection_id),
                    })) ?? [],
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
                onclick: () => emitEvent('RunNotificationsClicked', {}),
            }),
            Button({
                icon: 'today',
                type: 'stroked',
                label: 'Schedules',
                tooltip: 'Manage when profiling should run for table groups',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--button-generic-background-color);',
                onclick: () => emitEvent('RunSchedulesClicked', {}),
            }),
            permissions.can_edit
                ? Button({
                    type: 'stroked',
                    icon: 'add',
                    label: 'Add Table Group',
                    color: 'basic',
                    style: 'background: var(--button-generic-background-color); width: unset;',
                    onclick: () => emitEvent('AddTableGroupClicked', {}),
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

.tg-action-group {
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

/* Edit / Delete — icon circles, expand on hover */
button.tg-action-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 36px;
    width: 36px;
    max-width: 36px;
    border: none;
    border-radius: 50%;
    padding: 0;
    background: transparent;
    color: rgba(0, 0, 0, .54);
    cursor: pointer;
    overflow: hidden;
    white-space: nowrap;
    flex-shrink: 0;
    font-family: inherit;
    transition:
        max-width .25s ease,
        width .25s ease,
        border-radius .25s ease,
        padding .25s ease,
        color .2s ease,
        background .2s ease;
}

button.tg-action-icon .material-symbols-rounded {
    font-size: 20px;
    flex-shrink: 0;
}

button.tg-action-icon .tg-action-label {
    display: inline-block;
    max-width: 0;
    opacity: 0;
    overflow: hidden;
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
    margin-left: 0;
    pointer-events: none;
    transition:
        max-width .25s ease,
        opacity .15s ease,
        margin-left .25s ease;
}

button.tg-action-icon:hover,
button.tg-action-icon:focus-visible {
    max-width: 180px;
    width: auto;
    border-radius: 20px;
    padding: 0 14px 0 10px;
    color: rgba(0, 0, 0, .87);
    background: rgba(0, 0, 0, .05);
    outline: 2px solid rgba(0, 0, 0, .4);
    outline-offset: 1px;
}

button.tg-action-icon:hover .tg-action-label,
button.tg-action-icon:focus-visible .tg-action-label {
    max-width: 100px;
    opacity: 1;
    margin-left: 6px;
}

/* Data Contract pill — always expanded */
button.tg-dc-pill {
    display: inline-flex;
    align-items: center;
    height: 36px;
    max-width: 180px;
    border-radius: 20px;
    border: 1.5px solid rgba(0, 0, 0, .3);
    padding: 0 14px 0 10px;
    background: transparent;
    color: rgba(0, 0, 0, .87);
    cursor: pointer;
    overflow: hidden;
    white-space: nowrap;
    flex-shrink: 0;
    font-family: inherit;
    font-size: 13px;
    font-weight: 500;
    gap: 6px;
}

button.tg-dc-pill .material-symbols-rounded {
    font-size: 20px;
    flex-shrink: 0;
}

button.tg-dc-pill .tg-dc-label {
    display: inline-block;
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    max-width: 140px;
    opacity: 1;
    margin-left: 6px;
    pointer-events: none;
}

button.tg-dc-pill:hover {
    border-color: rgba(0, 0, 0, .7);
    background: rgba(0, 0, 0, .04);
}
`);

export { TableGroupList };
