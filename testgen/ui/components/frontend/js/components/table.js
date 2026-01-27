/**
 * @import {VanState} from '../van.min.js';
 * 
 * @typedef Column
 * @type {object}
 * @property {string} name
 * @property {string} label
 * @property {number?} colspan
 * @property {number?} width
 * @property {boolean?} sortable
 * @property {('left' | 'center' | 'right')?} align
 * @property {('hidden' | 'visible')?} overflow
 * 
 * @typedef Sort
 * @type {object}
 * @property {string?} field
 * @property {('asc'|'desc')?} order
 * 
 * @typedef SelectonOptions
 * @type {object}
 * @property {boolean?} multi
 * @property {((rowIndexes: number[]) => void)?} onRowsSelected
 * 
 * @typedef SortOptions
 * @type {object}
 * @property {string?} field
 * @property {('asc'|'desc')?} order
 * @property {((a: Sort) => void)} onSortChange
 * 
 * @typedef PaginatorOptions
 * @type {object}
 * @property {number?} itemsPerPage
 * @property {number?} totalItems
 * @property {number?} currentPageIdx
 * @property {((a: number, b: number) => void)?} onPageChange
 * 
 * @typedef Options
 * @type {object}
 * @property {(Column[] | Column[][])} columns
 * @property {any?} header
 * @property {any?} emptyState
 * @property {string?} class
 * @property {string?} height
 * @property {string?} width
 * @property {boolean?} highDensity
 * @property {boolean?} dynamicWidth
 * @property {SortOptions?} sort
 * @property {PaginatorOptions?} paginator
 * @property {SelectonOptions?} selection
 */
import { getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';
import { Button } from './button.js';
import { Icon } from './icon.js';
import { Select } from './select.js';

const { colgroup, col, div, span, table, thead, th, tbody, tr, td } = van.tags;
const defaultItemsPerPage = 20;
const defaultHeight = 'calc(100% - 76.5px)';
const defaultWidth = '100%';

/**
 * @param {Options?} options
 * @param {...Row} rows
 * @returns {HTMLElement}
 */
const Table = (options, rows) => {
    loadStylesheet('table', stylesheet);

    const headerLines = van.derive(() => {
        const columns = getValue(options.columns);
        if (Array.isArray(columns[0])) {
            return columns;
        }
        return [columns];
    });
    const dataColumns = van.derive(() => getValue(headerLines)?.slice(-1)?.[0] ?? []);
    const widthSum = van.state(0);
    const columnWidths = [];

    van.derive(() => {
        for (let i = 0; i < dataColumns.val.length; i++) {
            const column = dataColumns.val[i];
            columnWidths[i] = columnWidths[i] ?? van.state(0);
            columnWidths[i].val = column.width;
            widthSum.val += column.width;
        }
        widthSum.val = widthSum.val || undefined;
    });

    const selectedRows = [];
    van.derive(() => {
        const rows_ = getValue(rows);
        rows_.forEach((_, idx) => {
            selectedRows[idx] = selectedRows[idx] ?? van.state(false)
            selectedRows[idx].val = false;
        });
    });
    van.derive(() => {
        const selectedRows_ = [];
        for (let i = 0; i < selectedRows.length; i++) {
            if (selectedRows[i].val) {
                selectedRows_.push(i);
            }
        }

        options.selection?.onRowsSelected?.(selectedRows_);
    });
    const onRowSelected = (idx) => {
        if (!options.selection?.multi) {
            for (const state of selectedRows) {
                state.val = false;
            }
        }

        if (options.selection?.onRowsSelected) {
            selectedRows[idx].val = !selectedRows[idx].val;
        }
    };


    const renderPaginator = van.derive(() => getValue(options.paginator) != undefined);
    const paginatorOptions = van.derive(() => {
        const p = getValue(options.paginator);
        return {
            itemsPerPage: p?.itemsPerPage ?? defaultItemsPerPage,
            totalItems: p?.totalItems ?? undefined,
            currentPageIdx: p?.currentPageIdx ?? 0,
            onPageChange: p?.onPageChange,
        };
    });

    const sortOptions = van.derive(() => {
        const s = getValue(options.sort);

        return {
            field: s?.field,
            order: s?.order,
            onSortChange: (columnName) => {
                let newSortOrder = 'desc';
                let columnNameOrClear = columnName;
                if (s?.field === columnName && s?.order === 'desc') {
                    newSortOrder = 'asc';
                } else if (s?.field === columnName && s?.order === 'asc') {
                    newSortOrder = null;
                    columnNameOrClear = null;
                }

                s?.onSortChange?.({field: columnNameOrClear, order: newSortOrder});
            },
        };
    });

    return div(
        {
            class: () => `tg-table flex-column border border-radius-1 ${getValue(options.highDensity) ? 'tg-table-high-density' : ''} ${getValue(options.dynamicWidth) ? 'tg-table-dynamic-width' : ''} ${options.onRowsSelected ? 'tg-table-hoverable' : ''}`,
            style: () => `height: ${getValue(options.height) ? getValue(options.height) + 'px' : defaultHeight};`,
        },
        options.header,
        div(
            {class: 'tg-table-scrollable flex-column fx-flex'},
            table(
                {
                    class: () => getValue(options.class) ?? '',
                    style: () => {
                        const dynamicWidth = getValue(options.dynamicWidth) ?? false;
                        let widthNumber = getValue(options.width) ?? widthSum.val;
                        if (widthNumber < window.innerWidth) {
                            widthNumber = window.innerWidth;
                        }
                        return `width: ${(widthNumber && dynamicWidth) ? widthNumber + 'px' : defaultWidth}; ${dynamicWidth ? 'table-layout: fixed;' : ''}`;
                    },
                },
                () => colgroup(
                    ...columnWidths.map((widthState) => col({style: `width: ${widthState.val}px;`})),
                ),
                () => thead(
                    getValue(headerLines).map((headerLine, idx, allHeaderLines) => {
                        const dynamicWidth = getValue(options.dynamicWidth) ?? false;
                        return tr(
                            ...getValue(headerLine).map((column, colIdx) =>
                                TableHeaderColumn(
                                    column,
                                    idx === allHeaderLines.length - 1,
                                    columnWidths,
                                    colIdx,
                                    dynamicWidth,
                                    sortOptions,
                                )
                            ),
                        );
                    })
                ),
                () => {
                    const rows_ = getValue(rows);
                    if (rows_.length <= 0 && options.emptyState) {
                        return tbody(
                            {class: 'tg-table-empty-state-body'},
                            tr(
                                td(
                                    {colspan: columnWidths.length},
                                    options.emptyState,
                                ),
                            ),
                        );
                    }
                    
                    return tbody(
                        rows_.map((row, idx) =>
                            tr(
                                {
                                    class: () => selectedRows[idx].val ? 'selected' : '',
                                    onclick: () => onRowSelected(idx),
                                },
                                ...getValue(dataColumns).map(column => TableCell(column, row, idx)),
                            )
                        ),
                    )
                },
            ),
        ),
        () => renderPaginator.val
            ? Paginatior(
                getValue(paginatorOptions).itemsPerPage,
                getValue(paginatorOptions).totalItems,
                getValue(paginatorOptions).currentPageIdx,
                getValue(options.highDensity),
                getValue(paginatorOptions).onPageChange,
            )
            : undefined,
    );
};

/**
 * @typedef SortOptionsB
 * @type {object}
 * @property {string?} field
 * @property {('asc'|'desc')?} order
 * @property {((field: string) => void)} onSortChange
 * 
 * @param {Column} column 
 * @param {boolean} isDataColumn
 * @param {VanState<number>[]} columnWidths
 * @param {number} columnIndex
 * @param {boolean} dynamicWidth
 * @param {VanState<SortOptionsB>} sortOptions
 */
const TableHeaderColumn = (
    column,
    isDataColumn,
    columnWidths,
    columnIndex,
    dynamicWidth,
    sortOptions,
) => {
    let startX, startWidth;

    const doDrag = (e) => {
        const newWidth = startWidth + (e.clientX - startX);
        if (newWidth > 50) {
            columnWidths[columnIndex].val = newWidth;
        }
    };

    const stopDrag = () => {
        document.removeEventListener('mousemove', doDrag);
        document.removeEventListener('mouseup', stopDrag);
        document.body.style.cursor = '';
        document.documentElement.style.userSelect = '';
        document.documentElement.style.pointerEvents = '';
    };

    const initDrag = (e) => {
        startX = e.clientX;
        startWidth = columnWidths[columnIndex].val;
        document.addEventListener('mousemove', doDrag);
        document.addEventListener('mouseup', stopDrag);
        document.body.style.cursor = 'col-resize';
        document.documentElement.style.userSelect = 'none';
        document.documentElement.style.pointerEvents = 'none';
    };

    const sortIcon = van.derive(() => {
        if (!isDataColumn || !column.sortable) {
            return null;
        }
        
        const isSorted = sortOptions.val.field === column.name;
        return (
            isSorted
                ? Icon({size: 13}, sortOptions.val.order === 'desc' ? 'south' : 'north')
                : null
        );
    });

    return th(
        {
            class: `${isDataColumn ? 'tg-table-column' : 'tg-table-helper-column'} text-small text-secondary ${column.name} ${column.sortable ? 'clickable' : ''}`,
            align: column.align,
            width: column.width,
            colspan: column.colspan ?? 1,
            'data-testid': column.name,
            style: `overflow-x: ${column.overflow ?? 'hidden'}`,
            onclick: () => {
                if (isDataColumn && column.sortable) {
                    sortOptions.val.onSortChange(column.name);
                }
            },
        },
        () => div(
            {class: 'flex-row fx-gap-2', style: 'display: inline-flex'},
            span(column.label),
            sortIcon.val,
        ),
        (
            isDataColumn && dynamicWidth
                ? div(
                    {class: 'tg-column-resizer', onmousedown: initDrag},
                    div()
                )
                : null
        ),
    );
};

/**
 * 
 * @param {Column} column
 * @param {Row} row
 * @param {number} index
 */
const TableCell = (column, row, index) => {
    return td(
        {
            class: `tg-table-cell ${column.name}`,
            align: column.align,
            width: column.width,
            colspan: column.colspan ?? 1,
            'data-testid': `table-cell:${index},${column.name}`,
            style: `overflow-x: ${column.overflow ?? 'hidden'}`,
        },
        getValue(row[column.name]),
    );
};

/**
 * 
 * @param {number} itemsPerPage
 * @param {number?} totalItems
 * @param {number} currentPageIdx
 * @param {boolean?} highDensity
 * @param {((number, number) => void)?} onPageChange
 * @returns {HTMLElement}
 */
const Paginatior = (
    itemsPerPage,
    totalItems,
    currentPageIdx,
    highDensity,
    onPageChange,
) => {
    const pageStart = itemsPerPage * currentPageIdx + 1;
    const pageEnd = Math.min(pageStart + itemsPerPage - 1, totalItems);
    const lastPage = (Math.floor(totalItems / itemsPerPage) + (totalItems % itemsPerPage > 0) - 1);

    return div(
        {class: `tg-table-paginator flex-row fx-justify-content-flex-end ${highDensity ? '' : 'p-1'} text-secondary`},
        span({class: 'mr-2'}, 'Rows per page:'),
        Select({
            triggerStyle: 'inline',
            testId: 'items-per-page',
            value: itemsPerPage,
            options: [
                {label: '20', value: 20},
                {label: '50', value: 50},
                {label: '100', value: 100},
            ],
            portalPosition: 'top',
            onChange: (value) => onPageChange(currentPageIdx, parseInt(value)),
        }),
        span({class: 'mr-6'}, ''),
        span({class: 'mr-6'}, `${pageStart}-${pageEnd} of ${totalItems ?? '∞'}`),
        Button({
            type: 'icon',
            icon: 'first_page',
            iconSize: 24,
            style: 'color: var(--secondary-text-color)',
            disabled: currentPageIdx === 0,
            onclick: () => onPageChange(0, itemsPerPage),
        }),
        Button({
            type: 'icon',
            icon: 'chevron_left',
            iconSize: 24,
            style: 'color: var(--secondary-text-color)',
            disabled: currentPageIdx === 0,
            onclick: () => onPageChange(currentPageIdx - 1, itemsPerPage),
        }),
        Button({
            type: 'icon',
            icon: 'chevron_right',
            iconSize: 24,
            style: 'color: var(--secondary-text-color)',
            disabled: pageEnd >= totalItems,
            onclick: () => onPageChange(currentPageIdx + 1, itemsPerPage),
        }),
        Button({
            type: 'icon',
            icon: 'last_page',
            iconSize: 24,
            style: 'color: var(--secondary-text-color)',
            disabled: pageEnd >= totalItems,
            onclick: () => onPageChange(lastPage, itemsPerPage),
        }),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-table {
    background: var(--dk-card-background);
}

.tg-table > .tg-table-scrollable {
    overflow: auto;
    border-radius: 4px;
}

.tg-table > .tg-table-scrollable > table {
    border-collapse: collapse;
    border-color: var(--border-color);
}

.tg-table > .tg-table-scrollable > table:has(.tg-table-empty-state-body) {
    height: 100%;
}

.tg-table > .tg-table-scrollable > table > thead {
    border-bottom: var(--button-stroked-border);
    position: sticky;
    top: 0;
    background: var(--dk-card-background); /* Ensure header background is solid when sticky */
    z-index: 1; /* Ensure header is above scrolling content */
}

.tg-table > .tg-table-scrollable > table > thead th {
    font-weight: normal;
}

.tg-table > .tg-table-scrollable > table > thead th > div {
    text-overflow: ellipsis;
    white-space: nowrap;
    overflow-x: hidden;
}

.tg-table > .tg-table-scrollable > table > thead th.tg-table-helper-column {
    padding: 0px;
}

.tg-table > .tg-table-scrollable > table > thead th.tg-table-column {
    padding: 4px 8px;
    height: 32px;
    text-transform: uppercase;
    position: relative; /* Needed for absolute positioning of resizer */
}

.tg-table > .tg-table-scrollable > table > thead th .tg-column-resizer {
    position: absolute;
    right: 0;
    top: 0;
    width: 5px;
    height: 90%;
    background: transparent;
    cursor: col-resize;
    z-index: 2; /* Ensure resizer is above other content */
}

.tg-table > .tg-table-scrollable > table > thead th .tg-column-resizer > div {
    height: 100%;
    width: 1px;
    background: var(--border-color);
}

.tg-table > .tg-table-scrollable > table > tbody > tr {
    height: 40px;
}

.tg-table > .tg-table-scrollable > table > tbody > tr:not(:last-of-type) {
    border-bottom: var(--button-stroked-border);
}

.tg-table > .tg-table-scrollable > table > tbody > tr.selected {
    background-color: var(--table-selection-color);
}

.tg-table > .tg-table-scrollable > table .tg-table-cell {
    padding: 4px 8px;
    height: 40px;
}

.tg-table > .tg-table-paginator {
    border-top: var(--button-stroked-border);
}

.tg-table.tg-table-high-density > .tg-table-scrollable > table > thead th.tg-table-column {
    padding: 0px 8px;
    height: 27px;
}

.tg-table.tg-table-high-density > .tg-table-scrollable > table .tg-table-cell {
    padding: 0px 8px;
    height: 27px;
}

.tg-table.tg-table-dynamic-width > .tg-table-scrollable > table {
    table-layout: fixed;
}

.tg-table.tg-table-dynamic-width > .tg-table-scrollable > table > tbody td {
    text-overflow: ellipsis;
    white-space: nowrap;
}

.tg-table.tg-table-hoverable > .tg-table-scrollable > table > tbody tr:hover {
    background-color: var(--table-hover-color);
}
`);

export { Table, TableHeaderColumn };
