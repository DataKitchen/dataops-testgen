/**
 * @typedef ProfilingItem
 * @type {object}
 * @property {string} id
 * @property {'column'} type
 * @property {string} table_name
 * @property {string} column_name
 * @property {string} schema_name
 * @property {string} table_group_id
 * @property {'A' | 'B' | 'D' | 'N' | 'T' | 'X'} general_type
 * @property {string} db_data_type
 * @property {string} functional_data_type
 * @property {string} datatype_suggestion
 * @property {string?} semantic_data_type
 * @property {string?} hygiene_issues
 * @property {string?} result_details
 * @property {string} profile_run_id
 * @property {number} profile_run_date
 * @property {string?} profiling_error
 * @property {number?} record_ct
 * @property {number?} value_ct
 * @property {number?} distinct_value_ct
 * @property {number?} null_value_ct
 *
 * @typedef SelectedItem
 * @type {ProfilingItem & { hygiene_issues: import('../data_profiling/data_profiling_utils.js').HygieneIssue[] }}
 *
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {string} run_id
 * @property {ProfilingItem[]} items
 * @property {object} filters
 * @property {string?} selected_id
 * @property {string?} selected_item
 * @property {Permissions} permissions
 * @property {number} page
 * @property {number} total_count
 * @property {number} page_size
 * @property {object[]} sort_state
 * @property {object} filter_options
 */
import van from '/app/static/js/van.min.js';
import { Table } from '/app/static/js/components/table.js';
import { Icon } from '/app/static/js/components/icon.js';
import { Select } from '/app/static/js/components/select.js';
import { DropdownButton } from '/app/static/js/components/dropdown_button.js';

import { Streamlit } from '/app/static/js/streamlit.js';
import { emitEvent, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { DataCharacteristicsCard } from '../data_profiling/data_characteristics.js';
import { ColumnDistributionCard } from '../data_profiling/column_distribution.js';
import { PotentialPIICard, HygieneIssuesCard } from '../data_profiling/data_issues.js';

const { div, span, h2 } = van.tags;

const TYPE_ICONS = {
    A: { icon: 'font_download', style: 'color: var(--blue)' },
    B: { icon: 'toggle_on', style: 'color: var(--green)' },
    D: { icon: 'calendar_month', style: 'color: var(--orange)' },
    N: { icon: 'pin', style: 'color: var(--purple)' },
    T: { icon: 'table_view', style: 'color: var(--secondary-text-color)' },
    X: { icon: 'question_mark', style: 'color: var(--secondary-text-color)' },
};

const TABLE_COLUMNS = [
    { name: 'type_icon', label: '', width: 32, align: 'center' },
    { name: 'table_name', label: 'Table', width: 180, sortable: true, overflow: 'hidden' },
    { name: 'column_name', label: 'Column', width: 180, sortable: true, overflow: 'hidden' },
    { name: 'db_data_type', label: 'Data Type', width: 130, sortable: true, overflow: 'hidden' },
    { name: 'semantic_data_type', label: 'Semantic Type', width: 150, sortable: true, overflow: 'hidden' },
    { name: 'hygiene_icon', label: 'Hygiene Issues', width: 130, align: 'center' },
    { name: 'result_details', label: 'Details', width: 180, overflow: 'hidden' },
];

const buildTableRow = (/** @type ProfilingItem */ item) => {
    const iconInfo = TYPE_ICONS[item.general_type] ?? TYPE_ICONS['X'];
    return {
        id: item.id,
        type_icon: Icon({ style: `${iconInfo.style}; font-size: 18px` }, iconInfo.icon),
        table_name: item.table_name ?? '',
        column_name: item.column_name ?? '',
        db_data_type: item.db_data_type ?? '',
        semantic_data_type: item.semantic_data_type ?? '',
        hygiene_icon: item.hygiene_issues === 'Yes'
            ? Icon({ style: 'color: var(--orange); font-size: 16px' }, 'warning')
            : '',
        result_details: item.result_details ?? '',
    };
};

const ExportMenu = (tableFilter, columnFilter, selectedRowId) => {
    return DropdownButton({
        icon: 'download',
        label: 'Export',
        items: () => {
            const items = [
                { label: 'All results', onclick: () => emitEvent('ExportAll', {}) },
                {
                    label: 'Filtered results',
                    onclick: () => emitEvent('ExportFiltered', {
                        payload: { table_name: tableFilter.rawVal, column_name: columnFilter.rawVal },
                    }),
                },
            ];
            if (selectedRowId.val) {
                items.push({
                    label: 'Selected results',
                    onclick: () => emitEvent('ExportSelected', { payload: selectedRowId.rawVal }),
                });
            }
            return items;
        },
    });
};

const ProfilingResults = (/** @type Properties */ props) => {
    loadStylesheet('profiling-results', stylesheet);

    const items = van.derive(() => getValue(props.items) ?? []);

    const selectedItemData = van.derive(() => {
        try { return JSON.parse(getValue(props.selected_item)); }
        catch { return null; }
    });

    // Pagination state from Python
    const currentPage = van.derive(() => getValue(props.page) ?? 0);
    const totalCount = van.derive(() => getValue(props.total_count) ?? 0);
    const pageSize = van.derive(() => getValue(props.page_size) ?? 500);

    // Filter options from Python
    const filterOptions = van.derive(() => getValue(props.filter_options) ?? {});

    const initialFilters = getValue(props.filters) ?? {};
    const tableFilter = van.state(initialFilters.table_name ?? null);
    const columnFilter = van.state(initialFilters.column_name ?? null);

    // Sort state initialized from Python
    const initialSortState = getValue(props.sort_state) ?? [];
    const sortColumns = van.state(
        initialSortState.length > 0
            ? initialSortState
            : [{ field: 'table_name', order: 'asc' }]
    );

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

    // Selected row data (looked up from full items list)
    const selectedRow = van.derive(() =>
        selectedRowId.val ? items.val.find(r => r.id === selectedRowId.val) ?? null : null
    );

    // Table rows (no client-side filtering/sorting — server handles it)
    const tableRows = van.derive(() => items.val.map(buildTableRow));

    const onSortChange = (newColumns) => {
        sortColumns.val = newColumns;
        emitEvent('SortChanged', { payload: { columns: newColumns } });
    };

    const tableSortOptions = van.derive(() => ({
        columns: sortColumns.val,
        onSortChange,
    }));

    const isInitiallySelected = (row, _) => row.id === selectedRowId.rawVal;
    const onRowsSelected = (idxs) => {
        if (idxs.length > 0) {
            const row = items.rawVal[idxs[0]];
            if (row && row.id !== selectedRowId.rawVal) {
                selectedRowId.val = row.id;
                emitEvent('RowSelected', { payload: row.id });
            }
        }
    };

    const onTableFilterChange = (value) => {
        tableFilter.val = value;
        columnFilter.val = null;
        selectedRowId.val = null;
        emitEvent('FilterChanged', { payload: { table_name: value, column_name: null } });
    };

    const onColumnFilterChange = (value) => {
        columnFilter.val = value;
        selectedRowId.val = null;
        emitEvent('FilterChanged', { payload: { table_name: tableFilter.rawVal, column_name: value } });
    };

    // Table header bar with export menu
    const tableHeader = div(
        { class: 'flex-row fx-align-center fx-gap-2 p-2' },
        div({ class: 'fx-flex' }),
        ExportMenu(tableFilter, columnFilter, selectedRowId),
    );

    const paginatorOptions = van.derive(() => ({
        totalItems: totalCount.val,
        currentPageIdx: currentPage.val,
        itemsPerPage: pageSize.val,
        pageSizeOptions: [100, 500, 1000],
        onPageChange: (pageIdx, newPerPage) => {
            if (newPerPage !== pageSize.rawVal) {
                emitEvent('PageChanged', { payload: { page: 0, page_size: newPerPage } });
            } else {
                emitEvent('PageChanged', { payload: { page: pageIdx } });
            }
        },
    }));

    // Pre-build the Table once
    const dataTable = Table(
        {
            columns: TABLE_COLUMNS,
            header: tableHeader,
            highDensity: true,
            dynamicWidth: true,
            height: '40vh',
            emptyState: div(
                { class: 'flex-row fx-justify-center empty-table-message' },
                span({ class: 'text-secondary' }, 'No profiling results found matching filters'),
            ),
            sort: tableSortOptions,
            paginator: paginatorOptions,
            selection: { onRowsSelected, isInitiallySelected },
        },
        tableRows,
    );

    return div(
        { 'data-testid': 'profiling-results', class: 'flex-column' },
        // Filters row
        div(
            { class: 'flex-row fx-gap-2 fx-align-flex-end mb-2 fx-flex-wrap' },
            () => Select({
                label: 'Table',
                value: tableFilter.val,
                options: tableOptions.val,
                testId: 'table-filter',
                style: 'min-width: 200px',
                onChange: onTableFilterChange,
                allowNull: true,
            }),
            () => Select({
                label: 'Column',
                value: columnFilter.val,
                options: columnOptions.val,
                testId: 'column-filter',
                style: 'min-width: 200px',
                onChange: onColumnFilterChange,
                allowNull: true,
            }),
        ),
        dataTable,
        // Detail panel
        div(
            { style: () => selectedRow.val ? 'margin-top: 16px' : 'display: none' },
            () => selectedRow.val
                ? div(
                    { class: 'tg-pr--detail flex-column fx-gap-2' },
                    div(
                        { class: 'mb-2' },
                        h2(
                            { class: 'tg-pr--title' },
                            span({ class: 'text-secondary' }, `${selectedRow.val.table_name} > `),
                            selectedRow.val.column_name,
                        ),
                    ),
                    DataCharacteristicsCard({ border: true }, selectedRow.val),
                    ColumnDistributionCard({ border: true, dataPreview: false }, selectedRow.val),
                    () => {
                        const si = selectedItemData.val;
                        if (!si || si.id !== selectedRowId.rawVal) return '';
                        if (!Array.isArray(si.hygiene_issues) || !si.hygiene_issues.length) return '';
                        return div(
                            PotentialPIICard({ border: true }, si),
                            HygieneIssuesCard({ border: true }, si),
                        );
                    },
                )
                : '',
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-pr--title {
    margin: 0;
    color: var(--primary-text-color);
    font-size: 18px;
    font-weight: 400;
}
.tg-pr--detail {
    border-top: 1px solid var(--border-color, #dddfe2);
    padding-top: 16px;
}
`);

export { ProfilingResults };

export default (component) => {
    const { data, setTriggerValue, parentElement } = component;

    Streamlit.enableV2(setTriggerValue);

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, ProfilingResults(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
