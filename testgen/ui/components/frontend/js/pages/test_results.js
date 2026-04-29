/**
 * @typedef TestResultItem
 * @type {object}
 * @property {string} test_result_id
 * @property {string} table_name
 * @property {string} column_names
 * @property {string} test_name_short
 * @property {string} test_description
 * @property {string} measure_uom
 * @property {string?} measure_uom_description
 * @property {number?} threshold_value
 * @property {number?} result_measure
 * @property {string} result_status
 * @property {string?} disposition
 * @property {string?} action
 * @property {string?} result_message
 * @property {string?} input_parameters
 * @property {string?} test_definition_id
 * @property {string?} test_scope
 * @property {string?} table_groups_id
 * @property {string?} severity
 * @property {string} test_type
 *
 * @typedef Properties
 * @type {object}
 * @property {TestResultItem[]} items
 * @property {object[]} summary
 * @property {string} score
 * @property {object} filters
 * @property {string?} selected_id
 * @property {string?} selected_item
 * @property {object} permissions
 * @property {object} run_info
 * @property {object?} profiling_column
 * @property {object?} source_data
 * @property {object?} edit_test
 * @property {number} page
 * @property {number} total_count
 * @property {number} page_size
 * @property {object[]} sort_state
 * @property {object} filter_options
 */
import van from '/app/static/js/van.min.js';
import { createEmitter, getValue, isEqual, loadStylesheet, parseDate } from '/app/static/js/utils.js';
import { Table } from '/app/static/js/components/table.js';
import { Select } from '/app/static/js/components/select.js';
import { Tabs, Tab } from '/app/static/js/components/tabs.js';
import { Button } from '/app/static/js/components/button.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { DropdownButton } from '/app/static/js/components/dropdown_button.js';
import { Icon } from '/app/static/js/components/icon.js';
import { SummaryBar } from '/app/static/js/components/summary_bar.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Toggle } from '/app/static/js/components/toggle.js';
import { ProfilingResultsDialog } from '../shared/profiling_results_dialog.js';
import { SourceDataDialog } from '../shared/source_data_dialog.js';
import { TestResultsChart } from './test_results_chart.js';
import { TestDefinitionSummary } from './test_definition_summary.js';
import { EditDialogComponent } from './test_definitions.js';
import { TestDefinitionNotes } from './test_definition_notes.js';
import { withTooltip } from '/app/static/js/components/tooltip.js';

const { button: btn, div, i: icon, span, h3, h4, p, small } = van.tags;

const STATUS_COLORS = {
    Passed: 'var(--green)',
    Warning: 'var(--orange)',
    Failed: 'var(--red)',
    Error: 'var(--brown, #795548)',
    Log: 'var(--blue)',
};

/** Composite icon button: flag with a diagonal strikethrough (pen_size_1 rotated). */
const ClearFlagButton = ({ disabled, onclick }) => {
    return withTooltip(btn(
        {
            class: 'tg-button tg-icon-button tg-basic-button',
            tooltip: 'Clear flag',
            disabled,
            onclick,
            style: 'width: 40px; position: relative;',
        },
        span({ class: 'tg-button-focus-state-indicator' }, ''),
        div(
            { style: 'position: relative; display: inline-flex; align-items: center; justify-content: center;' },
            icon({ class: 'material-symbols-rounded', style: 'font-size: 20px;' }, 'flag'),
            icon({ class: 'material-symbols-rounded', style: 'font-size: 24px; position: absolute; top: -3px; left: -3px; transform: rotate(90deg);' }, 'pen_size_1'),
        ),
    ), { text: 'Clear flag' });
};

const FLAGGED_FILTER_OPTIONS = [
    { label: 'Flagged', value: 'Flagged' },
    { label: 'Not Flagged', value: 'Not Flagged' },
];

const DATA_COLUMNS = [
    { name: 'table_name', label: 'Table', width: 160, sortable: true, overflow: 'hidden' },
    { name: 'column_names', label: 'Columns/Focus', width: 150, sortable: true, overflow: 'hidden' },
    { name: 'test_name_short', label: 'Test Type', width: 140, sortable: true, overflow: 'hidden' },
    { name: 'result_measure_display', label: 'Result Measure', width: 120, sortable: true, align: 'right' },
    { name: 'measure_uom', label: 'Unit of Measure', width: 130, overflow: 'hidden' },
    { name: 'status_display', label: 'Status', width: 90, sortable: true },
    { name: 'action', label: 'Action', width: 70, align: 'center' },
    { name: 'flagged_display', label: 'Flagged', width: 80, align: 'center' },
    { name: 'notes_count', label: 'Notes', width: 70, align: 'center' },
    { name: 'result_message', label: 'Details', width: 200, overflow: 'hidden' },
];

const HISTORY_COLUMNS = [
    { name: 'test_date_display', label: 'Date', width: 160, align: 'left' },
    { name: 'threshold_display', label: 'Threshold', width: 100, align: 'right' },
    { name: 'measure_display', label: 'Measure', width: 100, align: 'right' },
    { name: 'status_display', label: 'Status', width: 80, align: 'center' },
];

const DISPOSITION_ICONS = {
    'Confirmed': { icon: 'check_circle', style: 'color: var(--green); font-size: 16px' },
    'Dismissed': { icon: 'cancel', style: 'color: var(--red); font-size: 16px' },
    'Inactive': { icon: 'notifications_off', style: 'color: var(--secondary-text-color); font-size: 16px' },
};

const buildDispositionIcon = (disposition) => {
    const info = DISPOSITION_ICONS[disposition];
    return info ? Icon({ style: info.style }, info.icon) : '';
};

const ACTION_FILTER_OPTIONS = [
    { label: 'Confirmed', value: 'Confirmed' },
    { label: 'Dismissed', value: 'Dismissed' },
    { label: 'Muted', value: 'Inactive' },
    { label: 'No Action', value: 'No Action' },
];

const STATUS_FILTER_OPTIONS = [
    { label: 'Failed + Warning', value: 'Failed + Warning' },
    { label: 'Failed', value: 'Failed' },
    { label: 'Warning', value: 'Warning' },
    { label: 'Passed', value: 'Passed' },
    { label: 'Error', value: 'Error' },
    { label: 'Log', value: 'Log' },
];

const formatNumber = (v) => {
    if (v == null || v === '') return '';
    const n = Number(v);
    if (Number.isNaN(n)) return String(v);
    return n.toLocaleString(undefined, { maximumFractionDigits: 5 });
};

const buildTableRow = (item) => ({
    id: item.test_result_id,
    table_name: item.table_name ?? '',
    column_names: item.column_names ?? '',
    test_name_short: item.test_name_short ?? '',
    result_measure_display: formatNumber(item.result_measure),
    result_measure: item.result_measure,
    measure_uom: item.measure_uom ?? '',
    status_display: item.result_status
        ? span({ style: `color: ${STATUS_COLORS[item.result_status] || 'inherit'}; font-weight: 500` }, item.result_status)
        : '',
    result_status: item.result_status ?? '',
    action: buildDispositionIcon(item.disposition),
    flagged_display: item.flagged_display?.toLowerCase() === 'yes'
        ? Icon({classes: 'text-error display-table-cell', filled: true}, 'flag')
        : '',
    notes_count: item.notes_count ? div(
        {class: 'flex-row fx-justify-center'},
        Icon({}, 'sticky_note_2'),
        span(item.notes_count),
    ) : '',
    result_message: item.result_message ?? '',
});

const ExportMenu = (statusFilter, tableFilter, columnFilter, testTypeFilter, actionFilter, flaggedFilter, hasSelection, getSelectedIds, emit) => {
    return DropdownButton({
        icon: 'download',
        label: 'Export',
        buttonSize: 'small',
        items: () => {
            const items = [
                { label: 'All results', onclick: () => emit('ExportAll', {}) },
                {
                    label: 'Filtered results',
                    onclick: () => emit('ExportFiltered', {
                        payload: {
                            status: statusFilter.rawVal,
                            table_name: tableFilter.rawVal,
                            column_name: columnFilter.rawVal,
                            test_type: testTypeFilter.rawVal,
                            action: actionFilter.rawVal,
                            flagged: flaggedFilter.rawVal,
                        },
                    }),
                },
            ];
            if (hasSelection()) {
                items.push({
                    label: 'Selected results',
                    onclick: () => emit('ExportSelected', { payload: { ids: getSelectedIds() } }),
                });
            }
            return items;
        },
    });
};

const TestResultSourceDataHeader = (d) => {
    const children = [
        div(
            { class: 'text-caption mb-2' },
            span({ style: 'font-weight: 500' }, `Table > Column: `),
            span({}, `${d.table_name} > ${d.column_names}`),
        ),
        h4({ style: 'margin: 0 0 4px' }, d.test_name_short),
        d.test_description ? p({ class: 'text-caption', style: 'margin: 0 0 8px' }, d.test_description) : '',
    ];

    if (d.input_parameters) {
        children.push(
            h4({ style: 'margin: 12px 0 4px' }, 'Test Parameters'),
            div({ class: 'text-caption', style: 'max-height: 75px; overflow: auto; margin-bottom: 8px' }, d.input_parameters),
        );
    }

    if (d.result_message) {
        children.push(
            h4({ style: 'margin: 12px 0 4px' }, 'Result Detail'),
            p({ class: 'text-caption', style: 'margin: 0 0 8px' }, d.result_message),
        );
    }

    return div({ class: 'flex-column' }, ...children);
};

// ProfilingDialog and SourceDataDialog are now shared components from ../shared/

const EditTestDialog = (props) => {
    const emit = props.emit;
    const editDialogOpen = van.state(false);
    const editDialogInfo = van.derive(() => getValue(props.edit_test) ?? null);

    van.derive(() => { editDialogOpen.val = !!editDialogInfo.val?.open; });

    return EditDialogComponent({
        open: editDialogOpen,
        info: editDialogInfo,
        validateResult: props.validate_result,
        onClose: () => {
            editDialogOpen.val = false;
            emit('EditTestClosed', {});
        },
    }, emit);
};

const TestResults = (/** @type Properties */ props) => {
    const { emit } = props;
    loadStylesheet('test-results', stylesheet);

    const items = van.derive(() => getValue(props.items) ?? []);
    const summary = van.derive(() => getValue(props.summary) ?? []);
    const permissions = van.derive(() => getValue(props.permissions) ?? {});
    const runInfo = van.derive(() => getValue(props.run_info) ?? {});

    const selectedItemData = van.derive(() => getValue(props.selected_item) ?? null);

    // Pagination state from Python
    const currentPage = van.derive(() => getValue(props.page) ?? 0);
    const totalCount = van.derive(() => getValue(props.total_count) ?? 0);
    const pageSize = van.derive(() => getValue(props.page_size) ?? 500);

    // Filter options from Python (full unfiltered set)
    const filterOptions = van.derive(() => getValue(props.filter_options) ?? {});

    const initialFilters = getValue(props.filters) ?? {};
    const statusFilter = van.state('status' in initialFilters ? initialFilters.status : 'Failed + Warning');
    const tableFilter = van.state(initialFilters.table_name ?? null);
    const columnFilter = van.state(initialFilters.column_name ?? null);
    const testTypeFilter = van.state(initialFilters.test_type ?? null);
    const actionFilter = van.state(initialFilters.action ?? null);
    const flaggedFilter = van.state(initialFilters.flagged ?? null);

    // Notes dialog: persistent local state + one-time sync from Python prop
    const notesDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.notes_dialog)) notesDialogOpen.val = true; });

    // Sort state initialized from Python
    const initialSortState = getValue(props.sort_state) ?? [];
    const sortColumns = van.state(
        initialSortState.length > 0
            ? initialSortState
            : [
                { field: 'table_name', order: 'asc' },
                { field: 'column_names', order: 'asc' },
                { field: 'test_name_short', order: 'asc' },
            ]
    );

    const selectedRowId = van.state(getValue(props.selected_id) ?? null);
    const multiSelect = van.state(false);
    const selectAll = van.state(false);

    // Filter options derived from Python-provided full list
    const tableOptions = van.derive(() => {
        const names = filterOptions.val.table_names ?? [];
        return names.map(n => ({ label: n, value: n }));
    });

    // Column options filtered by selected table
    const columnOptions = van.derive(() => {
        const allNames = filterOptions.val.column_names ?? [];
        // When a table is selected, we still show all columns from the full list
        // since the server provides the full unfiltered set
        return allNames.map(n => ({ label: n, value: n }));
    });

    // Test type options from filter_options
    const testTypeOptions = van.derive(() => {
        const types = filterOptions.val.test_types ?? [];
        return types.map(t => ({ label: t.test_name_short || t.test_type, value: t.test_type }));
    });

    // No client-side filtering or sorting -- items from Python are already filtered, sorted, and paginated
    const selectedRow = van.derive(() =>
        selectedRowId.val ? items.val.find(r => r.test_result_id === selectedRowId.val) ?? null : null
    );

    // Per-row checkbox states
    const checkboxStates = new Map();
    const getCheckboxState = (id) => {
        if (!checkboxStates.has(id)) checkboxStates.set(id, van.state(false));
        return checkboxStates.get(id);
    };
    const clearAllCheckboxStates = () => {
        for (const state of checkboxStates.values()) state.val = false;
        selectAll.val = false;
        selectedIdsCount.val = 0;
    };

    // Selection tracking (declared early — referenced by derives below)
    let selectedIds = [];
    const selectedIdSetForRestore = new Set();
    const selectedIdsCount = van.state(0);

    // Select All handler (declared early — used by checkbox column)
    const onSelectAllToggle = (checked) => {
        if (checked) {
            selectAll.val = true;
            for (const item of items.rawVal) {
                const state = getCheckboxState(item.test_result_id);
                state.val = true;
                selectedIdSetForRestore.add(item.test_result_id);
            }
            selectedIds = [...selectedIdSetForRestore];
            selectedIdsCount.val = selectedIds.length;
        } else {
            clearAllCheckboxStates();
            selectedIds = [];
            selectedIdSetForRestore.clear();
        }
    };

    // Columns: prepend checkbox when multi-select is on (header has reactive select-all checkbox)
    const checkboxColumn = {
        name: '_checkbox',
        label: () => Checkbox({
            label: '',
            checked: selectAll.val,
            indeterminate: !selectAll.val && selectedIdsCount.val > 0,
            onChange: onSelectAllToggle,
        }),
        width: 32,
        align: 'center',
    };
    const tableColumns = van.derive(() => multiSelect.val ? [checkboxColumn, ...DATA_COLUMNS] : DATA_COLUMNS);

    // Clear checkbox states and selection when toggling multi-select off
    van.derive(() => {
        if (!multiSelect.val) {
            clearAllCheckboxStates();
            selectedIds = [];
            selectedIdSetForRestore.clear();
        }
    });


    // Table rows built from items (already filtered/sorted/paginated by server)
    const tableRows = van.derive(() => {
        const isMulti = multiSelect.val;
        const isSelectAll = selectAll.val;
        const currentItems = items.val;

        // When selectAll is active, sync tracking state to current items
        if (isMulti && isSelectAll) {
            for (const item of currentItems) {
                const state = getCheckboxState(item.test_result_id);
                state.val = true;
                selectedIdSetForRestore.add(item.test_result_id);
            }
            selectedIds = [...selectedIdSetForRestore];
            selectedIdsCount.val = selectedIds.length;
        }

        return currentItems.map(item => {
            const row = buildTableRow(item);
            if (isMulti) {
                const checked = getCheckboxState(item.test_result_id);
                row._checkbox = () => Checkbox({ label: '', checked, style: 'pointer-events: none' });
            }
            return row;
        });
    });

    const onSortChange = (newColumns) => {
        sortColumns.val = newColumns;
        emit('SortChanged', { payload: { columns: newColumns } });
    };

    const tableSortOptions = van.derive(() => ({
        columns: sortColumns.val,
        onSortChange,
    }));

    // Paginator handlers

    // Selection callback
    const isInitiallySelected = (row, _) => {
        if (multiSelect.rawVal) return selectedIdSetForRestore.has(row.id);
        return row.id === selectedRowId.rawVal;
    };
    const onRowsSelected = (idxs) => {
        if (multiSelect.rawVal) {
            const currentPageItemIds = new Set(items.rawVal.map(r => r.test_result_id));
            const activeSet = new Set();
            for (const i of idxs) {
                const item = items.rawVal[i];
                if (item) activeSet.add(item.test_result_id);
            }
            // Update restore set: only modify entries for current page items
            for (const id of currentPageItemIds) {
                if (activeSet.has(id)) {
                    selectedIdSetForRestore.add(id);
                } else {
                    selectedIdSetForRestore.delete(id);
                }
            }
            for (const [id, state] of checkboxStates) {
                if (currentPageItemIds.has(id)) {
                    state.val = activeSet.has(id);
                }
            }
            selectedIds = [...selectedIdSetForRestore];
            selectedIdsCount.val = selectedIds.length;
            // If user deselected rows while selectAll was on, turn selectAll off
            if (selectAll.rawVal && activeSet.size < currentPageItemIds.size) {
                selectAll.val = false;
            }
            // Auto-enable selectAll when all items are individually selected
            if (!selectAll.rawVal && totalCount.rawVal > 0 && selectedIds.length >= totalCount.rawVal) {
                selectAll.val = true;
            }
        } else {
            if (idxs.length > 0) {
                const row = items.rawVal[idxs[0]];
                if (row && row.test_result_id !== selectedRowId.rawVal) {
                    selectedRowId.val = row.test_result_id;
                    emit('RowSelected', { payload: row.test_result_id });
                }
            }
        }
    };

    const getCurrentFilters = () => ({
        status: statusFilter.rawVal,
        table_name: tableFilter.rawVal,
        column_name: columnFilter.rawVal,
        test_type: testTypeFilter.rawVal,
        action: actionFilter.rawVal,
        flagged: flaggedFilter.rawVal,
    });

    const emitFilterChanged = () => {
        emit('FilterChanged', { payload: getCurrentFilters() });
    };

    const onStatusFilterChange = (value) => {
        statusFilter.val = value;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onTableFilterChange = (value) => {
        tableFilter.val = value;
        columnFilter.val = null;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onColumnFilterChange = (value, meta) => {
        columnFilter.val = meta?.isCustom ? `%${value}%` : value;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onTestTypeFilterChange = (value) => {
        testTypeFilter.val = value;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onActionFilterChange = (value) => {
        actionFilter.val = value;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onFlaggedFilterChange = (value) => {
        flaggedFilter.val = value;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const getSelectedResultIds = () => {
        if (multiSelect.val && selectedIdSetForRestore.size > 0) {
            return [...selectedIdSetForRestore];
        }
        return selectedRowId.rawVal ? [selectedRowId.rawVal] : [];
    };

    const onDisposition = (status) => {
        if (selectAll.rawVal) {
            emit('DispositionAll', { payload: { filters: getCurrentFilters(), status } });
            return;
        }
        const ids = getSelectedResultIds();
        if (ids.length > 0) {
            emit('DispositionChanged', { payload: { test_result_ids: ids, status } });
        }
    };

    // Table header bar
    const tableHeader = div(
        { class: 'flex-row fx-align-center fx-gap-2 p-2' },
        Toggle({
            label: () => {
                return div(
                    { class: 'flex-column' },
                    span('Multi-Select'),
                    () => {
                        if (!multiSelect.val) return '';
                        if (selectAll.val) return span({ class: 'text-caption' }, () => `All ${totalCount.val} matching results selected`);
                        const count = selectedIdsCount.val;
                        if (count > 0) return span({ class: 'text-caption' }, `${count} result${count !== 1 ? 's' : ''} selected`);
                        return '';
                    },
                );
            },
            checked: () => multiSelect.val,
            onChange: (checked) => { multiSelect.val = checked; },
        }),
        div({ class: 'fx-flex' }),
        () => {
            if (!permissions.val.can_disposition) return '';
            const isAll = selectAll.val;
            const count = selectedIdsCount.val;
            // In multi-select mode, just check if there's a selection — we can't
            // reliably determine item status across pages with server-side pagination.
            const disabled = multiSelect.val
                ? !isAll && count === 0
                : (() => { const row = selectedRow.val; return !row || row.result_status === 'Passed'; })();
            return div(
                { class: 'flex-row fx-gap-1' },
                Button({ type: 'icon', icon: 'check_circle', tooltip: 'Confirm selected as relevant', disabled, onclick: () => onDisposition('Confirmed') }),
                Button({ type: 'icon', icon: 'cancel', tooltip: 'Dismiss selected as not relevant', disabled, onclick: () => onDisposition('Dismissed') }),
                Button({ type: 'icon', icon: 'notifications_off', tooltip: 'Mute selected tests for future runs', disabled, onclick: () => onDisposition('Inactive') }),
                Button({ type: 'icon', icon: 'restart_alt', tooltip: 'Clear action on selected', disabled, onclick: () => onDisposition('No Decision') }),
            );
        },
        // Flag/unflag buttons
        () => {
            if (!permissions.val.can_disposition) return '';
            const isAll = selectAll.val;
            const count = selectedIdsCount.val;
            const noSelection = !isAll && count === 0 && !selectedRow.val;

            const onFlag = (value) => {
                if (isAll) {
                    emit('FlagAll', { payload: { filters: getCurrentFilters(), value } });
                } else if (count > 0) {
                    // Multi-select: send result IDs — backend resolves to definition IDs
                    emit('FlagChanged', { payload: { test_result_ids: getSelectedResultIds(), value } });
                } else {
                    // Single-select: send definition ID directly
                    const row = selectedRow.rawVal;
                    if (row?.test_definition_id) {
                        emit('FlagChanged', { payload: { test_definition_ids: [row.test_definition_id], value } });
                    }
                }
            };

            return div(
                { class: 'flex-row fx-gap-1' },
                span({ style: 'width: 0px; height: 24px; border-right: 1px dashed var(--border-color);'}, ''),
                Button({
                    type: 'icon', icon: 'flag', tooltip: 'Flag selected', disabled: noSelection,
                    onclick: () => onFlag(true),
                }),
                ClearFlagButton({
                    disabled: noSelection,
                    onclick: () => onFlag(false),
                }),
            );
        },
        span({ style: 'width: 0px; height: 24px; border-right: 1px dashed var(--border-color);'}, ''),
        () => {
            const hasAnySelection = selectedIdsCount.val > 0 || !!selectedRow.val;
            if (!hasAnySelection) return '';

            return Button({
                type: 'stroked', icon: 'download', label: 'Issue Report', width: 'auto',
                size: 'small', style: 'background: var(--button-generic-background-color);',
                onclick: () => emit('IssueReportClicked', { payload: { ids: getSelectedResultIds() } }),
            });
        },
        ExportMenu(
            statusFilter, tableFilter, columnFilter, testTypeFilter, actionFilter, flaggedFilter,
            () => selectedRowId.val || selectedIds.length > 0,
            getSelectedResultIds,
            emit,
        ),
    );

    const paginatorOptions = van.derive(() => ({
        totalItems: totalCount.val,
        currentPageIdx: currentPage.val,
        itemsPerPage: pageSize.val,
        pageSizeOptions: [100, 500, 1000],
        onPageChange: (pageIdx, newPerPage) => {
            if (newPerPage !== pageSize.rawVal) {
                if (!selectAll.rawVal) {
                    clearAllCheckboxStates();
                    selectedIds = [];
                    selectedIdSetForRestore.clear();
                }
                emit('PageChanged', { payload: { page: 0, page_size: newPerPage } });
            } else {
                emit('PageChanged', { payload: { page: pageIdx } });
            }
        },
    }));

    // Build the main table once
    const dataTable = Table(
        {
            emit,
            columns: tableColumns,
            header: tableHeader,
            highDensity: true,
            dynamicWidth: true,
            height: '40vh',
            emptyState: div(
                { class: 'flex-row fx-justify-center empty-table-message' },
                span({ class: 'text-secondary' }, 'No test results found matching filters'),
            ),
            sort: tableSortOptions,
            paginator: paginatorOptions,
            selection: {
                get multi() { return multiSelect.val; },
                onRowsSelected,
                isInitiallySelected,
            },
        },
        tableRows,
    );

    // Build history rows from selected item data
    const historyRows = van.derive(() => {
        const si = selectedItemData.val;
        if (!si?.history?.length) return [];
        return si.history.map(h => ({
            test_date_display: h.test_date ? new Date(h.test_date).toLocaleString() : '',
            threshold_display: formatNumber(h.threshold_value),
            measure_display: formatNumber(h.result_measure),
            status_display: h.result_status
                ? span({ style: `color: ${STATUS_COLORS[h.result_status] || 'inherit'}; font-weight: 500` }, h.result_status)
                : '',
        }));
    });

    const createHistoryTable = () => Table(
        { emit, columns: HISTORY_COLUMNS, highDensity: true, height: '250px' },
        historyRows,
    );

    // Chart data state (fed to TestResultsChart)
    const chartData = van.derive(() => {
        const si = selectedItemData.val;
        return si?.history ?? [];
    });
    const chartDataState = van.state([]);
    van.derive(() => { chartDataState.val = chartData.val; });

    // Test definition state (fed to TestDefinitionSummary)
    const testDefState = van.state(null);
    van.derive(() => {
        const si = selectedItemData.val;
        testDefState.val = si?.test_definition ?? null;
    });

    return div(
        { 'data-testid': 'test-results', class: 'flex-column' },

        // Dialogs (mounted once, driven by props from Python)
        ProfilingResultsDialog({ emit,
            profilingColumn: van.derive(() => getValue(props.profiling_column) ?? null),
            onClose: () => emit('ProfilingClosed', {}),
        }),
        SourceDataDialog({ emit,
            sourceData: van.derive(() => getValue(props.source_data) ?? null),
            onClose: () => emit('SourceDataClosed', {}),
            renderHeader: TestResultSourceDataHeader,
        }),
        EditTestDialog(props),

        // Notes dialog
        Dialog(
            {
                title: 'Test Notes',
                open: notesDialogOpen,
                onClose: () => {
                    notesDialogOpen.val = false;
                    emit('NotesDialogClosed', {});
                },
                width: '36rem',
            },
            () => {
                const data = getValue(props.notes_dialog);
                if (!data) return span();
                return TestDefinitionNotes({ emit,
                    test_label: data.test_label,
                    notes: data.notes,
                    current_user: data.current_user,
                    test_definition_id: data.id,
                });
            },
        ),

        // Header row: summary bar + score
        div(
            { class: 'flex-row fx-gap-2 fx-align-flex-end mb-2 fx-flex-wrap' },
            div(
                { class: 'fx-flex', style: 'min-width: 300px' },
                () => SummaryBar({ items: summary.val, height: 20, width: 800 }),
            ),
            div(
                { class: 'tg-tr--score flex-row fx-align-flex-end fx-gap-1' },
                div(
                    { class: 'tg-tr--score flex-column fx-align-center' },
                    small({ class: 'text-caption' }, 'Score'),
                    span({ class: 'tg-tr--score-value' }, () => getValue(props.score) ?? '--'),
                ),
                Button({
                    type: 'icon',
                    icon: 'autorenew',
                    tooltip: 'Recalculate score',
                    style: 'color: var(--secondary-text-color)',
                    onclick: () => emit('ScoreRefreshClicked', {}),
                }),
            ),
        ),

        // Filters row
        div(
            { class: 'flex-row fx-gap-2 fx-align-flex-end mb-2 fx-flex-wrap' },
            () => Select({
                label: 'Status',
                value: statusFilter.val,
                options: STATUS_FILTER_OPTIONS,
                testId: 'status-filter',
                style: 'min-width: 160px',
                onChange: onStatusFilterChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Table',
                value: tableFilter.val,
                options: tableOptions.val,
                testId: 'table-filter',
                style: 'min-width: 180px',
                filterable: true,
                onChange: onTableFilterChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Column',
                value: columnFilter.val,
                options: columnOptions.val,
                testId: 'column-filter',
                style: 'min-width: 180px',
                filterable: true,
                acceptNewOptions: true,
                onChange: onColumnFilterChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Test Type',
                value: testTypeFilter.val,
                options: testTypeOptions.val,
                testId: 'test-type-filter',
                style: 'min-width: 160px',
                filterable: true,
                onChange: onTestTypeFilterChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Action',
                value: actionFilter.val,
                options: ACTION_FILTER_OPTIONS,
                testId: 'action-filter',
                style: 'min-width: 140px',
                onChange: onActionFilterChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Flagged',
                value: flaggedFilter.val,
                options: FLAGGED_FILTER_OPTIONS,
                testId: 'flagged-filter',
                style: 'min-width: 140px',
                onChange: onFlaggedFilterChange,
                allowNull: true,
            }),
        ),

        // Data table
        dataTable,

        // Detail panel (hidden in multi-select mode)
        div(
            { style: () => selectedRow.val && !multiSelect.val ? 'margin-top: 16px' : 'display: none' },
            () => {
                const row = selectedRow.val;
                if (!row) return '';

                const si = selectedItemData.val;
                const hasData = si && si.test_result_id === row.test_result_id;

                return div(
                    { class: 'tg-tr--detail flex-column fx-gap-4' },

                    // Action buttons row
                    div(
                        { class: 'flex-row fx-gap-2 fx-justify-content-flex-end' },
                        ...[
                            permissions.val.can_edit ? Button({
                                type: 'stroked', icon: 'edit', label: 'Edit', width: 'auto',
                                style: 'background: var(--button-generic-background-color);',
                                onclick: () => emit('EditTestClicked', { payload: { test_result_id: row.test_result_id } }),
                            }) : '',
                            row.test_definition_id ? Button({
                                type: 'stroked', icon: 'sticky_note_2', label: 'Notes', width: 'auto',
                                style: 'background: var(--button-generic-background-color);',
                                onclick: () => emit('NotesClicked', { payload: { id: row.test_definition_id, table_name: row.table_name, column_name: row.column_names, test_name_short: row.test_name_short } }),
                            }) : '',
                            row.column_names ? Button({
                                type: 'stroked', icon: 'query_stats', label: 'Profiling', width: 'auto',
                                style: 'background: var(--button-generic-background-color);',
                                onclick: () => emit('ProfilingClicked', { payload: row.test_result_id }),
                            })
                            : '',
                            Button({
                                type: 'stroked', icon: 'visibility', label: 'Source Data', width: 'auto',
                                style: 'background: var(--button-generic-background-color);',
                                onclick: () => emit('SourceDataClicked', { payload: row.test_result_id }),
                            }),
                        ].filter(Boolean),
                    ),

                    // Two-column content
                    div(
                        { class: 'flex-row fx-gap-4 fx-align-flex-start' },

                        // Left column
                        div(
                            { class: 'flex-column fx-flex', style: 'min-width: 0' },
                            h3({ class: 'tg-tr--detail-title' }, row.test_name_short),
                            row.test_description
                                ? p({ class: 'tg-tr--detail-desc' }, row.test_description)
                                : '',
                            row.measure_uom_description
                                ? small({ class: 'text-caption' }, row.measure_uom_description)
                                : '',
                            row.result_message
                                ? small({ class: 'text-caption', style: 'margin-top: 4px' }, row.result_message)
                                : '',
                            div({ style: 'margin-top: 12px' }, hasData ? createHistoryTable() : ''),
                        ),

                        // Right column
                        div(
                            { class: 'flex-column fx-flex', style: 'min-width: 0' },
                            hasData
                                ? Tabs(
                                    { testId: 'test-result-detail' },
                                    Tab(
                                        { label: 'History' },
                                        si.history?.length
                                            ? TestResultsChart({ emit, data: chartDataState })
                                            : div({ class: 'text-caption p-4' }, 'Test history not available.'),
                                    ),
                                    Tab(
                                        { label: 'Test Definition' },
                                        si.test_definition
                                            ? TestDefinitionSummary({ emit, test_definition: testDefState })
                                            : div({ class: 'text-caption p-4' }, 'Test definition not available.'),
                                    ),
                                )
                                : div(
                                    { class: 'flex-row fx-align-center fx-justify-center p-4' },
                                    span({ class: 'text-caption' }, 'Loading details...'),
                                ),
                        ),
                    ),
                );
            },
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-tr--score-value {
    font-size: 28px;
    font-weight: 500;
    line-height: 1.2;
}
.tg-tr--detail {
    border-top: 1px dashed var(--border-color, #dddfe2);
    padding-top: 16px;
}
.tg-tr--detail-title {
    margin: 0 0 4px 0;
    font-size: 18px;
    font-weight: 500;
    color: var(--primary-text-color);
}
.tg-tr--detail-desc {
    margin: 0 0 4px 0;
    font-size: 14px;
    color: var(--primary-text-color);
}
.tg-tr--info-msg {
    padding: 8px 12px;
    background: var(--blue-light, #e3f2fd);
    border-radius: 4px;
    color: var(--primary-text-color);
    font-size: 14px;
}
.tg-tr--error-msg {
    padding: 8px 12px;
    background: var(--red-light, #ffebee);
    border-radius: 4px;
    color: var(--red, #c62828);
    font-size: 14px;
}
.tg-tr--code-block {
    background: var(--secondary-background-color, #f5f5f5);
    border-radius: 4px;
    padding: 12px;
    overflow-x: auto;
    max-height: 150px;
    font-size: 13px;
    margin: 0;
}
`);

export { TestResults };

export default (component) => {
    let { data, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, TestResults(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
