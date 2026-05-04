/**
 * @typedef HygieneItem
 * @type {object}
 * @property {string} id
 * @property {string} table_name
 * @property {string} column_name
 * @property {string} schema_name
 * @property {string} anomaly_name
 * @property {string} issue_likelihood
 * @property {string?} disposition
 * @property {string} action
 * @property {string} anomaly_description
 * @property {string} detail
 * @property {string} suggested_action
 * @property {string} likelihood_explanation
 * @property {number} likelihood_order
 * @property {string} anomaly_id
 * @property {string} table_groups_id
 * @property {string} db_data_type
 * @property {string} profiling_starttime
 * @property {string} profile_run_id
 *
 * @typedef SummaryItem
 * @type {object}
 * @property {string} label
 * @property {number} value
 * @property {string} color
 * @property {string?} type
 *
 * @typedef Properties
 * @type {object}
 * @property {string} run_id
 * @property {HygieneItem[]} items
 * @property {SummaryItem[]} summaries
 * @property {string?} score
 * @property {boolean} is_latest_run
 * @property {object} filters
 * @property {object} permissions
 * @property {object?} profiling_column
 * @property {object?} source_data
 * @property {number} page
 * @property {number} total_count
 * @property {number} page_size
 * @property {object[]} sort_state
 * @property {object} filter_options
 */
import van from '/app/static/js/van.min.js';
import { Table } from '/app/static/js/components/table.js';
import { Select } from '/app/static/js/components/select.js';
import { Toggle } from '/app/static/js/components/toggle.js';
import { Button } from '/app/static/js/components/button.js';
import { Checkbox } from '/app/static/js/components/checkbox.js';
import { DropdownButton } from '/app/static/js/components/dropdown_button.js';
import { SummaryCounts } from '/app/static/js/components/summary_counts.js';
import { Attribute } from '/app/static/js/components/attribute.js';
import { Icon } from '/app/static/js/components/icon.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { ProfilingResultsDialog } from '../shared/profiling_results_dialog.js';
import { SourceDataDialog } from '../shared/source_data_dialog.js';

const { div, span, h3, h4, small } = van.tags;

const LIKELIHOOD_OPTIONS = [
    { label: 'Definite', value: 'Definite' },
    { label: 'Likely', value: 'Likely' },
    { label: 'Possible', value: 'Possible' },
    { label: 'Potential PII', value: 'Potential PII' },
];

const ACTION_OPTIONS = [
    { label: 'Confirmed', value: 'Confirmed' },
    { label: 'Dismissed', value: 'Dismissed' },
    { label: 'Muted', value: 'Inactive' },
    { label: 'No Action', value: 'No Action' },
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

const BASE_TABLE_COLUMNS = [
    { name: 'table_name', label: 'Table', width: 160, sortable: true, overflow: 'hidden' },
    { name: 'column_name', label: 'Column', width: 160, sortable: true, overflow: 'hidden' },
    { name: 'issue_likelihood', label: 'Likelihood', width: 130, sortable: true, overflow: 'hidden' },
    { name: 'action', label: 'Action', width: 80, align: 'center', sortable: true },
    { name: 'anomaly_name', label: 'Issue Type', width: 200, sortable: true, overflow: 'hidden' },
    { name: 'detail', label: 'Detail', width: 300, overflow: 'hidden' },
];

const buildTableRow = (item) => ({
    id: item.id,
    table_name: item.table_name ?? '',
    column_name: item.column_name ?? '',
    issue_likelihood: item.issue_likelihood ?? '',
    action: buildDispositionIcon(item.disposition),
    anomaly_name: item.anomaly_name ?? '',
    detail: item.detail ?? '',
});

const HygieneSourceDataHeader = (d) => {
    const header = d.header;
    if (!header) return '';
    return div(
        { class: 'flex-column fx-gap-2 mb-2' },
        div(
            { class: 'text-caption' },
            span({ style: 'font-weight: 500' }, 'Table > Column: '),
            span({}, `${header.table_name} > ${header.column_name}`),
        ),
        div(
            h4({ style: 'margin: 0' }, header.anomaly_name),
            div({ class: 'text-caption' }, header.anomaly_description),
        ),
        div(
            h4({ style: 'margin: 0' }, 'Hygiene Issue Detail'),
            div({ class: 'text-caption' }, header.detail),
        ),
    );
};

const ExportMenu = (likelihoodFilter, tableFilter, columnFilter, issueTypeFilter, actionFilter, hasSelection, getSelectedIds, emit) => {
    return DropdownButton({
        icon: 'download',
        label: 'Export',
        buttonSize: 'small',
        items: () => {
            const items = [
                { label: 'All issues', onclick: () => emit('ExportAll', {}) },
                {
                    label: 'Filtered issues',
                    onclick: () => emit('ExportFiltered', {
                        payload: {
                            likelihood: likelihoodFilter.rawVal,
                            table_name: tableFilter.rawVal,
                            column_name: columnFilter.rawVal,
                            issue_type: issueTypeFilter.rawVal,
                            action: actionFilter.rawVal,
                        },
                    }),
                },
            ];
            if (hasSelection()) {
                items.push({
                    label: 'Selected issues',
                    onclick: () => emit('ExportSelected', { payload: { ids: getSelectedIds() } }),
                });
            }
            return items;
        },
    });
};

const DetailPanel = (selectedRow) => {
    const fields = [
        { key: 'anomaly_name', label: 'Issue Type' },
        { key: 'table_name', label: 'Table' },
        { key: 'column_name', label: 'Column' },
        { key: 'db_data_type', label: 'Data Type' },
        { key: 'anomaly_description', label: 'Description' },
        { key: 'detail', label: 'Detail' },
        { key: 'likelihood_explanation', label: 'Likelihood' },
        { key: 'suggested_action', label: 'Suggested Action' },
    ];

    return div(
        { class: 'flex-column fx-gap-2' },
        h3({ style: 'margin: 0; font-size: 16px; font-weight: 500' }, 'Hygiene Issue Detail'),
        div(
            { class: 'tg-hi--detail-grid' },
            ...fields.map(f => Attribute({ label: f.label, value: selectedRow[f.key] })),
        ),
    );
};

const HygieneIssues = (/** @type Properties */ props) => {
    const { emit } = props;
    loadStylesheet('hygiene-issues', stylesheet);

    const items = van.derive(() => getValue(props.items) ?? []);
    const summaries = van.derive(() => getValue(props.summaries) ?? []);
    const permissions = van.derive(() => getValue(props.permissions) ?? {});

    // Pagination state from Python
    const currentPage = van.derive(() => getValue(props.page) ?? 0);
    const totalCount = van.derive(() => getValue(props.total_count) ?? 0);
    const pageSize = van.derive(() => getValue(props.page_size) ?? 500);

    // Filter options from Python
    const filterOptions = van.derive(() => getValue(props.filter_options) ?? {});

    const initialFilters = getValue(props.filters) ?? {};
    const likelihoodFilter = van.state(initialFilters.likelihood ?? null);
    const tableFilter = van.state(initialFilters.table_name ?? null);
    const columnFilter = van.state(initialFilters.column_name ?? null);
    const issueTypeFilter = van.state(initialFilters.issue_type ?? null);
    const actionFilter = van.state(initialFilters.action ?? null);

    // Sort state initialized from Python
    const initialSortState = getValue(props.sort_state) ?? [];
    const sortColumns = van.state(
        initialSortState.length > 0
            ? initialSortState
            : [
                { field: 'issue_likelihood', order: 'asc' },
                { field: 'table_name', order: 'asc' },
                { field: 'column_name', order: 'asc' },
            ]
    );

    const multiSelect = van.state(false);
    const selectAll = van.state(false);
    const selectedRowId = van.state(getValue(props.selected_id) ?? null);

    // Filter options derived from Python-provided full list
    const tableOptions = van.derive(() => {
        const names = filterOptions.val.table_names ?? [];
        return names.map(n => ({ label: n, value: n }));
    });

    const columnOptions = van.derive(() => {
        const names = filterOptions.val.column_names ?? [];
        return names.map(n => ({ label: n, value: n }));
    });

    const issueTypeOptions = van.derive(() => {
        const types = filterOptions.val.issue_types ?? [];
        return types.map(t => ({ label: t.anomaly_name, value: t.anomaly_id }));
    });

    // No client-side filtering or sorting -- items from Python are already filtered, sorted, and paginated
    const selectedRow = van.derive(() =>
        selectedRowId.val ? items.val.find(r => r.id === selectedRowId.val) ?? null : null
    );

    // Per-row checkbox states (Phase 3: real Checkbox components)
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
    const selectedIdsCount = van.state(0);
    const selectedIdSetForRestore = new Set();

    const onSelectAllToggle = (checked) => {
        if (checked) {
            selectAll.val = true;
            for (const item of items.rawVal) {
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
    const tableColumns = van.derive(() => multiSelect.val ? [checkboxColumn, ...BASE_TABLE_COLUMNS] : BASE_TABLE_COLUMNS);

    van.derive(() => {
        if (!multiSelect.val) {
            clearAllCheckboxStates();
            selectedIds = [];
            selectedIdsCount.val = 0;
            selectedIdSetForRestore.clear();
        }
    });

    // Table rows built from items (already filtered/sorted/paginated by server)
    const tableRows = van.derive(() => {
        const isMulti = multiSelect.val;
        const isSelectAll = selectAll.val;
        const currentItems = items.val;

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
            const row = buildTableRow(item);
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
        if (multiSelect.rawVal) return selectedIdSetForRestore.has(row.id);
        return row.id === selectedRowId.rawVal;
    };

    const onRowsSelected = (idxs) => {
        if (multiSelect.rawVal) {
            const currentPageItemIds = new Set(items.rawVal.map(r => r.id));
            const activeSet = new Set();
            for (const i of idxs) {
                const item = items.rawVal[i];
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
                const row = items.rawVal[idxs[0]];
                if (row && row.id !== selectedRowId.rawVal) {
                    selectedRowId.val = row.id;
                    emit('RowSelected', { payload: row.id });
                }
            }
        }
    };

    const getCurrentFilters = () => ({
        likelihood: likelihoodFilter.rawVal,
        table_name: tableFilter.rawVal,
        column_name: columnFilter.rawVal,
        issue_type: issueTypeFilter.rawVal,
        action: actionFilter.rawVal,
    });

    const emitFilterChanged = () => {
        emit('FilterChanged', { payload: getCurrentFilters() });
    };

    const onLikelihoodChange = (value) => {
        likelihoodFilter.val = value;
        if (value === 'Potential PII') issueTypeFilter.val = null;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onTableChange = (value) => {
        tableFilter.val = value;
        columnFilter.val = null;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onColumnChange = (value, meta) => {
        columnFilter.val = meta?.isCustom ? `%${value}%` : value;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onIssueTypeChange = (value) => {
        issueTypeFilter.val = value;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const onActionChange = (value) => {
        actionFilter.val = value;
        selectedRowId.val = null;
        emitFilterChanged();
    };

    const getSelectedIds = () => {
        if (multiSelect.val && selectedIdSetForRestore.size > 0) {
            return [...selectedIdSetForRestore];
        }
        return selectedRowId.rawVal ? [selectedRowId.rawVal] : [];
    };

    const allSelectedArePassed = van.derive(() => {
        // For hygiene issues, disposition buttons are disabled when nothing is selected
        // or all selected items already have the target disposition
        if (multiSelect.val) {
            return selectedIdsCount.val === 0;
        }
        return !selectedRow.val;
    });

    const onDisposition = (status) => {
        if (selectAll.rawVal) {
            emit('DispositionAll', { payload: { filters: getCurrentFilters(), status } });
            return;
        }
        const ids = getSelectedIds();
        if (ids.length > 0) {
            emit('DispositionChanged', { payload: { ids, status } });
        }
    };

    // Score
    const score = van.derive(() => getValue(props.score) ?? '--');
    const isLatestRun = van.derive(() => getValue(props.is_latest_run) ?? false);

    // Summary sections
    const othersSummary = van.derive(() => summaries.val.filter(s => s.type !== 'PII'));
    const piiSummary = van.derive(() => summaries.val.filter(s => s.type === 'PII'));

    // Table header bar (actions above the table)
    const tableHeader = div(
        { class: 'flex-row fx-align-center fx-gap-2 p-2' },
        Toggle({
            label: () => {
                return div(
                    { class: 'flex-column' },
                    span('Multi-Select'),
                    () => {
                        if (!multiSelect.val) return '';
                        if (selectAll.val) return span({ class: 'text-caption' }, () => `All ${totalCount.val} matching issues selected`);
                        const count = selectedIdsCount.val;
                        if (count > 0) return span({ class: 'text-caption' }, `${count} issue${count !== 1 ? 's' : ''} selected`);
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
            const disabled = allSelectedArePassed.val;
            return div(
                { class: 'flex-row fx-gap-1' },
                Button({ type: 'icon', icon: 'check_circle', tooltip: 'Confirm selected as relevant', disabled, onclick: () => onDisposition('Confirmed') }),
                Button({ type: 'icon', icon: 'cancel', tooltip: 'Dismiss selected as not relevant', disabled, onclick: () => onDisposition('Dismissed') }),
                Button({ type: 'icon', icon: 'notifications_off', tooltip: 'Mute selected for future runs', disabled, onclick: () => onDisposition('Inactive') }),
                Button({ type: 'icon', icon: 'restart_alt', tooltip: 'Clear action on selected', disabled, onclick: () => onDisposition('No Decision') }),
            );
        },
        span({ style: 'width: 0px; height: 24px; border-right: 1px dashed var(--border-color);'}, ''),
        () => {
            const hasAnySelection = selectedIdsCount.val > 0 || !!selectedRow.val;
            if (!hasAnySelection) return '';

            return Button({
                type: 'stroked',
                icon: 'download',
                label: 'Issue Report',
                width: 'auto',
                size: 'small',
                style: 'background: var(--button-generic-background-color)',
                onclick: () => emit('DownloadReport', { payload: { ids: getSelectedIds() } }),
            });
        },
        ExportMenu(
            likelihoodFilter, tableFilter, columnFilter, issueTypeFilter, actionFilter,
            () => selectedRowId.val || selectedIdsCount.val > 0,
            getSelectedIds,
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
                    selectedIdsCount.val = 0;
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
                span({ class: 'text-secondary' }, 'No hygiene issues found matching filters'),
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

    return div(
        { 'data-testid': 'hygiene-issues', class: 'flex-column' },

        // Dialogs (mounted once at top, driven by props from Python)
        ProfilingResultsDialog({ emit,
            profilingColumn: van.derive(() => getValue(props.profiling_column) ?? null),
            onClose: () => emit('ProfilingClosed', {}),
            width: '50rem',
            testId: 'profiling-dialog',
        }),
        SourceDataDialog({ emit,
            sourceData: van.derive(() => getValue(props.source_data) ?? null),
            onClose: () => emit('SourceDataClosed', {}),
            renderHeader: HygieneSourceDataHeader,
            width: '60rem',
            testId: 'source-data-dialog',
        }),

        // Summary row
        div(
            { class: 'flex-row fx-gap-5 fx-align-flex-end mb-3 fx-flex-wrap' },
            () => othersSummary.val.length
                ? div(
                    { class: 'flex-column fx-gap-1' },
                    div({ class: 'text-caption' }, 'Hygiene Issues'),
                    SummaryCounts({ items: othersSummary.val }),
                )
                : '',
            () => piiSummary.val.length
                ? div(
                    { class: 'flex-column fx-gap-1' },
                    div({ class: 'text-caption' }, 'Potential PII (Risk)'),
                    SummaryCounts({ items: piiSummary.val }),
                )
                : '',
            span({class: 'fx-flex'}),
            div(
                { class: 'flex-row fx-gap-2 fx-align-flex-end' },
                div(
                    { class: 'flex-column' },
                    div({ class: 'text-caption'}, 'Score'),
                    div({ style: 'font-size: 28px' }, score),
                ),
                Button({
                    type: 'icon',
                    icon: 'autorenew',
                    iconSize: 22,
                    style: 'color: var(--secondary-text-color)',
                    tooltip: () => `Recalculate scores for run ${isLatestRun.val ? 'and table group' : ''}`,
                    onclick: () => emit('RefreshScore', {}),
                }),
            ),
        ),

        // Filters row
        div(
            { class: 'flex-row fx-gap-2 fx-align-flex-end mb-2 fx-flex-wrap' },
            () => Select({
                label: 'Likelihood',
                value: likelihoodFilter.val,
                options: LIKELIHOOD_OPTIONS,
                testId: 'likelihood-filter',
                style: 'min-width: 160px',
                onChange: onLikelihoodChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Table',
                value: tableFilter.val,
                options: tableOptions.val,
                testId: 'table-filter',
                style: 'min-width: 160px',
                filterable: true,
                onChange: onTableChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Column',
                value: columnFilter.val,
                options: columnOptions.val,
                testId: 'column-filter',
                style: 'min-width: 160px',
                filterable: true,
                acceptNewOptions: true,
                onChange: onColumnChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Issue Type',
                value: issueTypeFilter.val,
                options: issueTypeOptions.val,
                testId: 'issue-type-filter',
                style: 'min-width: 200px',
                filterable: true,
                onChange: onIssueTypeChange,
                allowNull: true,
                disabled: likelihoodFilter.val === 'Potential PII',
            }),
            () => Select({
                label: 'Action',
                value: actionFilter.val,
                options: ACTION_OPTIONS,
                testId: 'action-filter',
                style: 'min-width: 160px',
                onChange: onActionChange,
                allowNull: true,
            }),
        ),

        // Data table
        dataTable,

        // Detail panel (hidden in multi-select mode)
        div(
            { style: () => selectedRow.val && !multiSelect.val ? 'margin-top: 16px' : 'display: none' },
            () => {
                const sel = selectedRow.val;
                if (!sel) return '';

                return div(
                    { class: 'tg-hi--detail flex-column fx-gap-4' },
                    div(
                        { class: 'flex-row fx-gap-2 fx-justify-content-flex-end' },
                        sel.table_name !== '(multi-table)' 
                            ? Button({
                                type: 'stroked', icon: 'query_stats', label: 'Profiling', width: 'auto',
                                style: 'background: var(--button-generic-background-color)',
                                onclick: () => emit('ViewProfiling', { payload: sel.id }),
                            })
                            : '',
                        Button({
                            type: 'stroked', icon: 'visibility', label: 'Source Data', width: 'auto',
                            style: 'background: var(--button-generic-background-color)',
                            onclick: () => emit('ViewSourceData', { payload: sel.id }),
                        }),
                    ),
                    DetailPanel(sel),
                );
            },
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-hi--detail {
    border-top: 1px dashed var(--border-color, #dddfe2);
    padding-top: 16px;
}

.tg-hi--detail-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 12px;
    max-width: 700px;
}
`);

export { HygieneIssues };

export default (component) => {
    const { data, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, HygieneIssues(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
