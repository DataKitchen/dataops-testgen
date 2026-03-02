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
 * @property {number?} metric_anomalies
 * @property {string?} freshness_error_message
 * @property {string?} volume_error_message
 * @property {string?} schema_error_message
 * @property {string?} metric_error_message
 * @property {boolean?} freshness_is_training
 * @property {boolean?} volume_is_training
 * @property {boolean?} metric_is_training
 * @property {boolean} freshness_is_pending
 * @property {boolean} volume_is_pending
 * @property {boolean} schema_is_pending
 * @property {boolean} metric_is_pending
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
 * @property {string?} anomaly_type_filter
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
 * @typedef TableGroupFilterOption
 * @type {FilterOption & { has_monitors: boolean }}
 *
 * @typedef Properties
 * @type {object}
 * @property {ProjectSummary} project_summary
 * @property {MonitorSummary?} summary
 * @property {Schedule?} schedule
 * @property {TableGroupFilterOption[]} table_group_filter_options
 * @property {boolean?} has_monitor_test_suite
 * @property {string?} auto_open_table
 * @property {MonitorList} monitors
 * @property {MonitorListFilters} filters
 * @property {MonitorListSort?} sort
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { formatDuration, formatTimestamp, humanReadableDuration, formatNumber, viewPortUnitsToPixels } from '../display_utils.js';
import { Button } from '../components/button.js';
import { Select } from '../components/select.js';
import { Input } from '../components/input.js';
import { Checkbox } from '../components/checkbox.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '../components/empty_state.js';
import { Icon } from '../components/icon.js';
import { Table } from '../components/table.js';
import { withTooltip } from '../components/tooltip.js';
import { AnomaliesSummary } from '../components/monitor_anomalies_summary.js';

const { div, i, span, b } = van.tags;
const SHOW_CHANGES_COLUMNS_KEY = 'testgen__monitors__showchanges';

const MonitorsDashboard = (/** @type Properties */ props) => {
    loadStylesheet('monitors-dashboard', stylesheet);
    Streamlit.setFrameHeight(viewPortUnitsToPixels(90, 'height'));
    window.testgen.isPage = true;

    let renderTime = new Date();
    const tableGroupFilterValue = van.derive(() => getValue(props.filters).table_group_id ?? null);
    const tableNameFilterValue = van.derive(() => getValue(props.filters).table_name_filter ?? null);
    const anomalyTypeFilterValue = van.derive(() => getValue(props.filters).anomaly_type_filter ?? []);
    const tableSort = van.derive(() => {
        const sort = getValue(props.sort);
        return {
            field: sort?.sort_field,
            order: sort?.sort_order,
            onSortChange: (sort) => emitEvent('SetParamValues', { payload: { sort_field: sort.field ?? null, sort_order: sort.order ?? null } }),
        };
    });
    const showChangesColumns = van.state(Boolean(window.localStorage?.getItem(SHOW_CHANGES_COLUMNS_KEY) === '1'));
    const setShowChanges = (value) => {
        showChangesColumns.val = value ?? false;
        window.localStorage?.setItem(SHOW_CHANGES_COLUMNS_KEY, Number(showChangesColumns.val))
    };
    const tablePaginator = van.derive(() => {
        const result = getValue(props.monitors);
        return {
            currentPageIdx: result.current_page,
            itemsPerPage: result.items_per_page,
            totalItems: result.total_count,
            onPageChange: (page, pageSize) => emitEvent('SetParamValues', { payload: { current_page: page, items_per_page: pageSize } }),
            leftContent: div(
                { class: 'ml-2' },
                Checkbox({
                    label: span({ class: 'mr-1' }, 'Show changes'),
                    checked: showChangesColumns,
                    disabled: false,
                    onChange: setShowChanges,
                }),
            ),
        };
    });
    const autoOpenTable = getValue(props.auto_open_table);
    if (autoOpenTable) {
        setTimeout(() => emitEvent('OpenMonitoringTrends', { payload: { table_name: autoOpenTable } }), 0);
    }

    const openChartsDialog = (monitor) => emitEvent('OpenMonitoringTrends', { payload: { table_name: monitor.table_name }});


    const tableRows = van.derive(() => {
        const result = getValue(props.monitors);
        renderTime = new Date();
        return result.items.map(monitor => {
            const rowCountChange = (monitor.row_count ?? 0) - (monitor.previous_row_count ?? 0);

            return {
                _hasAnomalies: monitor.freshness_anomalies || monitor.volume_anomalies || monitor.schema_anomalies || monitor.metric_anomalies,
                table_name: () => ['added', 'dropped'].includes(monitor.table_state)
                    ? withTooltip(
                        span(
                            {
                                class: monitor.table_state === 'dropped' ? 'text-disabled' : '',
                                style: `position: relative; ${monitor.table_state === 'added' ? 'font-weight: 500;' : ''}`,
                            },
                            monitor.table_name,
                        ),
                        { text: `Table ${monitor.table_state}` },
                    )
                    : monitor.table_name,
                freshness_anomalies: () => AnomalyTag(monitor.freshness_anomalies, monitor.freshness_error_message, monitor.freshness_is_training, monitor.freshness_is_pending, () => openChartsDialog(monitor)),
                volume_anomalies: () => AnomalyTag(monitor.volume_anomalies, monitor.volume_error_message, monitor.volume_is_training, monitor.volume_is_pending, () => openChartsDialog(monitor)),
                schema_anomalies: () => AnomalyTag(monitor.schema_anomalies, monitor.schema_error_message, false, monitor.schema_is_pending, () => openChartsDialog(monitor)),
                metric_anomalies: () => AnomalyTag(monitor.metric_anomalies, monitor.metric_error_message, monitor.metric_is_training, monitor.metric_is_pending, () => openChartsDialog(monitor)),
                latest_update: () => monitor.latest_update
                    ? withTooltip(
                        span(
                            {class: 'text-small', style: 'position: relative;'},
                            `${humanReadableDuration(formatDuration(monitor.latest_update, renderTime), true)} ago`,
                        ),
                        { text: `Latest update detected: ${formatTimestamp(monitor.latest_update)}` },
                    )
                    : span({class: 'text-small text-secondary'}, '-'),
                row_count: () => rowCountChange !== 0 ?
                    withTooltip(
                        div(
                            {class: 'flex-row fx-gap-1', style: 'position: relative; display: inline-flex;'},
                            Icon(
                                {style: 'font-size: 20px; color: var(--primary-text-color);'},
                                rowCountChange > 0 ? 'arrow_upward' : 'arrow_downward',
                            ),
                            span({class: 'text-small'}, formatNumber(Math.abs(rowCountChange))),
                        ),
                        {
                            text: div(
                                {class: 'flex-column fx-align-flex-start mb-1'},
                                span(`Previous count: ${formatNumber(monitor.previous_row_count)}`),
                                span(`Latest count: ${formatNumber(monitor.row_count)}`),
                                span(`Percent change: ${monitor.previous_row_count ? formatNumber(rowCountChange * 100 / monitor.previous_row_count, 2) : '100'}%`),
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
                                ? Icon({size: 20, classes: 'schema-icon', filled: true}, 'add_box')
                                : null,
                            monitor.table_state === 'dropped' 
                                ? Icon({size: 20, classes: 'schema-icon', filled: true}, 'indeterminate_check_box')
                                : null,
                            monitor.column_adds ? div(
                                {class: 'flex-row'},
                                Icon({size: 20, classes: 'schema-icon'}, 'add'),
                                span({class: 'text-small'}, formatNumber(monitor.column_adds)),
                            ) : null,
                            monitor.column_drops ? div(
                                {class: 'flex-row'},
                                Icon({size: 20, classes: 'schema-icon'}, 'remove'),
                                span({class: 'text-small'}, formatNumber(monitor.column_drops)),
                            ) : null,
                            monitor.column_mods ? div(
                                {class: 'flex-row'},
                                Icon({size: 18, classes: 'schema-icon'}, 'change_history'),
                                span({class: 'text-small'}, formatNumber(monitor.column_mods)),
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
                    { class: 'flex-row fx-justify-center fx-gap-2' },
                    Button({
                        icon: 'insights',
                        type: 'icon',
                        tooltip: 'View table trends',
                        tooltipPosition: 'top-left',
                        style: 'color: var(--secondary-text-color);',
                        onclick: () => openChartsDialog(monitor),
                    }),
                    getValue(props.permissions)?.can_edit
                        ? Button({
                            icon: 'edit',
                            type: 'icon',
                            tooltip: 'Edit table monitors',
                            tooltipPosition: 'top-left',
                            style: 'color: var(--secondary-text-color);',
                            onclick: () => emitEvent('EditTableMonitors', { payload: { table_name: monitor.table_name }}),
                        })
                        : null,
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
                    options: (getValue(props.table_group_filter_options) ?? []).map(option => ({
                        ...option,
                        label: span(
                            { class: 'flex-row fx-gap-2' },
                            span({ class: `has-monitors dot text-disabled ${option.has_monitors ? '' : 'invisible'}` }),
                            option.label,
                        ),
                    })),
                    allowNull: false,
                    style: 'font-size: 14px;',
                    testId: 'table-group-filter',
                    onChange: (value) => emitEvent('SetParamValues', {payload: {table_group_id: value, table_name: null}}),
                }),
                () => getValue(props.has_monitor_test_suite)
                    ? AnomaliesSummary(getValue(props.summary), 'Total anomalies', {
                        onTagClick: (type) => {
                            const current = anomalyTypeFilterValue.val;
                            const newFilter = current.length === 1 && current[0] === type ? null : type;
                            emitEvent('SetParamValues', { payload: { anomaly_type_filter: newFilter, current_page: 0 } });
                        },
                        activeTypes: anomalyTypeFilterValue,
                    })
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
                        {class: 'flex-row fx-align-flex-end fx-gap-3 p-4 pt-2 pb-2'},
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
                            onChange: (value, state) => emitEvent('SetParamValues', {payload: {table_name_filter: value, current_page: 0}}),
                        }),
                        Select({
                            label: 'Anomaly type',
                            value: anomalyTypeFilterValue,
                            options: [
                                { label: 'Freshness', value: 'freshness' },
                                { label: 'Volume', value: 'volume' },
                                { label: 'Schema', value: 'schema' },
                                { label: 'Metrics', value: 'metrics' },
                            ],
                            multiSelect: true,
                            width: 200,
                            onChange: (values) => emitEvent('SetParamValues', {
                                payload: { anomaly_type_filter: values.length ? values.join(',') : null, current_page: 0 },
                            }),
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
                                        `Next run: ${formatTimestamp(schedule.cron_sample.samples[0])}`,
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
                        const showChanges = showChangesColumns.val;

                        return [
                            [
                                {name: 'filler_1', colspan: 1, label: ''},
                                {name: 'anomalies', label: `Anomalies in last ${numRuns}`, colspan: 4, padding: 8, align: 'center'},

                                ...(
                                    showChanges
                                        ? [
                                            {name: 'changes', label: `Changes in last ${numRuns}`, colspan: 3, padding: 8, align: 'center'},
                                            {name: 'filler_2', label: ''},
                                        ]
                                        : []
                                ),
                            ],
                            [
                                {name: 'table_name', label: 'Table', width: 200, align: 'left', sortable: true, overflow: 'visible'},
                                {name: 'freshness_anomalies', label: 'Freshness', width: 85, align: 'left', sortable: true, overflow: 'visible'},
                                {name: 'volume_anomalies', label: 'Volume', width: 85, align: 'left', sortable: true, overflow: 'visible'},
                                {name: 'schema_anomalies', label: 'Schema', width: 85, sortable: true, align: 'left'},
                                {name: 'metric_anomalies', label: 'Metrics', width: 85, sortable: true, align: 'left', overflow: 'visible'},

                                ...(
                                    showChanges
                                        ? [
                                            {name: 'latest_update', label: 'Latest Update', width: 150, align: 'left', sortable: true, overflow: 'visible'},
                                            {name: 'row_count', label: 'Row Count', width: 150, align: 'left', sortable: true, overflow: 'visible'},
                                            {name: 'schema_changes', label: 'Schema', width: 150, align: 'left', overflow: 'visible'},
                                        ]
                                        : []
                                ),

                                {
                                    name: 'action',
                                    label: showChanges ? `View trends |
                                    Edit monitors` : 'View trends | Edit monitors', // Formatted this way for white-space: pre-line
                                    width: 100,
                                    align: 'center',
                                    overflow: 'visible',
                                },
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
                    rowClass: (row) => row._hasAnomalies ? 'has-anomalies' : '',
                },
                tableRows,
            )
            : ConditionalEmptyState(projectSummary, userCanEdit),
        )
        : ConditionalEmptyState(projectSummary, userCanEdit);
}

/**
 * @param {number?} anomalies
 * @param {string?} errorMessage
 * @param {boolean} isTraining
 * @param {boolean} isPending
 * @param {Function} onClick
 */
const AnomalyTag = (anomalies, errorMessage = null, isTraining = false, isPending = false, onClick = undefined) => {
    if (isPending) {
        return withTooltip(
            span({class: 'text-secondary pl-2 pr-2', style: 'position: relative;'}, '-'),
            { text: 'No results yet or not configured' },
        );
    }

    const hasErrors = !!errorMessage;
    const content = van.derive(() => {
        if (anomalies > 0) {
            return span(anomalies);
        }
        if (hasErrors) {
            return withTooltip(
                i({class: 'material-symbols-rounded'}, 'warning'),
                {
                    text: div(
                        { class: 'flex-column fx-gap-2 text-left' },
                        span('Error in latest run. Reconfigure the monitor or contact support.'),
                        i(errorMessage),
                    ),
                    width: 360,
                },
            );
        }
        if (isTraining) {
            return withTooltip(
                i({class: 'material-symbols-rounded'}, 'more_horiz'),
                {text: 'Training model'},
            );
        }
        return i({class: 'material-symbols-rounded'}, 'check');
    });

    return div(
        { class: `anomaly-tag-wrapper flex-row p-1 ${onClick ? 'clickable' : ''}`, onclick: onClick },
        div(
            {
                class: `anomaly-tag ${anomalies > 0 ? 'has-anomalies' : ''} ${hasErrors ? 'has-errors' : ''} ${isTraining ? 'is-training' : ''}`,
            },
            content,
        ),
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

.has-monitors {
    font-size: 5px;
}

.tg-select--field .has-monitors {
    display: none;
}

th.tg-table-column.action span {
    white-space: pre-line;
    text-transform: none;
}

.tg-table-column.table_name,
.tg-table-column.freshness_anomalies,
.tg-table-column.latest_update,
.tg-table-cell.table_name,
.tg-table-cell.freshness_anomalies,
.tg-table-cell.latest_update {
    padding-left: 16px !important;
}

.tg-table-column.table_name,
.tg-table-column.metric_anomalies,
.tg-table-column.schema_changes,
.tg-table-cell.table_name,
.tg-table-cell.metric_anomalies,
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

.tg-icon.schema-icon {
    cursor: pointer;
    color: var(--primary-text-color);
}

.anomaly-tag-wrapper {
    width: fit-content;
    border-radius: 4px;
}
.anomaly-tag-wrapper.clickable:hover {
    background: var(--select-hover-background);
}

tr.has-anomalies {
    background-color: rgba(239, 83, 80, 0.08);
}
`);

export { MonitorsDashboard };
