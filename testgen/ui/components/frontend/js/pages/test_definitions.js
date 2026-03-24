import van from '/app/static/js/van.min.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { getValue, isEqual, emitEvent, loadStylesheet } from '/app/static/js/utils.js';
import { Table } from '/app/static/js/components/table.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Button } from '/app/static/js/components/button.js';
import { Select } from '/app/static/js/components/select.js';
import { Input } from '/app/static/js/components/input.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Toggle } from '/app/static/js/components/toggle.js';
import { Attribute } from '/app/static/js/components/attribute.js';
import { TestDefinitionForm } from '/app/static/js/components/test_definition_form.js';
import { RunTestsDialog } from '/app/static/js/components/run_tests_dialog.js';
import { Textarea } from '/app/static/js/components/textarea.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { DropdownButton } from '/app/static/js/components/dropdown_button.js';

const { div, span, strong, input, label } = van.tags;

const TABLE_COLUMNS = [
    { name: 'table_name', label: 'Table', width: 180, sortable: true, overflow: 'hidden' },
    { name: 'column_name', label: 'Column / Focus', width: 180, sortable: true, overflow: 'hidden' },
    { name: 'test_name_short', label: 'Test Type', width: 160, sortable: true, overflow: 'hidden' },
    { name: 'test_active_display', label: 'Active', width: 80 },
    { name: 'lock_refresh_display', label: 'Locked', width: 80 },
    { name: 'urgency', label: 'Urgency', width: 100 },
    { name: 'export_to_observability_display', label: 'Observability', width: 120 },
    { name: 'profiling_as_of_date', label: 'Based on Profiling', width: 160 },
    { name: 'last_manual_update', label: 'Last Manual Update', width: 160 },
];

const SEVERITY_OPTIONS = [
    { label: 'Log', value: 'Log' },
    { label: 'Warning', value: 'Warning' },
    { label: 'Fail', value: 'Fail' },
];

const SCOPE_LABELS = { referential: 'Referential', table: 'Table', column: 'Column', custom: 'Custom' };

// Blank test definition field defaults for add mode
const BLANK_PARAM_FIELDS = {
    custom_query: null,
    baseline_ct: null,
    baseline_unique_ct: null,
    baseline_value: null,
    baseline_value_ct: null,
    threshold_value: null,
    baseline_sum: null,
    baseline_avg: null,
    baseline_sd: null,
    lower_tolerance: null,
    upper_tolerance: null,
    subset_condition: null,
    groupby_names: null,
    having_condition: null,
    window_date_column: null,
    window_days: null,
    match_schema_name: null,
    match_table_name: null,
    match_column_names: null,
    match_subset_condition: null,
    match_groupby_names: null,
    match_having_condition: null,
    history_calculation: null,
    history_calculation_upper: null,
    history_lookback: null,
};

const TestDefinitions = (/** @type object */ props) => {
    loadStylesheet('test-definitions', stylesheet);

    const permissions = van.derive(() => getValue(props.permissions) ?? {});
    const canEdit = van.derive(() => getValue(permissions).can_edit ?? false);
    const canDisposition = van.derive(() => getValue(permissions).can_disposition ?? false);

    const filterOptions = van.derive(() => getValue(props.filter_options) ?? { tables: [], columns: [], test_types: [] });
    const currentFilters = van.derive(() => getValue(props.current_filters) ?? {});

    const tableFilter = van.state(null);
    const columnFilter = van.state(null);
    const testTypeFilter = van.state(null);

    // Initialize filters from Python query params (runs once on mount)
    const filtersInitialized = van.state(false);
    van.derive(() => {
        if (filtersInitialized.val) return;
        const cf = currentFilters.val;
        tableFilter.val = cf.table_name ?? null;
        columnFilter.val = cf.column_name ?? null;
        testTypeFilter.val = cf.test_type ?? null;
        filtersInitialized.val = true;
    });

    const columnFilterOptions = van.derive(() => {
        const cols = filterOptions.val.columns ?? [];
        const table = tableFilter.val;
        const filtered = table ? cols.filter(c => c.table_name === table) : cols;
        return [...new Map(filtered.map(c => [c.column_name, c])).values()]
            .sort((a, b) => (a.column_name ?? '').localeCompare(b.column_name ?? ''))
            .map(c => ({ label: c.column_name, value: c.column_name }));
    });

    const tableFilterOptions = van.derive(() =>
        (filterOptions.val.tables ?? []).map(t => ({ label: t, value: t }))
    );

    const testTypeFilterOptions = van.derive(() =>
        (filterOptions.val.test_types ?? []).map(tt => ({ label: tt.test_name_short, value: tt.test_type }))
    );

    const onFilterChange = () => emitEvent('FilterChanged', {
        payload: {
            table_name: tableFilter.val || null,
            column_name: columnFilter.val || null,
            test_type: testTypeFilter.val || null,
        },
    });

    const testDefinitions = van.derive(() => getValue(props.test_definitions) ?? []);

    // Pagination state from Python
    const currentPage = van.derive(() => getValue(props.page) ?? 0);
    const totalCount = van.derive(() => getValue(props.total_count) ?? 0);
    const pageSize = van.derive(() => getValue(props.page_size) ?? 500);

    // Sort state initialized from Python
    const initialSortState = getValue(props.sort_state) ?? [];
    const sortColumns = van.state(
        initialSortState.length > 0
            ? initialSortState
            : [{ field: 'table_name', order: 'asc' }, { field: 'column_name', order: 'asc' }]
    );

    // Selection state
    const multiSelectMode = van.state(false);
    const selectAll = van.state(false);
    const selectedRowId = van.state(null);

    // Per-row checkbox states (consistent with test_results/hygiene_issues pattern)
    const checkboxStates = new Map();
    const getCheckboxState = (id) => {
        if (!checkboxStates.has(id)) checkboxStates.set(id, van.state(false));
        return checkboxStates.get(id);
    };
    const clearAllCheckboxStates = () => {
        for (const state of checkboxStates.values()) state.val = false;
        selectAll.val = false;
    };

    let selectedIds = [];
    const selectedIdSetForRestore = new Set();

    const onSelectAllToggle = (checked) => {
        selectAll.val = checked;
        if (checked) {
            for (const item of testDefinitions.rawVal) {
                const state = getCheckboxState(item.id);
                state.val = true;
                selectedIdSetForRestore.add(item.id);
            }
            selectedIds = testDefinitions.rawVal.map(r => r.id);
        } else {
            clearAllCheckboxStates();
            selectedIds = [];
            selectedIdSetForRestore.clear();
        }
    };

    const selectAllCheckbox = Checkbox({
        label: '',
        checked: () => selectAll.val,
        onChange: onSelectAllToggle,
    });
    const checkboxColumn = { name: '_checkbox', label: selectAllCheckbox, width: 32, align: 'center' };
    const tableColumns = van.derive(() => multiSelectMode.val ? [checkboxColumn, ...TABLE_COLUMNS] : TABLE_COLUMNS);

    // Clear checkbox states when toggling multi-select off
    van.derive(() => {
        if (!multiSelectMode.val) {
            clearAllCheckboxStates();
            selectedIds = [];
            selectedIdSetForRestore.clear();
        }
    });

    // Reactive selection count for button enable/disable
    const selectedIdsCount = van.state(0);

    const selectedRows = van.derive(() => {
        const count = selectedIdsCount.val; // reactive dependency
        if (multiSelectMode.val) {
            const idSet = new Set(selectedIds);
            return testDefinitions.val.filter(r => idSet.has(r.id));
        }
        const row = selectedRowId.val ? testDefinitions.val.find(r => r.id === selectedRowId.val) : null;
        return row ? [row] : [];
    });
    const singleSelected = van.derive(() =>
        !multiSelectMode.val && selectedRows.val.length === 1 ? selectedRows.val[0] : null
    );

    // Dialog open states (local JS state, persists across Python reruns)
    const addDialogOpen = van.state(false);
    const editDialogOpen = van.state(false);
    const deleteDialogOpen = van.state(false);
    const unlockDialogOpen = van.state(false);
    const copyMoveDialogOpen = van.state(false);

    // Sync dialog open state from Python props
    const addDialogInfo = van.derive(() => getValue(props.add_dialog) ?? null);
    const editDialogInfo = van.derive(() => getValue(props.edit_dialog) ?? null);
    const deleteDialogInfo = van.derive(() => getValue(props.delete_dialog) ?? null);
    const unlockDialogInfo = van.derive(() => getValue(props.unlock_dialog) ?? null);
    const copyMoveDialogInfo = van.derive(() => getValue(props.copy_move_dialog) ?? null);

    van.derive(() => { if (addDialogInfo.val?.open) addDialogOpen.val = true; });
    van.derive(() => { if (editDialogInfo.val?.open) editDialogOpen.val = true; });
    van.derive(() => { if (deleteDialogInfo.val?.open) deleteDialogOpen.val = true; });
    van.derive(() => { if (unlockDialogInfo.val?.open) unlockDialogOpen.val = true; });
    van.derive(() => { if (copyMoveDialogInfo.val?.open) copyMoveDialogOpen.val = true; });

    const runTestsDialogData = van.derive(() => getValue(props.run_tests_dialog) ?? null);

    // Table rows built from items (already filtered/sorted/paginated by server)
    const tableRows = van.derive(() => {
        const isMulti = multiSelectMode.val;
        const isSelectAll = selectAll.val;
        const currentItems = testDefinitions.val;

        // When selectAll is active, sync tracking state to current page items
        if (isMulti && isSelectAll) {
            selectedIdSetForRestore.clear();
            const newIds = [];
            for (const item of currentItems) {
                const state = getCheckboxState(item.id);
                state.val = true;
                selectedIdSetForRestore.add(item.id);
                newIds.push(item.id);
            }
            selectedIds = newIds;
            selectedIdsCount.val = newIds.length;
        }

        return currentItems.map(item => {
            const row = { ...item };
            if (isMulti) {
                const checked = getCheckboxState(item.id);
                row._checkbox = Checkbox({ label: '', checked, style: 'pointer-events: none' });
            }
            return row;
        });
    });

    const onSortChange = (newColumns) => {
        sortColumns.val = newColumns;
        emitEvent('SortChanged', { payload: { columns: newColumns } });
    };

    const tableSortOptions = van.derive(() => ({
        columns: sortColumns.val,
        onSortChange,
    }));

    const isInitiallySelected = (row, _) => {
        if (multiSelectMode.rawVal) return selectedIdSetForRestore.has(row.id);
        return row.id === selectedRowId.rawVal;
    };

    const onRowsSelected = (idxs) => {
        if (multiSelectMode.rawVal) {
            const newIds = [];
            const activeSet = new Set();
            for (const i of idxs) {
                const item = testDefinitions.rawVal[i];
                if (item) {
                    newIds.push(item.id);
                    activeSet.add(item.id);
                }
            }
            selectedIdSetForRestore.clear();
            for (const id of activeSet) selectedIdSetForRestore.add(id);
            for (const [id, state] of checkboxStates) {
                state.val = activeSet.has(id);
            }
            selectedIds = newIds;
            selectedIdsCount.val = newIds.length;
            // If user deselected rows while selectAll was on, turn selectAll off
            if (selectAll.rawVal && newIds.length < testDefinitions.rawVal.length) {
                selectAll.val = false;
            }
        } else {
            if (idxs.length > 0) {
                const row = testDefinitions.rawVal[idxs[0]];
                if (row && row.id !== selectedRowId.rawVal) {
                    selectedRowId.val = row.id;
                }
            }
        }
    };

    const paginatorOptions = van.derive(() => ({
        totalItems: totalCount.val,
        currentPageIdx: currentPage.val,
        itemsPerPage: pageSize.val,
        pageSizeOptions: [100, 500, 1000],
        onPageChange: (pageIdx, newPerPage) => {
            if (!selectAll.rawVal) clearAllCheckboxStates();
            if (newPerPage !== pageSize.rawVal) {
                emitEvent('PageChanged', { payload: { page: 0, page_size: newPerPage } });
            } else {
                emitEvent('PageChanged', { payload: { page: pageIdx } });
            }
        },
    }));

    // Table header bar: multi-select toggle + edit buttons | dashed separator | disposition buttons + export
    const tableHeader = div(
        { class: 'flex-row fx-align-center fx-gap-2 p-2 fx-flex-wrap' },
        () => canDisposition.val
            ? Toggle({
                label: 'Multi-Select',
                checked: () => multiSelectMode.val,
                onChange: (v) => { multiSelectMode.val = v; },
            })
            : '',
        () => multiSelectMode.val && selectAll.val
            ? span({ class: 'text-caption' }, () => `All ${totalCount.val} matching definitions selected`)
            : '',
        div({ class: 'fx-flex' }),
        // Edit buttons (left group)
        () => {
            if (!canEdit.val) return '';
            const selected = selectedRows.val;
            const isAll = selectAll.val;
            const hasSelection = isAll || selected.length > 0;
            const isSingle = !isAll && selected.length === 1;
            // Only send minimal fields to avoid serialization issues
            const minimalSelected = () => selected.map(r => ({
                id: r.id, table_name: r.table_name, column_name: r.column_name,
                test_type: r.test_type, lock_refresh: r.lock_refresh,
            }));
            return div(
                { class: 'flex-row fx-gap-1' },
                Button({ type: 'icon', icon: 'edit', tooltip: 'Edit', disabled: !isSingle, onclick: () => emitEvent('EditDialogOpened', { payload: { id: selected[0]?.id } }) }),
                Button({ type: 'icon', icon: 'file_copy', tooltip: 'Copy/Move', disabled: !isSingle, onclick: () => emitEvent('CopyMoveDialogOpened', { payload: minimalSelected() }) }),
                Button({
                    type: 'icon', icon: 'delete', tooltip: 'Delete', disabled: !hasSelection,
                    onclick: () => isAll
                        ? emitEvent('DeleteAllOpened', {})
                        : emitEvent('DeleteDialogOpened', { payload: selected.map(r => ({ id: r.id })) }),
                }),
            );
        },
        // Dashed separator
        () => (canEdit.val && canDisposition.val) ? div({ class: 'td-header-separator' }) : '',
        // Disposition buttons (right group)
        () => {
            if (!canDisposition.val) return '';
            const selected = selectedRows.val;
            const isAll = selectAll.val;
            const noSelection = !isAll && !selected.length;
            const allActive = !isAll && selected.length > 0 && selected.every(r => r.test_active_display === 'Yes');
            const allInactive = !isAll && selected.length > 0 && selected.every(r => r.test_active_display === 'No');
            const allLocked = !isAll && selected.length > 0 && selected.every(r => r.lock_refresh_display === 'Yes');
            const allUnlocked = !isAll && selected.length > 0 && selected.every(r => r.lock_refresh_display === 'No');
            const emitAttribute = (attribute, value) => {
                if (isAll) {
                    emitEvent('UpdateAttributeAll', { payload: { attribute, value } });
                } else {
                    emitEvent('UpdateAttribute', { payload: { attribute, ids: selected.map(r => r.id), value } });
                }
            };
            return div(
                { class: 'flex-row fx-gap-1' },
                Button({ type: 'icon', icon: 'check_circle', tooltip: 'Activate selected', disabled: noSelection || allActive, onclick: () => emitAttribute('test_active', true) }),
                Button({ type: 'icon', icon: 'notifications_off', tooltip: 'Deactivate selected', disabled: noSelection || allInactive, onclick: () => emitAttribute('test_active', false) }),
                canEdit.val ? Button({ type: 'icon', icon: 'lock', tooltip: 'Lock selected', disabled: noSelection || allLocked, onclick: () => emitAttribute('lock_refresh', true) }) : '',
                canEdit.val ? Button({
                    type: 'icon', icon: 'lock_open', tooltip: 'Unlock selected', disabled: noSelection || allUnlocked,
                    onclick: () => isAll
                        ? emitEvent('UnlockAllOpened', {})
                        : emitEvent('UnlockDialogOpened', { payload: selected.map(r => ({ id: r.id })) }),
                }) : '',
            );
        },
        ExportMenu(props, testDefinitions),
    );

    // Build table once
    const dataTable = Table(
        {
            columns: tableColumns,
            header: tableHeader,
            highDensity: true,
            dynamicWidth: true,
            height: '40vh',
            emptyState: div(
                { class: 'flex-row fx-justify-center empty-table-message' },
                span({ class: 'text-secondary' }, 'No test definitions found matching filters'),
            ),
            sort: tableSortOptions,
            paginator: paginatorOptions,
            selection: {
                get multi() { return multiSelectMode.val; },
                onRowsSelected,
                isInitiallySelected,
            },
        },
        tableRows,
    );

    return div(
        { 'data-testid': 'test-definitions-page', class: 'flex-column fx-gap-3 td-page' },

        // --- Dialogs (mounted once at top, state persists) ---
        AddDialogComponent({
            open: addDialogOpen,
            info: addDialogInfo,
            onClose: () => {
                addDialogOpen.val = false;
                emitEvent('AddDialogClosed', {});
            },
        }),

        EditDialogComponent({
            open: editDialogOpen,
            info: editDialogInfo,
            onClose: () => {
                editDialogOpen.val = false;
                emitEvent('EditDialogClosed', {});
            },
        }),

        // Delete dialog
        Dialog(
            {
                title: 'Delete Tests',
                open: deleteDialogOpen,
                onClose: () => {
                    deleteDialogOpen.val = false;
                    emitEvent('DeleteDialogClosed', {});
                },
            },
            () => {
                const info = deleteDialogInfo.val;
                if (!info) return span();
                return div(
                    { class: 'flex-column fx-gap-4' },
                    div(info.count > 1
                        ? span('Are you sure you want to delete ', strong({}, `${info.count}`), ' selected test definitions?')
                        : span('Are you sure you want to delete the selected test definition?')
                    ),
                    div(
                        { class: 'flex-row td-dialog-actions' },
                        Button({
                            type: 'flat',
                            color: 'warn',
                            label: 'Delete',
                            onclick: () => {
                                deleteDialogOpen.val = false;
                                emitEvent('DeleteConfirmed', { payload: { ids: info.ids } });
                            },
                        }),
                    ),
                );
            },
        ),

        // Unlock dialog
        Dialog(
            {
                title: 'Unlock Test Definition',
                open: unlockDialogOpen,
                onClose: () => {
                    unlockDialogOpen.val = false;
                    emitEvent('UnlockDialogClosed', {});
                },
            },
            () => {
                const info = unlockDialogInfo.val;
                if (!info) return span();
                return div(
                    { class: 'flex-column fx-gap-4' },
                    Alert({ type: 'warning' }, 'Unlocked tests subject to auto-generation will be overwritten during the next test generation run.'),
                    div(info.count > 1
                        ? span('Are you sure you want to unlock ', strong({}, `${info.count}`), ' selected test definitions?')
                        : span('Are you sure you want to unlock the selected test definition?')
                    ),
                    div(
                        { class: 'flex-row td-dialog-actions' },
                        Button({
                            type: 'stroked',
                            color: 'basic',
                            label: 'Unlock',
                            onclick: () => {
                                unlockDialogOpen.val = false;
                                emitEvent('UnlockConfirmed', { payload: { ids: info.ids } });
                            },
                        }),
                    ),
                );
            },
        ),

        CopyMoveDialogComponent({
            open: copyMoveDialogOpen,
            info: copyMoveDialogInfo,
            onClose: () => {
                copyMoveDialogOpen.val = false;
                emitEvent('CopyMoveDialogClosed', {});
            },
        }),

        // Run tests dialog
        () => {
            const info = runTestsDialogData.val;
            if (!info) return span();
            return RunTestsDialog({
                dialog: { title: 'Run Tests', open: true },
                project_code: info.project_code,
                test_suites: info.test_suites ?? [],
                default_test_suite_id: info.default_test_suite_id,
                result: info.result,
                onClose: () => emitEvent('RunTestsDialogClosed', {}),
            });
        },

        // --- Top bar: filters + Add + Run Tests ---
        div(
            { class: 'flex-row fx-align-flex-end fx-gap-3 fx-flex-wrap' },
            () => Select({
                label: 'Table',
                value: tableFilter.val,
                options: tableFilterOptions.val,
                allowNull: true,
                width: 200,
                filterable: true,
                onChange: (value) => {
                    tableFilter.val = value;
                    if (columnFilter.val) columnFilter.val = null;
                    onFilterChange();
                },
            }),
            () => Select({
                label: 'Column',
                value: columnFilter.val,
                options: columnFilterOptions.val,
                allowNull: true,
                width: 200,
                filterable: true,
                onChange: (value) => {
                    columnFilter.val = value;
                    onFilterChange();
                },
            }),
            () => Select({
                label: 'Test Type',
                value: testTypeFilter.val,
                options: testTypeFilterOptions.val,
                allowNull: true,
                width: 200,
                filterable: true,
                onChange: (value) => {
                    testTypeFilter.val = value;
                    onFilterChange();
                },
            }),
            div({ class: 'fx-flex' }),
            () => canEdit.val
                ? Button({
                    type: 'stroked',
                    color: 'primary',
                    icon: 'add',
                    label: 'Add',
                    width: 'auto',
                    style: 'background: var(--button-generic-background-color);',
                    onclick: () => emitEvent('AddDialogOpened', {}),
                })
                : '',
            () => canEdit.val
                ? Button({
                    type: 'stroked',
                    color: 'basic',
                    icon: 'play_arrow',
                    label: 'Run Tests',
                    width: 'auto',
                    style: 'background: var(--button-generic-background-color);',
                    onclick: () => emitEvent('RunTestsClicked', {}),
                })
                : '',
        ),

        // --- Table ---
        dataTable,

        // --- Detail panel (hidden in multi-select mode) ---
        div(
            { style: () => singleSelected.val && !multiSelectMode.val ? 'margin-top: 16px' : 'display: none' },
            () => {
                const row = singleSelected.val;
                return row ? div({ class: 'tg-td--detail' }, DetailPanel(row)) : '';
            },
        ),
    );
};

// Export popover menu
const ExportMenu = (props, testDefinitions) => {
    return DropdownButton({
        icon: 'download',
        label: 'Export',
        items: [
            { label: 'All tests', onclick: () => emitEvent('ExportAll', {}) },
            {
                label: 'Filtered tests',
                onclick: () => emitEvent('ExportFiltered', { payload: { records: testDefinitions.val } }),
            },
        ],
    });
};

// Detail panel shown when a single row is selected
const DetailPanel = (row) => {
    const paramCols = row.default_parm_columns
        ? row.default_parm_columns.split(',').map(c => c.trim()).filter(Boolean)
        : [];

    return div(
        { class: 'flex-column fx-gap-3 border border-radius-1 p-4 mt-2' },
        div(
            { class: 'flex-row fx-align-flex-start fx-gap-4' },
            div(
                { class: 'flex-column fx-flex fx-gap-4' },
                Attribute({ label: 'Schema Name', value: row.schema_name }),
                Attribute({ label: 'Table Name', value: row.table_name }),
                Attribute({ label: 'Test Focus', value: row.column_name }),
                Attribute({ label: 'Test Type', value: row.test_type }),
                Attribute({ label: 'Test Active', value: row.test_active_display }),
                Attribute({ label: 'Validation Status', value: row.test_definition_status }),
                Attribute({ label: 'Lock Refresh', value: row.lock_refresh_display }),
                Attribute({ label: 'Urgency', value: row.urgency }),
                Attribute({ label: 'Export to Observability', value: row.export_to_observability_display }),
                ...paramCols.map(col => Attribute({ label: col, value: String(row[col] ?? '') })),
            ),
            div(
                { class: 'flex-column fx-flex fx-gap-3' },
                row.default_test_description
                    ? div({ class: 'text-caption', innerHTML: row.default_test_description })
                    : null,
                row.usage_notes
                    ? Alert({ type: 'info' }, strong({ class: 'mb-1' }, 'Usage Notes'), div({}, row.usage_notes))
                    : null,
            ),
        ),
    );
};

// Add dialog — mounted once, state persists across Python reruns
const AddDialogComponent = ({ open, info, onClose }) => {
    const testTypes = van.derive(() => getValue(info)?.test_types ?? []);
    const tableGroupSchema = van.derive(() => getValue(info)?.table_group_schema ?? '');
    const tableGroupsId = van.derive(() => getValue(info)?.table_groups_id ?? '');
    const testSuite = van.derive(() => getValue(info)?.test_suite ?? {});
    const tableColumns = van.derive(() => getValue(info)?.table_columns ?? []);
    const validateResult = van.derive(() => getValue(info)?.validate_result ?? null);

    const scopeFilter = {
        referential: van.state(true),
        table: van.state(true),
        column: van.state(true),
        custom: van.state(true),
    };

    const filteredTestTypeOptions = van.derive(() =>
        testTypes.val
            .filter(tt => tt.test_scope !== 'tablegroup' && (scopeFilter[tt.test_scope]?.val ?? true))
            .map(tt => ({ label: tt.select_name ?? tt.test_name_short, value: tt.test_type }))
    );

    const selectedTestType = van.state(null);
    const selectedTestTypeRow = van.derive(() =>
        selectedTestType.val ? testTypes.val.find(tt => tt.test_type === selectedTestType.val) ?? null : null
    );

    // Build blank form values when a test type is chosen
    const formValues = van.state(null);
    van.derive(() => {
        const tt = selectedTestTypeRow.val;
        if (!tt) { formValues.val = null; return; }
        formValues.val = {
            ...BLANK_PARAM_FIELDS,
            ...tt,
            default_test_description: tt.test_description,
            test_description: null,
            test_active: true,
            lock_refresh: false,
            severity: null,
            export_to_observability: null,
            schema_name: tableGroupSchema.val,
            test_suite_id: testSuite.val.id,
            table_groups_id: tableGroupsId.val,
            table_name: null,
            column_name: null,
            skip_errors: 0,
            test_definition_status: null,
            last_auto_gen_date: null,
            profiling_as_of_date: null,
            profile_run_id: null,
        };
    });

    // Reset form state when dialog opens (transitions from closed→open)
    const wasOpen = van.state(false);
    van.derive(() => {
        const isOpen = open.val;
        if (isOpen && !wasOpen.val) {
            selectedTestType.val = null;
            wasOpen.val = true;
        } else if (!isOpen) {
            wasOpen.val = false;
        }
    });

    return Dialog(
        { title: 'Add Test', open, onClose, width: '52rem' },
        div(
            { class: 'flex-column fx-gap-4 td-form-dialog' },

            // Test type picker — always visible
            div(
                { class: 'flex-column fx-gap-3' },
                div(
                    { class: 'flex-row fx-gap-4 fx-align-flex-center fx-flex-wrap' },
                    span({ class: 'text-caption' }, 'Show Types:'),
                    ...Object.entries(SCOPE_LABELS).map(([scope, scopeLabel]) =>
                        Checkbox({
                            label: scopeLabel,
                            checked: scopeFilter[scope],
                            onChange: (v) => { scopeFilter[scope].val = v; },
                        })
                    ),
                ),
                () => Select({
                    label: 'Test Type',
                    value: selectedTestType.val,
                    options: filteredTestTypeOptions.val,
                    allowNull: true,
                    filterable: true,
                    onChange: (value) => { selectedTestType.val = value; },
                }),
            ),

            // Form (shown after test type selected)
            () => {
                const fv = formValues.val;
                if (!fv) return span();
                return TestDefFormContent({
                    formValues: fv,
                    tableColumns: tableColumns.val,
                    testSuite: testSuite.val,
                    validateResult: validateResult.val,
                    mode: 'add',
                    onFormChange: (changes) => {
                        formValues.val = { ...formValues.rawVal, ...changes };
                    },
                    onValidate: () => emitEvent('ValidateTest', { payload: formValues.rawVal }),
                    onSave: () => emitEvent('AddTestSaved', { payload: formValues.rawVal }),
                    onCancel: onClose,
                });
            },
        ),
    );
};

// Edit dialog — mounted once, state persists across Python reruns
const EditDialogComponent = ({ open, info, onClose }) => {
    const dialogInfo = van.derive(() => getValue(info) ?? null);
    const testTypes = van.derive(() => dialogInfo.val?.test_types ?? []);
    const tableColumns = van.derive(() => dialogInfo.val?.table_columns ?? []);
    const testSuite = van.derive(() => dialogInfo.val?.test_suite ?? {});
    const validateResult = van.derive(() => dialogInfo.val?.validate_result ?? null);

    // Build formValues when dialog info changes (new definition to edit)
    const formValues = van.state(null);
    van.derive(() => {
        const di = dialogInfo.val;
        if (!di?.test_definition) { formValues.val = null; return; }
        const def = di.test_definition;
        const ttRow = (di.test_types ?? []).find(tt => tt.test_type === def.test_type) ?? {};
        formValues.val = {
            ...def,
            run_type: ttRow.run_type ?? def.run_type ?? 'CAT',
            column_name_prompt: ttRow.column_name_prompt ?? null,
            column_name_help: ttRow.column_name_help ?? null,
        };
    });

    return Dialog(
        { title: 'Edit Test', open, onClose, width: '52rem' },
        () => {
            const fv = formValues.val;
            if (!fv) return span();
            return div(
                { class: 'flex-column fx-gap-4 td-form-dialog' },
                TestDefFormContent({
                    formValues: fv,
                    tableColumns: tableColumns.val,
                    testSuite: testSuite.val,
                    validateResult: validateResult.val,
                    mode: 'edit',
                    onFormChange: (changes) => {
                        formValues.val = { ...formValues.rawVal, ...changes };
                    },
                    onValidate: () => emitEvent('ValidateTest', { payload: formValues.rawVal }),
                    onSave: () => emitEvent('EditTestSaved', { payload: formValues.rawVal }),
                    onCancel: onClose,
                }),
            );
        },
    );
};

// Shared form content for add/edit dialogs
const TestDefFormContent = ({ formValues, tableColumns, testSuite, validateResult, mode, onFormChange, onValidate, onSave, onCancel }) => {
    const testScope = formValues.test_scope ?? 'column';
    const runType = formValues.run_type ?? 'CAT';
    const testType = formValues.test_type ?? '';
    const isValidatable = testType === 'Condition_Flag' || testType === 'CUSTOM';

    const fv = van.state({ ...formValues });
    const updateField = (key, value) => {
        const updated = { ...fv.rawVal, [key]: value };
        fv.val = updated;
        onFormChange({ [key]: value });
    };

    const inheritedSeverity = testSuite.severity ?? formValues.default_severity ?? 'Warning';
    const severityOptions = [
        { label: `Inherited (${inheritedSeverity})`, value: null },
        ...SEVERITY_OPTIONS,
    ];

    const inheritedObs = testSuite.export_to_observability ? 'Yes' : 'No';
    const obsOptions = [
        { label: `Inherited (${inheritedObs})`, value: null },
        { label: 'Yes', value: true },
        { label: 'No', value: false },
    ];

    const tableNameOptions = [
        ...new Set((tableColumns ?? []).map(c => c.table_name).filter(Boolean))
    ].sort((a, b) => a.localeCompare(b)).map(t => ({ label: t, value: t }));

    const columnNameOptions = van.derive(() => {
        const selectedTable = fv.val.table_name;
        const cols = selectedTable
            ? (tableColumns ?? []).filter(c => c.table_name === selectedTable).map(c => c.column_name)
            : (tableColumns ?? []).map(c => c.column_name);
        return [...new Set(cols.filter(Boolean))].sort().map(c => ({ label: c, value: c }));
    });

    const columnLabel = formValues.column_name_prompt || (testScope === 'column' ? 'Column' : 'Test Focus');
    const columnHelp = formValues.column_name_help ?? null;

    return div(
        { class: 'flex-column fx-gap-3' },

        // Test type header (add mode) or read-only test type (edit mode)
        mode === 'add' && formValues.test_name_short
            ? div(
                { class: 'mb-1' },
                div({ class: 'text-large' }, formValues.test_name_short),
                formValues.default_test_description
                    ? div({ class: 'text-caption mt-1', innerHTML: formValues.default_test_description })
                    : null,
            )
            : null,

        mode === 'edit'
            ? Input({
                name: 'test_type_display',
                label: 'Test Type',
                value: formValues.test_name_short ?? formValues.test_type ?? '',
                disabled: true,
            })
            : null,

        formValues.usage_notes
            ? Alert({ type: 'info' }, strong({ class: 'mb-1' }, 'Usage Notes'), div({}, formValues.usage_notes))
            : null,

        // Description override
        Textarea({
            name: 'test_description',
            label: 'Test Description Override',
            value: () => fv.val.test_description ?? '',
            placeholder: `Inherited (${formValues.default_test_description ?? ''})`,
            height: 72,
            onChange: (value) => updateField('test_description', value || null),
        }),

        // Toggles
        div(
            { class: 'flex-row fx-gap-4' },
            Toggle({
                label: 'Test Active',
                checked: () => fv.val.test_active ?? true,
                onChange: (v) => updateField('test_active', v),
            }),
            Toggle({
                label: 'Lock Refresh',
                checked: () => fv.val.lock_refresh ?? false,
                onChange: (v) => updateField('lock_refresh', v),
            }),
        ),

        // Severity + Observability selects
        div(
            { class: 'flex-row fx-gap-3 fx-flex-wrap' },
            div(
                { style: 'flex: calc(50% - 8px) 0 0;' },
                () => Select({
                    label: 'Urgency Override',
                    value: fv.val.severity ?? null,
                    options: severityOptions,
                    allowNull: false,
                    onChange: (value) => updateField('severity', value),
                }),
            ),
            div(
                { style: 'flex: calc(50% - 8px) 0 0;' },
                () => Select({
                    label: 'Send to Observability - Override',
                    value: fv.val.export_to_observability ?? null,
                    options: obsOptions,
                    allowNull: false,
                    onChange: (value) => updateField('export_to_observability', value),
                }),
            ),
        ),

        // Schema (read-only)
        Input({
            name: 'schema_name',
            label: 'Schema',
            value: formValues.schema_name ?? '',
            disabled: true,
        }),

        // Table name
        testScope !== 'tablegroup'
            ? testScope === 'custom'
                ? Input({
                    name: 'table_name',
                    label: 'Table',
                    value: () => fv.val.table_name ?? '',
                    onChange: (value) => updateField('table_name', value || null),
                })
                : () => Select({
                    label: 'Table',
                    value: fv.val.table_name ?? null,
                    options: tableNameOptions,
                    allowNull: true,
                    filterable: true,
                    disabled: mode === 'edit',
                    onChange: (value) => {
                        updateField('table_name', value);
                        updateField('column_name', null);
                    },
                })
            : null,

        // Column name (scope-dependent)
        testScope === 'column'
            ? () => Select({
                label: 'Column',
                value: fv.val.column_name ?? null,
                options: columnNameOptions.val,
                allowNull: true,
                filterable: true,
                onChange: (value) => updateField('column_name', value),
            })
            : testScope === 'referential' || testScope === 'custom'
                ? Input({
                    name: 'column_name',
                    label: columnLabel,
                    help: columnHelp,
                    value: () => fv.val.column_name ?? '',
                    onChange: (value) => updateField('column_name', value || null),
                })
                : null,

        // Validation status (edit mode only)
        mode === 'edit' && formValues.test_definition_status
            ? Input({
                name: 'test_definition_status',
                label: 'Validation Status',
                value: formValues.test_definition_status || 'OK',
                disabled: true,
            })
            : null,

        // Dynamic parameter fields
        div(
            { class: 'td-form-params-section' },
            TestDefinitionForm({
                definition: () => fv.val,
                onChange: (changes) => {
                    const updated = { ...fv.rawVal, ...changes };
                    fv.val = updated;
                    onFormChange(changes);
                },
            }),
        ),

        // Skip errors (QUERY run type only)
        runType === 'QUERY'
            ? Input({
                name: 'skip_errors',
                label: 'Threshold Error Count',
                type: 'number',
                value: () => fv.val.skip_errors ?? 0,
                step: 1,
                onChange: (value) => updateField('skip_errors', value ?? 0),
            })
            : null,

        // Validate feedback
        validateResult
            ? Alert({ type: validateResult.success ? 'success' : 'error' }, validateResult.message)
            : null,

        // Buttons
        div(
            { class: 'flex-row fx-justify-space-between td-dialog-actions' },
            isValidatable
                ? Button({
                    type: 'stroked',
                    color: 'basic',
                    label: 'Validate',
                    onclick: onValidate,
                })
                : null,
            Button({
                type: 'stroked',
                color: 'basic',
                label: 'Cancel',
                width: 'auto',
                onclick: onCancel,
            }),
            Button({
                type: 'flat',
                color: 'primary',
                label: 'Save',
                width: 'auto',
                onclick: onSave,
            }),
        ),
    );
};

// Copy/Move dialog — mounted once
const CopyMoveDialogComponent = ({ open, info, onClose }) => {
    const dialogInfo = van.derive(() => getValue(info) ?? null);
    const collision = van.derive(() => dialogInfo.val?.collision ?? null);

    const targetTgId = van.state(null);
    const targetTsId = van.state(null);
    const targetTableName = van.state(null);
    const targetColumnName = van.state(null);

    // Reset when dialog opens
    const wasOpen = van.state(false);
    van.derive(() => {
        const isOpen = open.val;
        if (isOpen && !wasOpen.val) {
            const di = dialogInfo.val;
            targetTgId.val = di?.current_table_group_id ?? null;
            targetTsId.val = null;
            targetTableName.val = null;
            targetColumnName.val = null;
            wasOpen.val = true;
        } else if (!isOpen) {
            wasOpen.val = false;
        }
    });

    const tableGroupOptions = van.derive(() =>
        (dialogInfo.val?.table_groups ?? []).map(tg => ({ label: tg.table_groups_name, value: tg.id }))
    );

    const testSuiteOptions = van.derive(() => {
        const tg = targetTgId.val;
        const suites = dialogInfo.val?.test_suites_by_table_group?.[tg] ?? [];
        return suites.map(ts => ({ label: ts.test_suite, value: ts.id }));
    });

    const isSameSuite = van.derive(() =>
        !!targetTsId.val &&
        targetTgId.val === dialogInfo.val?.current_table_group_id &&
        targetTsId.val === dialogInfo.val?.current_test_suite_id
    );

    const tableOptions = van.derive(() => {
        const cols = dialogInfo.val?.filter_columns ?? [];
        return [...new Set(cols.map(c => c.table_name).filter(Boolean))].sort()
            .map(t => ({ label: t, value: t }));
    });

    const columnOptions = van.derive(() => {
        const cols = dialogInfo.val?.filter_columns ?? [];
        const table = targetTableName.val;
        const filtered = table ? cols.filter(c => c.table_name === table) : [];
        return [...new Set(filtered.map(c => c.column_name).filter(Boolean))].sort()
            .map(c => ({ label: c, value: c }));
    });

    // Emit target-changed for collision check
    van.derive(() => {
        const tgId = targetTgId.val;
        const tsId = targetTsId.val;
        const di = dialogInfo.val;
        if (tgId && tsId && di?.selected) {
            emitEvent('CopyMoveTargetChanged', {
                payload: {
                    selected: di.selected,
                    target_table_group_id: tgId,
                    target_test_suite_id: tsId,
                },
            });
        }
    });

    // Determine movable IDs (excluding locked collision matches)
    const movableIds = van.derive(() => {
        const di = dialogInfo.val;
        const selected = di?.selected ?? [];
        const col = collision.val;
        if (col === null || !targetTsId.val) return selected.map(s => s.id);
        const lockedKeys = new Set(
            (col ?? [])
                .filter(c => c.lock_refresh)
                .map(c => `${c.table_name}|${c.column_name}|${c.test_type}`)
        );
        return selected
            .filter(s => !lockedKeys.has(`${s.table_name}|${s.column_name}|${s.test_type}`))
            .map(s => s.id);
    });

    const buildPayload = () => ({
        ids: movableIds.rawVal,
        target_table_group_id: targetTgId.rawVal,
        target_test_suite_id: targetTsId.rawVal,
        target_table_name: targetTableName.rawVal || null,
        target_column_name: targetColumnName.rawVal || null,
    });

    return Dialog(
        { title: 'Copy/Move Tests', open, onClose, width: '42rem' },
        div(
            { class: 'flex-column fx-gap-4 td-form-dialog' },
            () => div({ class: 'text-caption' }, `Selected tests: ${(dialogInfo.val?.selected ?? []).length}`),

            () => Select({
                label: 'Target Table Group',
                value: targetTgId.val,
                options: tableGroupOptions.val,
                required: true,
                filterable: true,
                onChange: (value) => {
                    targetTgId.val = value;
                    targetTsId.val = null;
                },
            }),

            () => Select({
                label: 'Target Test Suite',
                value: targetTsId.val,
                options: testSuiteOptions.val,
                required: true,
                allowNull: true,
                filterable: true,
                onChange: (value) => { targetTsId.val = value; },
            }),

            // Same-suite copy: show table/column selects
            () => isSameSuite.val
                ? div(
                    { class: 'flex-column fx-gap-3' },
                    () => Select({
                        label: 'Target Table Name',
                        value: targetTableName.val,
                        options: tableOptions.val,
                        required: true,
                        allowNull: true,
                        filterable: true,
                        onChange: (value) => {
                            targetTableName.val = value;
                            targetColumnName.val = null;
                        },
                    }),
                    () => Select({
                        label: 'Column Name',
                        value: targetColumnName.val,
                        options: columnOptions.val,
                        required: true,
                        allowNull: true,
                        disabled: !targetTableName.val,
                        filterable: true,
                        onChange: (value) => { targetColumnName.val = value; },
                    }),
                )
                : span(),

            // Collision warning
            () => {
                const col = collision.val;
                if (!col || !col.length || !targetTsId.val) return span();
                const unlocked = col.filter(c => !c.lock_refresh);
                const locked = col.filter(c => c.lock_refresh);
                return Alert(
                    { type: 'warning' },
                    div({}, 'Auto-generated tests exist in the target suite for the same column-test type combinations.'),
                    div({ class: 'mt-1' }, `Unlocked tests that will be overwritten: ${unlocked.length}`),
                    div({}, `Locked tests that will not be overwritten: ${locked.length}`),
                );
            },

            div(
                { class: 'flex-row fx-gap-2 td-dialog-actions' },
                () => Button({
                    type: 'stroked',
                    color: 'basic',
                    label: 'Copy',
                    disabled: !movableIds.val.length || !targetTsId.val,
                    onclick: () => emitEvent('CopyConfirmed', { payload: buildPayload() }),
                }),
                () => Button({
                    type: 'flat',
                    color: 'primary',
                    label: 'Move',
                    disabled: !movableIds.val.length || !targetTsId.val,
                    onclick: () => emitEvent('MoveConfirmed', { payload: buildPayload() }),
                }),
            ),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.td-page {
    width: 100%;
    min-height: 500px;
}

.tg-td--detail {
    border-top: 1px solid var(--border-color, #dddfe2);
    padding-top: 16px;
}

.td-header-separator {
    width: 1px;
    height: 24px;
    border-left: 1px dashed var(--border-color, #dddfe2);
    margin: 0 4px;
}

.td-form-dialog {
    max-height: 70vh;
    overflow-y: auto;
    padding-right: 4px;
}

.td-form-params-section {
    border-top: 1px solid var(--border-color);
    padding-top: 12px;
    margin-top: 4px;
}


.td-dialog-actions {
    justify-content: flex-end;
    gap: 8px;
}
`);

export { TestDefinitions, EditDialogComponent };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    Streamlit.enableV2(setTriggerValue);

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, TestDefinitions(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
