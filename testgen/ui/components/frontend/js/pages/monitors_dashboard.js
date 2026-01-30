/**
 * @import { MonitorSummary } from '../components/monitor_anomalies_summary.js';
 * @import { CronSample, FilterOption, ProjectSummary } from '../types.js';
 * 
 * @typedef Schedule
 * @type {object}
 * @property {boolean} active
 * @property {string} cron_tz
 * @property {CronSample} cron_sample
 * 
 * @typedef Monitor
 * @type {object}
 * @property {string} table_group_id
 * @property {string} table_name
 * @property {('modified'|'added'|'dropped')} table_state
 * @property {number?} freshness_anomalies
 * @property {number?} volume_anomalies
 * @property {number?} schema_anomalies
 * @property {number?} quality_drift_anomalies
 * @property {boolean?} freshness_is_training
 * @property {boolean?} volume_is_training
 * @property {boolean} freshness_is_pending
 * @property {boolean} volume_is_pending
 * @property {boolean} schema_is_pending
 * @property {number?} lookback_start
 * @property {number?} lookback_end
 * @property {string?} latest_update
 * @property {number?} row_count
 * @property {number?} previous_row_count
 * @property {number?} column_adds
 * @property {number?} column_drops
 * @property {number?} column_mods
 * 
 * @typedef MonitorList
 * @type {object}
 * @property {Monitor[]} items
 * @property {number} current_page
 * @property {number} items_per_page
 * @property {number} total_count
 * 
 * @typedef MonitorListFilters
 * @type {object}
 * @property {string?} table_group_id
 * @property {string?} table_name_filter
 * @property {string?} only_tables_with_anomalies
 * 
 * @typedef MonitorListSort
 * @type {object}
 * @property {string?} sort_field
 * @property {('asc'|'desc')?} sort_order
 * 
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {MonitorSummary?} summary
 * @property {Schedule?} schedule
 * @property {FilterOption[]} table_group_filter_options
 * @property {boolean?} has_monitor_test_suite
 * @property {MonitorList} monitors
 * @property {MonitorListFilters} filters
 * @property {MonitorListSort?} sort
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { formatDuration, humanReadableDuration, colorMap, formatNumber, viewPortUnitsToPixels } from '../display_utils.js';
import { Button } from '../components/button.js';
import { Select } from '../components/select.js';
import { Input } from '../components/input.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '../components/empty_state.js';
import { Icon } from '../components/icon.js';
import { Table } from '../components/table.js';
import { Toggle } from '../components/toggle.js';
import { withTooltip } from '../components/tooltip.js';
import { AnomaliesSummary } from '../components/monitor_anomalies_summary.js';

const { div, i, span, b } = van.tags;

const MonitorsDashboard = (/** @type Properties */ props) => {
    loadStylesheet('monitors-dashboard', stylesheet);
    Streamlit.setFrameHeight(viewPortUnitsToPixels(90, 'height'));
    window.testgen.isPage = true;

    let renderTime = new Date();
    const tableGroupFilterValue = van.derive(() => getValue(props.filters).table_group_id ?? null);
    const tableNameFilterValue = van.derive(() => getValue(props.filters).table_name_filter ?? null);
    const onlyAnomaliesFilterValue = van.derive(() => getValue(props.filters).only_tables_with_anomalies === 'true');
    const tableSort = van.derive(() => {
        const sort = getValue(props.sort);
        return {
            field: sort?.sort_field,
            order: sort?.sort_order,
            onSortChange: (sort) => emitEvent('SetParamValues', { payload: { sort_field: sort.field ?? null, sort_order: sort.order ?? null } }),
        };
    });
    const tablePaginator = van.derive(() => {
        const result = getValue(props.monitors);
        return {
            currentPageIdx: result.current_page,
            itemsPerPage: result.items_per_page,
            totalItems: result.total_count,
            onPageChange: (page, pageSize) => emitEvent('SetParamValues', { payload: { current_page: page, items_per_page: pageSize } }),
        };
    });
    const tableRows = van.derive(() => {
        const result = getValue(props.monitors);
        renderTime = new Date();
        return result.items.map(monitor => {
            const rowCountChange = (monitor.row_count ?? 0) - (monitor.previous_row_count ?? 0);

            return {
                table_name: () => span(
                    {
                        class: monitor.table_state === 'dropped' ? 'text-disabled' : '',
                        style: monitor.table_state === 'added' ? `font-weight: 500; color: ${colorMap.tealDark}` : '',
                    },
                    monitor.table_name,
                ),
                freshness: () => AnomalyTag(monitor.freshness_anomalies, monitor.freshness_is_training, monitor.freshness_is_pending),
                volume: () => AnomalyTag(monitor.volume_anomalies, monitor.volume_is_training, monitor.volume_is_pending),
                schema: () => AnomalyTag(monitor.schema_anomalies, false, monitor.schema_is_pending),
                quality_drift: () => AnomalyTag(monitor.quality_drift_anomalies),
                latest_update: () => span(
                    {class: 'text-small text-secondary'},
                    monitor.latest_update ? `${humanReadableDuration(formatDuration(monitor.latest_update, renderTime), true)} ago` : '-',
                ),
                row_count: () => rowCountChange !== 0 ?
                    withTooltip(
                        div(
                            {class: 'flex-row fx-gap-1', style: 'position: relative; display: inline-flex;'},
                            Icon(
                                {style: `font-size: 20px; color: ${rowCountChange > 0 ? colorMap.tealDark : colorMap.redDark};`},
                                rowCountChange > 0 ? 'arrow_upward' : 'arrow_downward',
                            ),
                            span({class: 'text-small text-secondary'}, formatNumber(Math.abs(rowCountChange))),
                        ),
                        {
                            text: div(
                                {class: 'flex-column fx-align-flex-start mb-1'},
                                span(`Previous count: ${formatNumber(monitor.previous_row_count)}`),
                                span(`Latest count: ${formatNumber(monitor.row_count)}`),
                                span(`Percent change: ${formatNumber(rowCountChange * 100 / monitor.previous_row_count, 2)}%`),
                            ),
                        },
                    )
                    : span({class: 'text-small text-secondary'}, '-'),
                schema_changes: () => monitor.schema_anomalies ?
                    withTooltip(
                        div(
                            {
                                class: 'flex-row fx-gap-1 schema-changes',
                                onclick: () => {
                                    const summary = getValue(props.summary);
                                    emitEvent('OpenSchemaChanges', { payload: { 
                                        table_name: monitor.table_name,
                                        start_time: summary?.lookback_start,
                                        end_time: summary?.lookback_end,
                                    }});
                                },
                            },
                            monitor.table_state === 'added' 
                                ? Icon({size: 20, classes: 'schema-icon--add', filled: true}, 'add_box')
                                : null,
                            monitor.table_state === 'dropped' 
                                ? Icon({size: 20, classes: 'schema-icon--drop', filled: true}, 'indeterminate_check_box')
                                : null,
                            monitor.column_adds ? div(
                                {class: 'flex-row'},
                                Icon({size: 20, classes: 'schema-icon--add'}, 'add'),
                                span({class: 'text-small text-secondary'}, formatNumber(monitor.column_adds)),
                            ) : null,
                            monitor.column_drops ? div(
                                {class: 'flex-row'},
                                Icon({size: 20, classes: 'schema-icon--drop'}, 'remove'),
                                span({class: 'text-small text-secondary'}, formatNumber(monitor.column_drops)),
                            ) : null,
                            monitor.column_mods ? div(
                                {class: 'flex-row'},
                                Icon({size: 18, classes: 'schema-icon--mod'}, 'change_history'),
                                span({class: 'text-small text-secondary'}, formatNumber(monitor.column_mods)),
                            ) : null,
                        ),
                        {
                            text: div(
                                {class: 'flex-column fx-align-flex-start'},
                                monitor.table_state === 'added' 
                                    ? span({class: 'mb-1', style: 'font-size: 14px;'}, 'Table added.')
                                    : null,
                                monitor.table_state === 'dropped'
                                    ? span({class: 'mb-1', style: 'font-size: 14px;'}, 'Table dropped.')
                                    : null,
                                b({class: 'mb-1'}, 'Columns'),
                                monitor.column_adds ? span(`Added: ${monitor.column_adds}`) : null,
                                monitor.column_drops ? span(`Dropped: ${monitor.column_drops}`) : null,
                                monitor.column_mods ? span(`Modified: ${monitor.column_mods}`) : null,
                            ),
                            width: 200,
                            position: 'right',
                        },
                    ) : span({class: 'text-small text-secondary'}, '-'),
                action: () => div(
                    {
                        role: 'button',
                        class: 'flex-row fx-gap-1 p-2 clickable',
                        style: 'color: var(--link-color); width: fit-content;',
                        onclick: () => emitEvent('OpenMonitoringTrends', { payload: { table_group_id: monitor.table_group_id, table_name: monitor.table_name }})
                    },
                    span('View'),
                    i({class: 'material-symbols-rounded', style: 'font-size: 18px;'}, 'insights'),
                ),
            };
        });
    });

    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;
    const projectSummary = getValue(props.project_summary);

    return projectSummary.table_group_count > 0
        ? div(
            {style: 'height: 100%;'},
            div(
                { class: 'flex-row fx-align-flex-end fx-justify-space-between fx-gap-4 fx-flex-wrap mb-4' },
                Select({
                    label: 'Table Group',
                    value: tableGroupFilterValue,
                    options: getValue(props.table_group_filter_options) ?? [],
                    allowNull: false,
                    style: 'font-size: 14px;',
                    testId: 'table-group-filter',
                    onChange: (value) => emitEvent('SetParamValues', {payload: {table_group_id: value}}),
                }),
                () => getValue(props.has_monitor_test_suite)
                    ? AnomaliesSummary(getValue(props.summary), 'Total anomalies')
                    : '',
                () => getValue(props.has_monitor_test_suite) && userCanEdit
                    ? div(
                        {class: 'flex-row fx-gap-3'},
                        Button({
                            icon: 'notifications',
                            tooltip: 'Configure email notifications for table group monitors',
                            tooltipPosition: 'bottom-left',
                            color: 'basic',
                            type: 'stroked',
                            style: 'background: var(--button-generic-background-color);', 
                            onclick: () => emitEvent('EditNotifications', {}),
                        }),
                        Button({
                            icon: 'settings',
                            tooltip: 'Edit monitor settings for table group',
                            tooltipPosition: 'bottom-left',
                            color: 'basic',
                            type: 'stroked',
                            style: 'background: var(--button-generic-background-color);', 
                            onclick: () => emitEvent('EditMonitorSettings', {}),
                        }),
                        Button({
                            icon: 'delete',
                            tooltip: 'Delete all monitors for table group',
                            tooltipPosition: 'bottom-left',
                            color: 'basic',
                            type: 'stroked',
                            style: 'background: var(--button-generic-background-color);', 
                            onclick: () => emitEvent('DeleteMonitorSuite', {}),
                        }),
                    )
                    : '',
            ),
            () => getValue(props.has_monitor_test_suite) ? Table(
                {
                    header: () => div(
                        {class: 'flex-row fx-gap-3 p-4 pt-2 pb-2'},
                        Input({
                            id: 'search-tables',
                            name: 'search-tables',
                            placeholder: 'Search tables',
                            clearable: true,
                            width: 230,
                            style: 'font-size: 14px;',
                            icon: 'search',
                            testId: 'search-tables',
                            value: tableNameFilterValue,
                            onChange: (value, state) => emitEvent('SetParamValues', {payload: {table_name_filter: value}}),
                        }),
                        Toggle({
                            name: 'anomalies_only',
                            label: 'Only tables with anomalies',
                            style: 'font-size: 16px;',
                            checked: onlyAnomaliesFilterValue,
                            onChange: (checked) => emitEvent('SetParamValues', {payload: {only_tables_with_anomalies: String(checked).toLowerCase()}}),
                        }),
                        span({class: 'fx-flex'}, ''),
                        () => {
                            const schedule = getValue(props.schedule);
                            if (schedule && !schedule.active) {
                                return div(
                                    { class: 'flex-row fx-gap-1' },
                                    Icon({ style: 'font-size: 16px; color: var(--purple);' }, 'info'),
                                    span(
                                        { style: 'color: var(--purple);' },
                                        'Monitor schedule is paused.',
                                    ),
                                );
                            };
                            if (schedule && schedule.cron_sample.samples) {
                                return withTooltip(
                                    span(
                                        { class: 'text-caption', style: 'position: relative;' },
                                        `Next run: ${schedule.cron_sample.samples[0]}`,
                                    ),
                                    {
                                        text: `Schedule: ${schedule.cron_sample.readable_expr} (${schedule.cron_tz})`,
                                        width: 150,
                                    },
                                );
                            }
                            return '';
                        },
                    ),
                    columns: () => {
                        const lookback = getValue(props.summary)?.lookback ?? 0;
                        const numRuns = lookback === 1 ? 'run' : `${lookback} runs`;
                        return [
                            [
                                {name: 'filler_1', colspan: 1, label: ''},
                                {name: 'anomalies', label: `Anomalies in last ${numRuns}`, colspan: 3, padding: 8, align: 'center'},
                                {name: 'changes', label: `Changes in last ${numRuns}`, colspan: 3, padding: 8, align: 'center'},
                                {name: 'filler_2', label: ''},
                            ],
                            [
                                {name: 'table_name', label: 'Table', width: 200, align: 'left', sortable: true},
                                {name: 'freshness', label: 'Freshness', width: 85, align: 'left', overflow: 'visible'},
                                {name: 'volume', label: 'Volume', width: 85, align: 'left', overflow: 'visible'},
                                {name: 'schema', label: 'Schema', width: 85, align: 'left'},
                                // {name: 'quality_drift', label: 'Quality Drift', width: 185, align: 'left'},
                                {name: 'latest_update', label: 'Latest Update', width: 150, align: 'left', sortable: true},
                                {name: 'row_count', label: 'Row Count', width: 150, align: 'left', sortable: true, overflow: 'visible'},
                                {name: 'schema_changes', label: 'Schema', width: 150, align: 'left', overflow: 'visible'},
                                {name: 'action', label: '', width: 100, align: 'center'},
                            ],
                        ];
                    },
                    emptyState: div(
                        {class: 'flex-row fx-justify-center empty-table-message'},
                        span(
                            {class: 'text-secondary'},
                            'No tables found matching filters',
                        ),
                    ),
                    sort: tableSort,
                    paginator: tablePaginator,
                },
                tableRows,
            )
            : ConditionalEmptyState(projectSummary, userCanEdit),
        )
        : ConditionalEmptyState(projectSummary, userCanEdit);
}

/**
 * @param {number?} anomalies
 * @param {boolean} isTraining
 * @param {boolean} isPending
 */
const AnomalyTag = (anomalies, isTraining = false, isPending = false) => {
    if (isPending) {
        return span({class: 'text-secondary'}, '-');
    }

    const content = van.derive(() => {
        if (isTraining) {
            return withTooltip(
                i({class: 'material-symbols-rounded'}, 'more_horiz'),
                {text: 'Training model'},
            );
        }
        if (anomalies > 0) {
            return span(anomalies);
        }
        return i({class: 'material-symbols-rounded'}, 'check');
    });

    return div(
        {class: `anomaly-tag ${anomalies > 0 ? 'has-anomalies' : ''} ${isTraining ? 'is-training' : ''}`},
        content,
    );
};

/**
 * @param {ProjectSummary} projectSummary
 * @param {boolean} userCanEdit
 */
const ConditionalEmptyState = (projectSummary, userCanEdit) => {
    let args = {
        label: 'No monitors yet for table group',
        message: EMPTY_STATE_MESSAGE.monitors,
        button: Button({
            type: 'stroked',
            icon: 'settings',
            label: 'Configure Monitors',
            color: 'primary',
            style: 'width: unset;',
            disabled: !userCanEdit,
            onclick: () => emitEvent('EditMonitorSettings', {}),
        }),
    }
    if (projectSummary.connection_count <= 0) {
        args = {
            label: 'Your project is empty',
            message: EMPTY_STATE_MESSAGE.connection,
            link: {
                label: 'Go to Connections',
                href: 'connections',
                params: { project_code: projectSummary.project_code },
            },
        };
    } else if (projectSummary.table_group_count <= 0) {
        args = {
            label: 'Your project is empty',
            message: EMPTY_STATE_MESSAGE.tableGroup,
            link: {
                label: 'Go to Table Groups',
                href: 'table-groups',
                params: {
                    project_code: projectSummary.project_code,
                    connection_id: projectSummary.default_connection_id,
                },
            },
        };
    }
    
    return EmptyState({
        icon: 'apps_outage',
        ...args,
    });
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.empty-table-message {
    min-height: 300px;
}

.tg-table-column.table_name,
.tg-table-column.freshness,
.tg-table-column.latest_update,
.tg-table-cell.table_name,
.tg-table-cell.freshness,
.tg-table-cell.latest_update {
    padding-left: 16px !important;
}

.tg-table-column.table_name,
.tg-table-column.schema,
.tg-table-column.schema_changes,
.tg-table-cell.table_name,
.tg-table-cell.schema,
.tg-table-cell.schema_changes {
    border-right: 1px dashed var(--border-color);
}

.tg-table-cell.schema_changes {
    padding-right: 0;
    padding-left: 0;
}

.schema-changes {
    position: relative;
    display: inline-flex;
    cursor: pointer;
    padding: 4px;
    border-radius: 4px;
}

.schema-changes:hover {
    background: var(--select-hover-background);
}

.tg-icon.schema-icon--add {
    cursor: pointer;
    color: ${colorMap.tealDark}; 
}

.tg-icon.schema-icon--drop {
    cursor: pointer;
    color: ${colorMap.redDark}; 
}

.tg-icon.schema-icon--mod {
    cursor: pointer;
    color: ${colorMap.purple}; 
}
`);

export { MonitorsDashboard };
