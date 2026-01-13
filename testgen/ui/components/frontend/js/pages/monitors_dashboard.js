/**
 * @import { MonitorSummary } from '../components/monitor_anomalies_summary.js';
 * @import { FilterOption, ProjectSummary } from '../types.js';
 * 
 * @typedef Monitor
 * @type {object}
 * @property {string} table_group_id
 * @property {string} table_name
 * @property {('modified'|'added'|'deleted')} table_state
 * @property {number?} freshness_anomalies
 * @property {number?} volume_anomalies
 * @property {number?} schema_anomalies
 * @property {number?} quality_drift_anomalies
 * @property {string?} latest_update
 * @property {number?} row_count
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
 * @property {MonitorSummary} summary
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

const { div, i, span } = van.tags;

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
        return result.items.map(monitor => ({
            table_state: ['added', 'deleted'].includes(monitor.table_state)
                ? (
                    monitor.table_state === 'added'
                        ? withTooltip(
                            Icon({classes: 'table-added-state', filled: true}, 'add_box'),
                            {
                                text: 'Table added',
                                width: 85,
                                position: 'bottom-right',
                            },
                        )
                        : withTooltip(
                            Icon({classes: 'table-deleted-state', filled: true}, 'indeterminate_check_box'),
                            {
                                text: 'Table deleted',
                                width: 85,
                                position: 'bottom-right',
                            },
                        )
                )
                : undefined,
            table_name: span({}, monitor.table_name),
            freshness: AnomalyTag(monitor.freshness_anomalies),
            volume: AnomalyTag(monitor.volume_anomalies),
            schema: AnomalyTag(monitor.schema_anomalies),
            quality_drift: AnomalyTag(monitor.quality_drift_anomalies),
            latest_update: span(
                {class: 'text-small text-secondary'},
                monitor.latest_update ? humanReadableDuration(formatDuration(monitor.latest_update, renderTime)) : '-',
            ),
            row_count: monitor.row_count ?
                div(
                    {class: 'flex-row fx-gap-1'},
                    i(
                        {class: 'material-symbols-rounded', style: `font-size: 16px; color: ${monitor.row_count > 0 ? colorMap.tealDark : colorMap.redDark}`},
                        monitor.row_count > 0 ? 'arrow_upward' : 'arrow_downward',
                    ),
                    span({class: 'text-small text-secondary'}, formatNumber(monitor.row_count)),
                )
                : span({class: 'text-small text-secondary'}, '-'),
            action: div(
                {
                    role: 'button',
                    class: 'flex-row fx-gap-1 p-2 clickable',
                    style: 'color: var(--link-color); width: fit-content;',
                    onclick: () => emitEvent('OpenMonitoringTrends', { payload: { table_group_id: monitor.table_group_id, table_name: monitor.table_name }})
                },
                span('View'),
                i({class: 'material-symbols-rounded', style: 'font-size: 18px;'}, 'insights'),
            ),
        }));
    });

    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;
    const projectSummary = getValue(props.project_summary);

    return projectSummary.table_group_count > 0
        ? div(
            {style: 'height: 100%;'},
            div(
                { class: 'flex-row fx-align-flex-end fx-justify-space-between mb-4' },
                Select({
                    label: 'Table Group',
                    value: tableGroupFilterValue,
                    options: getValue(props.table_group_filter_options) ?? [],
                    allowNull: false,
                    style: 'font-size: 14px;',
                    testId: 'table-group-filter',
                    onChange: (value) => emitEvent('SetParamValues', {payload: {table_group_id: value}}),
                }),
                span({class: 'fx-flex'}),
                () => getValue(props.has_monitor_test_suite) 
                    ? AnomaliesSummary(getValue(props.summary), 'Total anomalies')
                    : '',
                span({class: 'fx-flex'}),
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
                        userCanEdit
                            ? Button({
                                icon: 'edit',
                                iconSize: 18,
                                label: 'Edit monitor settings',
                                color: 'basic',
                                width: 'auto',
                                onclick: () => emitEvent('EditTestSuite', { payload: {} }),
                            })
                            : '',
                    ),
                    columns: () => {
                        const lookback = getValue(props.summary)?.lookback ?? 0;
                        const numRuns = lookback === 1 ? 'run' : `${lookback} runs`;
                        return [
                            [
                                {name: 'filler_1', colspan: 2, label: ''},
                                {name: 'anomalies', label: `Anomalies in last ${numRuns}`, colspan: 2, padding: 8},
                                {name: 'changes', label: `Changes in last ${numRuns}`, colspan: 1, padding: 8},
                                {name: 'filler_2', label: ''},
                            ],
                            [
                                {name: 'table_state', label: '', align: 'center', width: 36, overflow: 'visible'},
                                {name: 'table_name', label: 'Table', width: 200, align: 'left', sortable: true},
                                {name: 'freshness', label: 'Freshness', width: 85, align: 'left'},
                                // {name: 'volume', label: 'Volume', width: 85, align: 'left'},
                                {name: 'schema', label: 'Schema', width: 85, align: 'left'},
                                // {name: 'quality_drift', label: 'Quality Drift', width: 185, align: 'left'},
                                {name: 'latest_update', label: 'Latest Update', width: 150, align: 'left', sortable: true},
                                // {name: 'row_count', label: 'Row Count', width: 150, align: 'left', sortable: true},
                                {name: 'action', label: '', width: 100, align: 'center'},
                            ],
                        ];
                    },
                    emptyState: div(
                        {class: 'flex-row fx-justify-center empty-table-message'},
                        span({class: 'text-secondary'}, 'No tables found matching filters'),
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
 * @param {number?} value
 */
const AnomalyTag = (value) => {
    const content = van.derive(() => {
        if (value == undefined) {
            return i({class: 'material-symbols-rounded'}, 'remove');
        }

        if (value > 0) {
            return span(value);
        }

        return i({class: 'material-symbols-rounded'}, 'check');
    });

    return div(
        {class: `anomaly-tag ${(value != undefined && value > 0) ? 'has-anomalies' : ''} ${value == undefined ? 'no-value' : ''}`},
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
        // TODO: Add action
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
.table-added-state {
    color: ${colorMap.deepPurple};
}

.table-deleted-state {
    color: ${colorMap.red};
}

.empty-table-message {
    min-height: 300px;
}
`);

export { MonitorsDashboard };
