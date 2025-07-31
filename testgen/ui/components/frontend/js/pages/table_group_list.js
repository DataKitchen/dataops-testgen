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
import { withTooltip } from '../components/tooltip.js';

const { div, h4, i, span } = van.tags;

/**
 * @param {Properties} props
 * @returns {HTMLElement}
 */
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
                Toolbar(permissions, connections, connectionId),
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
                                                        {max: 3},
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
                                    onclick: () => emitEvent('EditTableGroupClicked', { payload: tableGroup.id }),
                                }),
                                Button({
                                    type: 'icon',
                                    icon: 'delete',
                                    iconSize: 18,
                                    tooltip: 'Delete table group',
                                    tooltipPosition: 'left',
                                    color: 'basic',
                                    onclick: () => emitEvent('DeleteTableGroupClicked', { payload: tableGroup.id }),
                                }),
                            )
                            : undefined,
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
 * @returns 
 */
const Toolbar = (permissions, connections, selectedConnection) => {
    return div(
        { class: 'flex-row fx-align-flex-end fx-justify-space-between mb-4' },
        (getValue(connections) ?? [])?.length > 1
            ? Select({
                testId: 'connection-select',
                label: 'Connection',
                allowNull: true,
                height: 38,
                value: selectedConnection,
                options: getValue(connections)?.map((connection) => ({
                    label: connection.connection_name,
                    value: String(connection.connection_id),
                })) ?? [],
                onChange: (value) => emitEvent('ConnectionSelected', { payload: value }),
            })
            : span(''),
        div(
            { class: 'flex-row fx-gap-4' },
            Button({
                icon: 'today',
                type: 'stroked',
                label: 'Profiling Schedules',
                tooltip: 'Manage when profiling should run for table groups',
                tooltipPosition: 'bottom',
                width: 'fit-content',
                style: 'background: var(--dk-card-background);',
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

/**
 * @typedef TruncatedTextOptions
 * @type {object}
 * @property {number} max
 * @property {string?} class
 * 
 * @param {TruncatedTextOptions} options
 * @param {string[]} children
 */
const TruncatedText = ({ max, ...options }, ...children) => {
    const sortedChildren = [...children.sort((a, b) => a.length - b.length)];
    const tooltipText = children.sort((a, b) => a.localeCompare(b)).join(', ');

    return div(
        { class: () => `${options.class ?? ''}`, style: 'position: relative;' },
        span(sortedChildren.slice(0, max).join(', ')),
        sortedChildren.length > max
            ? withTooltip(
                i({class: 'text-caption'}, ` + ${sortedChildren.length - max} more`),
                {
                    text: tooltipText,
                    position: 'top-right',
                }
            )
            : '',
    );
};

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
