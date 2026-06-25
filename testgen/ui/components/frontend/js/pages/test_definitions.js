import van from '/app/static/js/van.min.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
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
import { TestDefinitionNotes } from './test_definition_notes.js';
import { withTooltip } from '/app/static/js/components/tooltip.js';
import { Icon } from '/app/static/js/components/icon.js';
import { ProfilingResultsDialog } from '../shared/profiling_results_dialog.js';
import { AXES, FACET_AXES, GROUP_BY_AXES, EMPTY, appliesToSelectedColumn } from '/app/static/js/components/test_picker_taxonomy.js';
import { enterPage, exitPage, getPageSignal } from '/app/static/js/page_lifecycle.js';

const { button: btn, div, i: icon, span, strong } = van.tags;

const PAGE_KEY = 'testDefinitions';

const TABLE_COLUMNS = [
    { name: 'table_name', label: 'Table', width: 180, sortable: true, overflow: 'hidden' },
    { name: 'column_name', label: 'Column / Focus', width: 180, sortable: true, overflow: 'hidden' },
    { name: 'test_name_short', label: 'Test Type', width: 160, sortable: true, overflow: 'hidden' },
    { name: 'test_active_display', label: 'Active', width: 80, align: 'center' },
    { name: 'lock_refresh_display', label: 'Locked', width: 80, align: 'center' },
    { name: 'urgency', label: 'Urgency', width: 100 },
    { name: 'flagged_display', label: 'Flagged', width: 80, align: 'center' },
    { name: 'notes_count', label: 'Notes', width: 70, align: 'center' },
    { name: 'profiling_as_of_date', label: 'Based on Profiling', width: 160 },
    { name: 'last_manual_update', label: 'Last Manual Update', width: 160 },
    { name: 'export_to_observability_display', label: 'Observability', width: 120 },
];

const SEVERITY_OPTIONS = [
    { label: 'Log', value: 'Log' },
    { label: 'Warning', value: 'Warning' },
    { label: 'Fail', value: 'Fail' },
];

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

/** Composite icon button: flag with a diagonal strikethrough (pen_size_1 rotated). */
const ClearFlagButton = ({ disabled, onclick }) => {
    return withTooltip(btn(
        {
            'data-testid': 'button',
            class: 'tg-button tg-icon-button tg-basic-button',
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

const TestDefinitions = (/** @type object */ props) => {
    const { emit } = props;
    loadStylesheet('test-definitions', stylesheet);

    // Notes dialog: persistent local state + one-time sync from Python prop
    const notesDialogOpen = van.state(false);
    van.derive(() => { if (getValue(props.notes_dialog)) notesDialogOpen.val = true; });

    const permissions = van.derive(() => getValue(props.permissions) ?? {});
    const canEdit = van.derive(() => getValue(permissions).can_edit ?? false);
    const canDisposition = van.derive(() => getValue(permissions).can_disposition ?? false);

    const filterOptions = van.derive(() => getValue(props.filter_options) ?? { tables: [], columns: [], test_types: [] });
    const currentFilters = van.derive(() => getValue(props.current_filters) ?? {});

    const tableFilter = van.state(null);
    const columnFilter = van.state(null);
    const testTypeFilter = van.state(null);
    const flaggedFilter = van.state(null);

    // Initialize filters from Python query params (runs once on mount)
    const filtersInitialized = van.state(false);
    van.derive(() => {
        if (filtersInitialized.val) return;
        const cf = currentFilters.val;
        tableFilter.val = cf.table_name ?? null;
        columnFilter.val = cf.column_name ?? null;
        testTypeFilter.val = cf.test_type ?? null;
        flaggedFilter.val = cf.flagged ?? null;
        filtersInitialized.val = true;
    });

    const columnFilterOptions = van.derive(() => {
        const cols = filterOptions.val.columns ?? [];
        const table = tableFilter.val;
        let filtered;
        if (!table) {
            filtered = cols;
        } else if (table.startsWith('%') && table.endsWith('%')) {
            const partial = table.slice(1, -1).toLowerCase();
            filtered = cols.filter(c => c.table_name.toLowerCase().includes(partial));
        } else {
            filtered = cols.filter(c => c.table_name === table);
        }
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

    const onFilterChange = () => emit('FilterChanged', {
        payload: {
            table_name: tableFilter.val || null,
            column_name: columnFilter.val || null,
            test_type: testTypeFilter.val || null,
            flagged: flaggedFilter.val || null,
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
        selectedIdsCount.val = 0;
    };

    let selectedIds = [];
    const selectedIdSetForRestore = new Set();
    const getSelectedDefinitionIds = () => {
        if (multiSelectMode.val) return [...selectedIdSetForRestore];
        return selectedRowId.val ? [selectedRowId.val] : [];
    };

    // Reactive selection count for button enable/disable
    const selectedIdsCount = van.state(0);

    const onSelectAllToggle = (checked) => {
        if (checked) {
            selectAll.val = true;
            for (const item of testDefinitions.rawVal) {
                const state = getCheckboxState(item.id);
                state.val = true;
                selectedIdSetForRestore.add(item.id);
            }
            selectedIds = [...selectedIdSetForRestore];
            selectedIdsCount.val = selectedIds.length;
        } else {
            clearAllCheckboxStates();
            selectedIds = [];
            selectedIdSetForRestore.clear();
        }
    };

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
    const tableColumns = van.derive(() => multiSelectMode.val ? [checkboxColumn, ...TABLE_COLUMNS] : TABLE_COLUMNS);

    // Clear checkbox states and selection when toggling multi-select off
    van.derive(() => {
        if (!multiSelectMode.val) {
            clearAllCheckboxStates();
            selectedIds = [];
            selectedIdsCount.val = 0;
            selectedIdSetForRestore.clear();
        }
    });

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

    van.derive(() => { addDialogOpen.val = !!addDialogInfo.val?.open; });
    van.derive(() => { editDialogOpen.val = !!editDialogInfo.val?.open; });
    van.derive(() => { deleteDialogOpen.val = !!deleteDialogInfo.val?.open; });
    van.derive(() => { unlockDialogOpen.val = !!unlockDialogInfo.val?.open; });
    van.derive(() => { copyMoveDialogOpen.val = !!copyMoveDialogInfo.val?.open; });

    const runTestsDialogData = van.derive(() => getValue(props.run_tests_dialog) ?? null);

    // Table rows built from items (already filtered/sorted/paginated by server)
    const tableRows = van.derive(() => {
        const isMulti = multiSelectMode.val;
        const isSelectAll = selectAll.val;
        const currentItems = testDefinitions.val;

        // When selectAll is active, sync tracking state to current page items
        if (isMulti && isSelectAll) {
            for (const item of currentItems) {
                const state = getCheckboxState(item.id);
                state.val = true;
                selectedIdSetForRestore.add(item.id);
            }
            selectedIds = [...selectedIdSetForRestore];
            selectedIdsCount.val = selectedIds.length;
        }

        return currentItems.map(item => {
            const row = {
                ...item,
                test_active: item.test_active_display?.toLowerCase() === 'yes', // flag to apply row style
                test_active_display: item.test_active_display?.toLowerCase() === 'yes'
                    ? Icon({classes: 'text-green display-table-cell'}, 'check_circle')
                    : Icon({classes: 'text-disabled display-table-cell'}, 'notifications_off'),
                lock_refresh_display: item.lock_refresh_display?.toLowerCase() === 'yes'
                    ? Icon({classes: 'text-purple display-table-cell'}, 'lock')
                    : '',
                flagged_display: item.flagged_display?.toLowerCase() === 'yes'
                    ? Icon({classes: 'text-error display-table-cell', filled: true}, 'flag')
                    : '',
                notes_count: item.notes_count ? div(
                    {class: 'flex-row fx-justify-center'},
                    Icon({}, 'sticky_note_2'),
                    span(item.notes_count),
                ) : '',
            };
            if (isMulti) {
                const checked = getCheckboxState(item.id);
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

    const isInitiallySelected = (row, _) => {
        if (multiSelectMode.rawVal) return selectedIdSetForRestore.has(row.id);
        return row.id === selectedRowId.rawVal;
    };

    const onRowsSelected = (idxs) => {
        if (multiSelectMode.rawVal) {
            const currentPageItemIds = new Set(testDefinitions.rawVal.map(r => r.id));
            const activeSet = new Set();
            for (const i of idxs) {
                const item = testDefinitions.rawVal[i];
                if (item) activeSet.add(item.id);
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
            if (newPerPage !== pageSize.rawVal) {
                if (!selectAll.rawVal) {
                    clearAllCheckboxStates();
                    selectedIds = [];
                    selectedIdsCount.val = 0;
                    selectedIdSetForRestore.clear();
                }
                emit('PageChanged', { payload: { page: 0, page_size: newPerPage } });
            } else {
                emit('PageChanged', { payload: { page: pageIdx } });
            }
        },
    }));

    // Table header bar: multi-select toggle + edit buttons | dashed separator | disposition buttons + export
    const tableHeader = div(
        { 'data-testid': 'table-header', class: 'flex-row fx-align-center fx-gap-2 p-2 fx-flex-wrap' },
        () => canDisposition.val
            ? Toggle({
                label: () => {
                    return div(
                        { class: 'flex-column' },
                        span('Multi-Select'),
                        () => {
                            if (!multiSelectMode.val) return '';
                            if (selectAll.val) return span({ class: 'text-caption' }, () => `All ${totalCount.val} matching definitions selected`);
                            const count = selectedIdsCount.val;
                            if (count > 0) return span({ class: 'text-caption' }, `${count} definition${count !== 1 ? 's' : ''} selected`);
                            return '';
                        },
                    );
                },
                checked: () => multiSelectMode.val,
                onChange: (v) => { multiSelectMode.val = v; },
            })
            : '',
        div({ class: 'fx-flex' }),
        // Edit buttons (left group)
        () => {
            if (!canEdit.val) return '';
            const selected = selectedRows.val;
            const isAll = selectAll.val;
            const count = selectedIdsCount.val;
            const hasSelection = isAll || (multiSelectMode.val ? count > 0 : selected.length > 0);
            const isSingle = !isAll && selected.length === 1;
            // Only send minimal fields to avoid serialization issues
            const minimalSelected = () => selected.map(r => ({
                id: r.id, table_name: r.table_name, column_name: r.column_name,
                test_type: r.test_type, lock_refresh: r.lock_refresh,
            }));
            return div(
                { 'data-testid': 'edit-actions', class: 'flex-row fx-gap-1' },
                Button({ type: 'icon', icon: 'file_copy', tooltip: 'Copy/Move', disabled: !hasSelection, onclick: () => emit('CopyMoveDialogOpened', { payload: isAll ? 'all' : minimalSelected() }) }),
                Button({
                    type: 'icon', icon: 'delete', tooltip: 'Delete', disabled: !hasSelection,
                    onclick: () => isAll
                        ? emit('DeleteAllOpened', {})
                        : emit('DeleteDialogOpened', { payload: getSelectedDefinitionIds().map(id => ({ id })) }),
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
            const count = selectedIdsCount.val;
            // Use cross-page count in multi-select; current-page items in single-select
            const noSelection = multiSelectMode.val ? !isAll && count === 0 : !selected.length;
            // Skip per-item attribute checks in multi-select (can't see all pages)
            const allActive = !multiSelectMode.val && selected.length > 0 && selected.every(r => r.test_active_display === 'Yes');
            const allInactive = !multiSelectMode.val && selected.length > 0 && selected.every(r => r.test_active_display === 'No');
            const allLocked = !multiSelectMode.val && selected.length > 0 && selected.every(r => r.lock_refresh_display === 'Yes');
            const allUnlocked = !multiSelectMode.val && selected.length > 0 && selected.every(r => r.lock_refresh_display === 'No');
            const emitAttribute = (attribute, value) => {
                if (isAll) {
                    emit('UpdateAttributeAll', { payload: { attribute, value } });
                } else {
                    emit('UpdateAttribute', { payload: { attribute, ids: getSelectedDefinitionIds(), value } });
                }
            };
            return div(
                { 'data-testid': 'disposition-actions', class: 'flex-row fx-gap-1' },
                Button({ type: 'icon', icon: 'check_circle', tooltip: 'Activate selected', disabled: noSelection || allActive, onclick: () => emitAttribute('test_active', true) }),
                Button({ type: 'icon', icon: 'notifications_off', tooltip: 'Deactivate selected', disabled: noSelection || allInactive, onclick: () => emitAttribute('test_active', false) }),
                div({ class: 'td-header-separator' }),
                canEdit.val ? Button({ type: 'icon', icon: 'lock', tooltip: 'Lock selected', disabled: noSelection || allLocked, onclick: () => emitAttribute('lock_refresh', true) }) : '',
                canEdit.val ? Button({
                    type: 'icon', icon: 'lock_open', tooltip: 'Unlock selected', disabled: noSelection || allUnlocked,
                    onclick: () => isAll
                        ? emit('UnlockAllOpened', {})
                        : emit('UnlockDialogOpened', { payload: getSelectedDefinitionIds().map(id => ({ id })) }),
                }) : '',
                canEdit.val ? div({ class: 'td-header-separator' }) : '',
                Button({
                    type: 'icon', icon: 'flag', tooltip: 'Flag selected',
                    disabled: noSelection || (!multiSelectMode.val && selected.length > 0 && selected.every(r => r.flagged)),
                    onclick: () => emitAttribute('flagged', true),
                }),
                ClearFlagButton({
                    disabled: noSelection || (!multiSelectMode.val && selected.length > 0 && selected.every(r => !r.flagged)),
                    onclick: () => emitAttribute('flagged', false),
                }),
            );
        },
        ExportMenu(
            props,
            testDefinitions,
            () => selectedRowId.val || selectedIdsCount.val > 0,
            getSelectedDefinitionIds,
        ),
    );

    // Build table once
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
                span({ class: 'text-secondary' }, 'No test definitions found matching filters'),
            ),
            sort: tableSortOptions,
            paginator: paginatorOptions,
            selection: {
                get multi() { return multiSelectMode.val; },
                onRowsSelected,
                isInitiallySelected,
            },
            rowClass: (row, _) => !row.test_active ? 'text-disabled' : '',
        },
        tableRows,
    );

    return div(
        { 'data-testid': 'test-definitions-page', class: 'flex-column fx-gap-3 td-page' },

        // --- Dialogs (mounted once at top, state persists) ---
        AddDialogComponent({
            open: addDialogOpen,
            info: addDialogInfo,
            validateResult: props.validate_result,
            onClose: () => {
                addDialogOpen.val = false;
                emit('AddDialogClosed', {});
            },
        }, emit),

        EditDialogComponent({
            open: editDialogOpen,
            info: editDialogInfo,
            validateResult: props.validate_result,
            onClose: () => {
                editDialogOpen.val = false;
                emit('EditDialogClosed', {});
            },
        }, emit),

        // Delete dialog
        Dialog(
            {
                title: 'Delete Tests',
                open: deleteDialogOpen,
                onClose: () => {
                    deleteDialogOpen.val = false;
                    emit('DeleteDialogClosed', {});
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
                        { class: 'flex-row fx-justify-flex-end fx-gap-2' },
                        Button({
                            type: 'flat',
                            color: 'warn',
                            label: 'Delete',
                            width: 'auto',
                            style: 'margin-left: auto;',
                            onclick: () => {
                                deleteDialogOpen.val = false;
                                emit('DeleteConfirmed', { payload: { ids: info.ids } });
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
                    emit('UnlockDialogClosed', {});
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
                        { class: 'flex-row fx-justify-flex-end fx-gap-2' },
                        Button({
                            type: 'stroked',
                            color: 'basic',
                            label: 'Unlock',
                            width: 'auto',
                            style: 'margin-left: auto;',
                            onclick: () => {
                                unlockDialogOpen.val = false;
                                emit('UnlockConfirmed', { payload: { ids: info.ids } });
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
                emit('CopyMoveDialogClosed', {});
            },
        }, emit),

        // Run tests dialog
        () => {
            const info = runTestsDialogData.val;
            if (!info) return span();
            return RunTestsDialog({ emit,
                dialog: { title: 'Run Tests', open: true },
                project_code: info.project_code,
                test_suites: info.test_suites ?? [],
                default_test_suite_id: info.default_test_suite_id,
                result: info.result,
                onClose: () => emit('RunTestsDialogClosed', {}),
            });
        },

        // Profiling results dialog
        ProfilingResultsDialog({ emit,
            profilingColumn: van.derive(() => getValue(props.profiling_column) ?? null),
            onClose: () => emit('ProfilingClosed', {}),
        }),

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
                acceptNewOptions: true,
                onChange: (value, meta) => {
                    columnFilter.val = meta?.isCustom ? `%${value}%` : value;
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
            () => Select({
                label: 'Flagged',
                value: flaggedFilter.val,
                options: [
                    { label: 'Flagged', value: 'Flagged' },
                    { label: 'Not Flagged', value: 'Not Flagged' },
                ],
                allowNull: true,
                onChange: (value) => {
                    flaggedFilter.val = value;
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
                    onclick: () => emit('AddDialogOpened', {}),
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
                    onclick: () => emit('RunTestsClicked', {}),
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
                if (!row) return '';
                return div(
                    { 'data-testid': 'test-definition-detail', class: 'tg-td--detail flex-column fx-gap-4' },
                    div(
                        { class: 'flex-row fx-gap-2 fx-justify-content-flex-end' },
                        canEdit.val ? Button({
                            type: 'stroked', icon: 'edit', label: 'Edit', width: 'auto',
                            style: 'background: var(--button-generic-background-color);',
                            onclick: () => emit('EditDialogOpened', { payload: { id: row.id } }),
                        }) : '',
                        canEdit.val ? Button({
                            type: 'stroked', icon: 'sticky_note_2', label: 'Notes', width: 'auto',
                            style: 'background: var(--button-generic-background-color);',
                            onclick: () => emit('NotesClicked', { payload: { id: row.id, table_name: row.table_name, column_name: row.column_name, test_name_short: row.test_name_short } }),
                        }) : '',
                        row.column_name ? Button({
                            type: 'stroked', icon: 'query_stats', label: 'Profiling', width: 'auto',
                            style: 'background: var(--button-generic-background-color);',
                            onclick: () => emit('ProfilingClicked', { payload: { table_name: row.table_name, column_name: row.column_name, table_groups_id: row.table_groups_id } }),
                        }) : '',
                    ),
                    DetailPanel(row),
                );
            },
        ),
    );
};

// Export popover menu
const ExportMenu = (props, testDefinitions, hasSelection, getSelectedIds) => {
    const emit = props.emit;
    return DropdownButton({
        icon: 'download',
        label: 'Export',
        buttonSize: 'small',
        items: () => {
            const items = [
                { label: 'All tests', onclick: () => emit('ExportAll', {}) },
                {
                    label: 'Filtered tests',
                    onclick: () => emit('ExportFiltered', { payload: { records: testDefinitions.val } }),
                },
            ];
            if (hasSelection()) {
                items.push({
                    label: 'Selected tests',
                    onclick: () => emit('ExportSelected', { payload: { ids: getSelectedIds() } }),
                });
            }
            return items;
        },
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
                Attribute({ label: 'Test Type', value: row.test_name_short }),
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

const TestPickerChip = (text, color) => {
    const { span } = van.tags;
    return span(
        {
            class: 'tg-test-chip',
            style: `border:1px solid color-mix(in srgb, ${color} 25%, transparent);color:${color};`,
        },
        text,
    );
};

// A keyboard-shortcut hint for the picker footer: a key chip followed by its action.
const KeyHint = (key, action) => {
    const { span } = van.tags;
    return span(
        { class: 'tg-key-hint' },
        span({ class: 'tg-kbd' }, key),
        action,
    );
};

// Faceted add-test picker dialog (step 1) reusing the param form (step 2)
const AddDialogComponent = ({ open, info, validateResult, onClose }, emit) => {
    const { div, span, input, label, h4 } = van.tags;

    const testTypes = van.derive(() => getValue(info)?.test_types ?? []);
    const tableColumns = van.derive(() => getValue(info)?.table_columns ?? []);
    const testSuite = van.derive(() => getValue(info)?.test_suite ?? {});
    const tableGroupSchema = van.derive(() => getValue(info)?.table_group_schema ?? '');
    const tableGroupsId = van.derive(() => getValue(info)?.table_groups_id ?? '');
    const qualifiesTableRefsWithSchema = van.derive(() => getValue(info)?.qualifies_table_refs_with_schema ?? true);
    const prefillColumn = van.derive(() => getValue(info)?.prefill_column ?? null);

    // selectedColumn carries the general_type needed by the type-aware filter; resolve it from
    // the tableColumns entry so a prefill and a manual pick produce the identical shape.
    const columnFromEntry = (c) => ({
        table_name: c.table_name,
        column_name: c.column_name,
        general_type: c.general_type ?? null,
    });

    // ---- Step + selection state ----
    const step = van.state(1);
    const selectedTestType = van.state(null);
    const formValues = van.state({});

    // ---- Picker state ----
    const searchQuery = van.state('');
    const groupBy = van.state('impact');
    const focusIndex = van.state(-1); // -1 = no row highlighted until keyboard nav
    const selectedColumn = van.state(null); // { table_name, column_name, general_type } | null

    const facetSel = {};
    Object.keys(AXES).forEach((ax) => { facetSel[ax] = van.state([]); });

    // Build blank form values for the selected test type.
    const buildFormValues = (testType) => {
        if (!testType) return null;
        const tt = testTypes.rawVal.find(t => t.test_type === testType);
        if (!tt) return null;
        return {
            ...BLANK_PARAM_FIELDS,
            ...tt,
            id: null,
            default_test_description: tt.test_description,
            test_description: null,
            test_active: true,
            lock_refresh: false,
            severity: null,
            export_to_observability: null,
            schema_name: tableGroupSchema.rawVal,
            test_suite_id: testSuite.rawVal.id,
            table_groups_id: tableGroupsId.rawVal,
            table_name: null,
            column_name: null,
            skip_errors: 0,
            test_definition_status: null,
            last_auto_gen_date: null,
            profiling_as_of_date: null,
            profile_run_id: null,
        };
    };

    const toggleFacet = (ax, value) => {
        const cur = facetSel[ax].val;
        facetSel[ax].val = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
        focusIndex.val = -1;
    };
    const clearAll = () => {
        Object.values(facetSel).forEach((s) => { s.val = []; });
        searchQuery.val = '';
        focusIndex.val = -1;
    };

    // Reset to a fresh step-1 picker on each closed->open transition. The dialog is mounted
    // once and its state otherwise persists across reopens, which would show the stale step-2
    // form. Also re-seeds the locked column per open.
    const wasOpen = van.state(false);
    van.derive(() => {
        const isOpen = open.val;
        if (isOpen && !wasOpen.val) {
            step.val = 1;
            selectedTestType.val = null;
            formValues.val = {};
            searchQuery.val = '';
            focusIndex.val = -1;
            groupBy.val = 'impact';
            Object.values(facetSel).forEach((s) => { s.val = []; });
            const prefill = prefillColumn.rawVal;
            const match = prefill
                ? tableColumns.rawVal.find((c) => c.table_name === prefill.table_name && c.column_name === prefill.column_name)
                : null;
            selectedColumn.val = match ? columnFromEntry(match) : null;
            wasOpen.val = true;
        } else if (!isOpen) {
            wasOpen.val = false;
        }
    });

    const matchesSearch = (t, q) => {
        if (!q) return true;
        const hay = `${t.test_name_short} ${t.test_name_long} ${t.test_description}`.toLowerCase();
        return q.toLowerCase().split(/\s+/).filter(Boolean).every((tok) => hay.includes(tok));
    };

    // Search + column relevance only -- drives facet counts (PRD F9). A selected column filters
    // the list to tests applicable to its type; clearing the column shows all tests.
    const baseVisible = van.derive(() => {
        const q = searchQuery.val;
        const col = selectedColumn.val;
        return testTypes.val.filter((t) =>
            matchesSearch(t, q) && (!col || appliesToSelectedColumn(t, col.general_type)));
    });

    const passesFacets = (t) => Object.entries(facetSel).every(([ax, s]) => {
        const sel = s.val;
        if (!sel.length) return true;
        const v = AXES[ax].value(t);
        return v != null && sel.includes(v);
    });

    const filtered = van.derive(() => baseVisible.val.filter(passesFacets));

    // Group the result list by the chosen axis; null -> EMPTY bucket.
    const grouped = van.derive(() => {
        const axis = AXES[groupBy.val];
        const buckets = new Map();
        filtered.val.forEach((t) => {
            const key = axis.value(t) || EMPTY;
            if (!buckets.has(key)) buckets.set(key, []);
            buckets.get(key).push(t);
        });
        const order = axis.order; // sparse axes have a canonical order
        const entries = [...buckets.entries()];
        entries.sort((a, b) => {
            if (order) {
                const ia = order.indexOf(a[0]); const ib = order.indexOf(b[0]);
                return (ia < 0 ? Infinity : ia) - (ib < 0 ? Infinity : ib); // EMPTY bucket sorts last
            }
            return b[1].length - a[1].length;
        });
        return entries;
    });

    const flatList = van.derive(() => grouped.val.flatMap(([, tests]) => tests));

    // Per-axis value -> count, over baseVisible (not other facet selections).
    const counts = (ax) => {
        const m = new Map();
        baseVisible.val.forEach((t) => {
            const v = AXES[ax].value(t);
            if (v != null) m.set(v, (m.get(v) || 0) + 1);
        });
        return m;
    };

    const selectTest = (t) => {
        if (!t) return;
        selectedTestType.val = t;
        const fv = buildFormValues(t.test_type);
        const col = selectedColumn.rawVal;
        if (col) {
            const scope = fv.test_scope ?? 'column';
            if (scope !== 'tablegroup') {
                fv.table_name = col.table_name;
            }
            if (scope === 'column' || scope === 'referential' || scope === 'custom') {
                fv.column_name = col.column_name;
            }
        }
        formValues.val = fv;
        step.val = 2;
    };

    // ---- Keyboard: Cmd/Ctrl+K or "/" focus search, Up/Down move, Enter add, Esc close ----
    let searchEl = null;
    const onKeyDown = (e) => {
        if (step.val !== 1) return;
        if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && document.activeElement !== searchEl)) {
            e.preventDefault(); searchEl?.focus(); return;
        }
        if (e.key === 'Escape') { onClose(); return; }
        const list = flatList.val;
        if (e.key === 'ArrowDown') { e.preventDefault(); focusIndex.val = Math.min(focusIndex.val + 1, Math.max(list.length - 1, 0)); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); focusIndex.val = Math.max(focusIndex.val - 1, 0); }
        // Enter adds the focused row, or the only match when nothing is explicitly focused.
        else if (e.key === 'Enter') { e.preventDefault(); selectTest(list[focusIndex.val] ?? (list.length === 1 ? list[0] : null)); }
    };

    // Listen at the document level while step 1 is open so arrow keys work without first
    // clicking the picker. Attach/detach reactively; guard prevents duplicate registration.
    // The page's AbortSignal removes the listener on teardown — without it, a teardown
    // while the dialog is open (e.g. browser Back) would orphan onKeyDown on the document,
    // since nothing toggles open/step on unmount to run the detach branch below.
    let keydownAttached = false;
    van.derive(() => {
        const active = open.val && step.val === 1;
        if (active && !keydownAttached) {
            document.addEventListener('keydown', onKeyDown, { signal: getPageSignal(PAGE_KEY) ?? undefined });
            keydownAttached = true;
        } else if (!active && keydownAttached) {
            document.removeEventListener('keydown', onKeyDown);
            keydownAttached = false;
        }
    });

    // ---- Renderers ----
    const FacetGroup = (ax) => {
        const axis = AXES[ax];
        // Whole group is reactive: its title is hidden when no option has a count (PRD facet review).
        return () => {
            const m = counts(ax);
            let keys = [...m.keys()];
            if (axis.order) keys = axis.order.filter((k) => m.has(k));
            else keys.sort((a, b) => m.get(b) - m.get(a));
            if (!keys.length) return '';
            return div(
                { class: 'tg-facet-group', 'data-testid': 'facet-group', 'data-axis': ax },
                h4({ class: 'tg-facet-title' }, axis.label),
                div(
                    { class: 'flex-column fx-gap-1' },
                    ...keys.map((value) => {
                        const checked = van.derive(() => facetSel[ax].val.includes(value));
                        // Display-only Checkbox (pointer-events disabled via .tg-facet-checkbox); the
                        // row's onclick is the single toggle source, so the box can't double-fire.
                        return div(
                            {
                                class: 'tg-facet-option',
                                'data-testid': 'facet-option',
                                'data-axis': ax,
                                'data-value': value,
                                onclick: () => toggleFacet(ax, value),
                            },
                            span({ class: 'tg-facet-checkbox' }, Checkbox({ label: '', checked })),
                            span({ class: 'tg-facet-dot', style: `background:${axis.color(value)}` }),
                            span({ class: 'tg-facet-label' }, value),
                            span({ class: 'tg-facet-count' }, m.get(value)),
                        );
                    }),
                ),
            );
        };
    };

    const ResultRow = (t, isFocused) => {
        const row = div(
            {
                class: () => `tg-test-row${isFocused.val ? ' tg-test-row--focused' : ''}`,
                'data-testid': 'test-picker-row',
                'data-test-type': t.test_type,
                onclick: () => selectTest(t),
            },
            div(
                { class: 'flex-row fx-justify-space-between' },
                div({ class: 'tg-test-row-title' }, t.test_name_short),
            ),
            div({ class: 'tg-test-desc' }, t.test_description),
            div(
                { class: 'flex-row fx-flex-wrap fx-gap-1' },
                t.impact_dimension ? TestPickerChip(t.impact_dimension, AXES.impact.color(t.impact_dimension)) : null,
                t.algorithm ? TestPickerChip(t.algorithm, AXES.algorithm.color(t.algorithm)) : null,
                t.statistical_technique ? TestPickerChip(t.statistical_technique, AXES.technique.color(t.statistical_technique)) : null,
                t.health_dimension ? TestPickerChip(t.health_dimension, AXES.health.color(t.health_dimension)) : null,
                t.criteria ? TestPickerChip(t.criteria, AXES.criteria.color(t.criteria)) : null,
            ),
        );
        // Keep the keyboard-focused row visible within the scrolling list.
        van.derive(() => { if (isFocused.val) row.scrollIntoView({ block: 'nearest' }); });
        return row;
    };

    // One filter row: column relevance + search on the left, group-by pushed to the right.
    const ContextBar = (searchField) => div(
        { class: 'tg-picker-context flex-row fx-gap-3 fx-align-flex-end' },
        () => {
            // Column relevance filter. Option VALUES are the array index (string) so that
            // table/column names containing spaces or dots can never break parsing.
            const cols = tableColumns.val;
            const options = cols.map((c, i) => ({ label: `${c.table_name}.${c.column_name}`, value: String(i) }));
            const sel = selectedColumn.val;
            const currentIdx = sel ? cols.findIndex((c) => c.table_name === sel.table_name && c.column_name === sel.column_name) : -1;
            return Select({
                label: 'Show tests relevant to a column',
                allowNull: true,
                // Cap growth so a long table.column value ellipsizes instead of crowding search.
                style: 'max-width: 320px;',
                value: currentIdx >= 0 ? String(currentIdx) : null,
                options,
                onChange: (val) => {
                    if (val == null || val === '') { selectedColumn.val = null; return; }
                    selectedColumn.val = columnFromEntry(tableColumns.rawVal[Number(val)]);
                },
            });
        },
        div({ class: 'tg-picker-search fx-flex', 'data-testid': 'test-picker-search' }, searchField),
        Select({
            label: 'Group by',
            value: groupBy.val,
            options: GROUP_BY_AXES.map((ax) => ({ label: AXES[ax].label, value: ax })),
            onChange: (val) => { groupBy.val = val; focusIndex.val = -1; },
        }),
    );

    const ActiveFilters = () => div(
        { class: 'flex-row fx-flex-wrap fx-gap-1', 'data-testid': 'test-picker-active-filters' },
        () => {
            const chips = [];
            Object.entries(facetSel).forEach(([ax, s]) => s.val.forEach((value) => {
                chips.push(span(
                    { class: 'tg-active-chip flex-row', onclick: () => toggleFacet(ax, value) },
                    span(`${AXES[ax].label}: ${value}`),
                    Icon({ size: 14 }, 'close'),
                ));
            }));
            if (!chips.length) return '';
            chips.push(span(
                { 'data-testid': 'test-picker-clear' },
                Button({ type: 'basic', label: 'Clear all', onclick: clearAll }),
            ));
            return div({ class: 'flex-row fx-flex-wrap fx-gap-1' }, ...chips);
        },
    );

    const ResultsPane = () => div(
        { class: 'tg-picker-results' },
        // Fixed header — count stays put while the list below scrolls.
        div(
            { class: 'tg-picker-results-header' },
            span(
                { 'data-testid': 'test-picker-count', class: 'tg-picker-count' },
                () => `${filtered.val.length} matching test types${!!selectedColumn.val ? ' for selected column' : ''}`
            ),
        ),
        div(
            { class: 'tg-picker-list' },
            // One-result hint (PRD F13): when exactly one test matches, prompt Enter-to-add.
            () => filtered.val.length === 1
                ? div({ class: 'tg-one-result-hint mb-2', 'data-testid': 'test-picker-one-hint' },
                    `${filtered.val[0].test_name_short} — press Enter to add`)
                : '',
            () => {
                const groups = grouped.val;
                if (!groups.length) {
                    return div(
                        { class: 'tg-picker-empty', 'data-testid': 'test-picker-empty' },
                        span('No tests match this filter combination.'),
                        Button({ type: 'stroked', label: 'Clear filters and search', onclick: clearAll }),
                    );
                }
                let runningIndex = -1;
                return div(
                    { class: 'flex-column fx-gap-2' },
                    ...groups.map(([groupName, tests]) => div(
                        { class: 'tg-result-group' },
                        div(
                            { class: 'tg-group-band' },
                            span({ class: 'tg-group-band-name' }, groupName),
                            span({ class: 'tg-group-band-count' }, `${tests.length} test types`),
                        ),
                        ...tests.map((t) => {
                            runningIndex += 1;
                            const myIndex = runningIndex;
                            const isFocused = van.derive(() => focusIndex.val === myIndex);
                            return ResultRow(t, isFocused);
                        }),
                    )),
                );
            },
        ),
    );

    const PickerView = () => {
        // Reusable Input component for search. The keyboard handler focuses the inner <input>,
        // resolved by id below (Input renders its label with this id).
        const searchField = Input({
            id: 'tg-picker-search',
            icon: 'search',
            clearable: true,
            style: 'width: 100%;',
            placeholder: 'Search name or description',
            value: searchQuery,
            onChange: (value) => { searchQuery.val = value; focusIndex.val = -1; },
        });
        // Load-bearing on every step-1 (re)render, not just first open: refocuses search when
        // returning from the step-2 form. Do not hoist out of PickerView.
        requestAnimationFrame(() => {
            searchEl = document.getElementById('tg-picker-search')?.querySelector('input') ?? null;
            searchEl?.focus();
        });

        return div(
            { class: 'tg-test-picker', 'data-testid': 'test-picker' },
            // Fixed header: column relevance + search + group-by in one row, then active filters.
            div(
                { class: 'tg-picker-header' },
                ContextBar(searchField),
                ActiveFilters(),
            ),
            div(
                { class: 'tg-picker-body fx-gap-3' },
                div(
                    { class: 'tg-picker-rail' },
                    ...FACET_AXES.map(FacetGroup),
                ),
                ResultsPane(),
            ),
            div(
                { class: 'tg-picker-footer', 'data-testid': 'test-picker-footer' },
                KeyHint('↑ ↓', 'navigate'),
                KeyHint('Enter', 'select'),
                KeyHint('/', 'focus search'),
            ),
        );
    };

    const FormView = () => TestDefFormContent({
        formValues: formValues.val,
        tableColumns: tableColumns.rawVal,
        testSuite: testSuite.rawVal,
        qualifiesTableRefsWithSchema: qualifiesTableRefsWithSchema.rawVal,
        validateResult: getValue(validateResult),
        mode: 'add',
        onFormChange: (changes) => { formValues.val = { ...formValues.rawVal, ...changes }; },
        onValidate: () => emit('ValidateTest', { payload: formValues.rawVal }),
        onSave: () => emit('AddTestSaved', { payload: formValues.rawVal }),
        onBack: () => { step.val = 1; selectedTestType.val = null; },
        onCancel: onClose,
    });

    const dialogTitle = van.derive(() => `Add Test - ${step.val === 1 ? 'Pick a Test Type' : 'Configure Test'}`);

    return Dialog(
        { title: dialogTitle, open, onClose, width: '68rem' },
        () => step.val === 1 ? PickerView() : FormView(),
    );
};

// Edit dialog — mounted once, state persists across Python reruns
const EditDialogComponent = ({ open, info, validateResult: validateResultProp, onClose }, emit) => {
    const dialogInfo = van.derive(() => getValue(info) ?? null);
    const tableColumns = van.derive(() => dialogInfo.val?.table_columns ?? []);
    const testSuite = van.derive(() => dialogInfo.val?.test_suite ?? {});
    const qualifiesTableRefsWithSchema = van.derive(() => dialogInfo.val?.qualifies_table_refs_with_schema ?? true);
    const validateResult = van.derive(() => getValue(validateResultProp) ?? null);

    const formValues = van.state(null);

    const initFormFromInfo = () => {
        const di = dialogInfo.rawVal;
        if (!di?.test_definition) { formValues.val = null; return; }
        const def = di.test_definition;
        const ttRow = (di.test_types ?? []).find(tt => tt.test_type === def.test_type) ?? {};
        formValues.val = {
            ...def,
            run_type: ttRow.run_type ?? def.run_type ?? 'CAT',
            column_name_prompt: ttRow.column_name_prompt ?? null,
            column_name_help: ttRow.column_name_help ?? null,
        };
    };

    // Reset form when dialog opens (closed→open), clear when it closes
    const wasOpen = van.state(false);
    van.derive(() => {
        const isOpen = open.val;
        if (isOpen && !wasOpen.val) {
            initFormFromInfo();
            wasOpen.val = true;
        } else if (!isOpen) {
            formValues.val = null;
            wasOpen.val = false;
        }
    });

    return Dialog(
        { title: 'Edit Test', open, onClose, width: '52rem' },
        () => {
            open.val;
            const fv = formValues.val;
            const vr = validateResult.val;
            if (!fv) return '';
            return div(
                { class: 'flex-column fx-gap-4 td-form-dialog' },
                TestDefFormContent({
                    formValues: fv,
                    tableColumns: tableColumns.rawVal,
                    testSuite: testSuite.rawVal,
                    qualifiesTableRefsWithSchema: qualifiesTableRefsWithSchema.rawVal,
                    validateResult: vr,
                    mode: 'edit',
                    onFormChange: (changes) => {
                        formValues.val = { ...formValues.rawVal, ...changes };
                    },
                    onValidate: () => emit('ValidateTest', { payload: formValues.rawVal }),
                    onSave: () => emit('EditTestSaved', { payload: formValues.rawVal }),
                    onCancel: onClose,
                }),
            );
        },
    );
};

// Shared form content for add/edit dialogs
const TestDefFormContent = ({ formValues, tableColumns, testSuite, validateResult, mode, qualifiesTableRefsWithSchema, onFormChange, onValidate, onSave, onCancel, onBack }) => {
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

    const inheritedImpactDimension = formValues.default_impact_dimension ?? 'Conformance';
    const impactDimensionOptions = [
        { label: `Inherited (${inheritedImpactDimension})`, value: null },
        { label: 'Reliability', value: 'Reliability' },
        { label: 'Conformance', value: 'Conformance' },
        { label: 'Regularity', value: 'Regularity' },
        { label: 'Usability', value: 'Usability' },
    ];
    const showImpactDimensionOverride = ['custom', 'referential'].includes(testScope);

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

        // Checkboxes
        div(
            { class: 'flex-row fx-gap-4' },
            Checkbox({
                label: 'Test Active',
                checked: () => fv.val.test_active ?? true,
                onChange: (v) => updateField('test_active', v),
            }),
            Checkbox({
                label: 'Lock Refresh',
                checked: () => fv.val.lock_refresh ?? false,
                onChange: (v) => updateField('lock_refresh', v),
            }),
        ),

        // Severity + Observability + Impact Dimension selects
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
            showImpactDimensionOverride ? div(
                { style: 'flex: calc(50% - 8px) 0 0;' },
                () => Select({
                    label: 'Impact Dimension Override',
                    value: fv.val.impact_dimension ?? null,
                    options: impactDimensionOptions,
                    allowNull: false,
                    helpText: 'Override the default impact classification for this test. Affects how the test result is categorized in score breakdowns.',
                    onChange: (value) => updateField('impact_dimension', value),
                }),
            ) : null,
        ),

        // Schema (read-only)
        qualifiesTableRefsWithSchema
            ? Input({
                name: 'schema_name',
                label: 'Schema',
                value: formValues.schema_name ?? '',
                disabled: true,
            })
            : null,

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
                definition: formValues,
                qualifiesTableRefsWithSchema,
                onChange: (changes) => {
                    if (Object.keys(changes).length === 0) return;
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
            { class: 'flex-row fx-justify-space-between fx-gap-2' },
            div(
                { class: 'flex-row fx-gap-2' },
                onBack
                    ? Button({
                        type: 'stroked',
                        color: 'basic',
                        icon: 'arrow_back',
                        label: 'Back',
                        width: 'auto',
                        onclick: onBack,
                    })
                    : null,
                isValidatable
                    ? Button({
                        type: 'stroked',
                        color: 'basic',
                        label: 'Validate',
                        width: 'auto',
                        onclick: onValidate,
                    })
                    : null,
            ),
            div(
                { class: 'flex-row fx-gap-2' },
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
                    label: mode === 'edit' ? 'Save' : 'Add',
                    width: 'auto',
                    onclick: onSave,
                }),
            ),
        ),
    );
};

// Copy/Move dialog — mounted once
const CopyMoveDialogComponent = ({ open, info, onClose }, emit) => {
    const dialogInfo = van.derive(() => getValue(info) ?? null);
    const collision = van.derive(() => dialogInfo.val?.collision ?? null);

    const targetProjectCode = van.state(null);
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
            targetProjectCode.val = di?.current_project_code ?? null;
            targetTgId.val = di?.current_table_group_id ?? null;
            targetTsId.val = null;
            targetTableName.val = null;
            targetColumnName.val = null;
            wasOpen.val = true;
        } else if (!isOpen) {
            wasOpen.val = false;
        }
    });

    const projectOptions = van.derive(() =>
        (dialogInfo.val?.projects ?? []).map(p => ({ label: p.project_name, value: p.project_code }))
    );

    const tableGroupOptions = van.derive(() => {
        const project = targetProjectCode.val;
        const tgs = dialogInfo.val?.table_groups_by_project?.[project] ?? [];
        return tgs.map(tg => ({ label: tg.table_groups_name, value: tg.id }));
    });

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
        const tableName = targetTableName.val;
        const colName = targetColumnName.val;
        const di = dialogInfo.val;
        if (tgId && tsId && di?.selected) {
            emit('CopyMoveTargetChanged', {
                payload: {
                    selected: di.selected,
                    target_table_group_id: tgId,
                    target_test_suite_id: tsId,
                    target_table_name: tableName || null,
                    target_column_name: colName || null,
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
                label: 'Target Project',
                value: targetProjectCode.val,
                options: projectOptions.val,
                required: true,
                filterable: true,
                onChange: (value) => {
                    targetProjectCode.val = value;
                    targetTgId.val = null;
                    targetTsId.val = null;
                    targetTableName.val = null;
                    targetColumnName.val = null;
                },
            }),

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
                { class: 'flex-row fx-justify-flex-end fx-gap-2' },
                () => Button({
                    type: 'stroked',
                    color: 'basic',
                    label: 'Copy',
                    width: 'auto',
                    disabled: !movableIds.val.length || !targetTsId.val,
                    onclick: () => emit('CopyConfirmed', { payload: buildPayload() }),
                }),
                () => Button({
                    type: 'flat',
                    color: 'primary',
                    label: 'Move',
                    width: 'auto',
                    disabled: !movableIds.val.length || !targetTsId.val,
                    onclick: () => emit('MoveConfirmed', { payload: buildPayload() }),
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
    border-top: 1px dashed var(--border-color, #dddfe2);
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

.tg-test-picker { display: flex; flex-direction: column; gap: 12px; height: 70vh; min-height: 0; }
.tg-picker-header { flex: none; display: flex; flex-direction: column; gap: 12px; }
.tg-picker-body { flex: 1; min-height: 0; display: flex; flex-direction: row; align-items: stretch; }
.tg-picker-rail { flex: 0 0 260px; min-height: 0; overflow-y: auto; overflow-x: hidden; padding-right: 8px; border-right: 1px solid var(--border-color, #e0e0e0); }
.tg-picker-results { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.tg-picker-results-header { flex: none; padding-bottom: 8px; margin-bottom: 8px; border-bottom: 1px solid var(--border-color, #e0e0e0); }
.tg-picker-count { font-size: 13px; color: var(--secondary-text-color, #666); }
.tg-picker-list { flex: 1; overflow-y: auto; }
.tg-facet-group { margin-bottom: 14px; }
.tg-facet-title { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color, #666); }
.tg-facet-option { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; color: var(--primary-text-color); }
.tg-facet-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.tg-facet-label { color: var(--primary-text-color); }
.tg-facet-count { margin-left: auto; color: var(--secondary-text-color, #888); font-variant-numeric: tabular-nums; }
.tg-facet-checkbox { display: inline-flex; pointer-events: none; }
/* --empty stays distinct from the --table-hover-color row hover so the band reads as a divider. */
.tg-group-band { position: sticky; top: 0; z-index: 1; display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 6px 10px; margin-bottom: 4px; border-radius: 6px; background: var(--empty, #e0e0e0); }
.tg-group-band-name { font-weight: 600; }
.tg-group-band-count { font-size: 12px; color: var(--secondary-text-color, #888); font-variant-numeric: tabular-nums; }
.tg-result-group { display: flex; flex-direction: column; gap: 6px; }
.tg-test-row { position: relative; padding: 10px; border: 2px solid transparent; border-radius: 8px; cursor: pointer; }
/* Divider sits in the gap below the row, not on its border, so it never overlaps the focus outline. */
.tg-result-group .tg-test-row:not(:last-child)::after { content: ''; position: absolute; left: 8px; right: 8px; bottom: -4px; border-bottom: 1px dashed var(--border-color, #dddfe2); }
.tg-test-row:hover { background: var(--table-hover-color, #f3f4f6); }
.tg-test-row--focused { border-color: var(--primary-color, #1976d2); background: var(--table-hover-color, #f3f4f6); }
.tg-test-row-title { font-weight: 600; }
.tg-test-desc { font-size: 13px; color: var(--secondary-text-color, #555); margin: 2px 0 6px; }
.tg-test-chip { font-size: 11px; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
.tg-active-chip { font-size: 12px; line-height: 1; gap: 3px; padding: 2px 6px 2px 8px; border-radius: 999px; background: var(--table-hover-color, #eee); cursor: pointer; }
.tg-active-chip .material-symbols-rounded { cursor: pointer; }
.tg-one-result-hint { padding: 8px 10px; border-radius: 6px; background: var(--table-hover-color, #eef2ff); font-size: 13px; }
.tg-picker-empty { display: flex; flex-direction: column; gap: 12px; align-items: flex-start; padding: 40px 8px; }
.tg-picker-footer { flex: none; display: flex; gap: 16px; align-items: center; padding-top: 10px; border-top: 1px solid var(--border-color, #e0e0e0); font-size: 12px; color: var(--secondary-text-color, #666); }
.tg-key-hint { display: inline-flex; align-items: center; gap: 6px; }
.tg-kbd { display: inline-flex; align-items: center; min-width: 18px; justify-content: center; padding: 1px 6px; border: 1px solid var(--border-color, #d0d0d0); border-radius: 4px; background: var(--empty, #e0e0e0); font-family: monospace; font-size: 11px; color: var(--primary-text-color); }
`);

export { TestDefinitions, EditDialogComponent };

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
        componentState.signal = enterPage(PAGE_KEY);
        van.add(parentElement, TestDefinitions(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => {
        exitPage(PAGE_KEY);
        parentElement.state = null;
    };
};
