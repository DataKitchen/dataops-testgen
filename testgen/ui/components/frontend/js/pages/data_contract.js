// cache-bust: v2
/**
 * Data Contract page — VanJS component.
 *
 * @typedef TermItem
 * @type {object}
 * @property {string} name
 * @property {string} value
 * @property {string} source   - "ddl" | "profiling" | "governance" | "test"
 * @property {string} verif    - "db_enforced" | "tested" | "monitored" | "observed" | "declared"
 * @property {string?} rule_id
 * @property {string?} status  - "passing" | "warning" | "failing" | "not run"
 *
 * @typedef ColumnData
 * @type {object}
 * @property {string} name
 * @property {string} type
 * @property {boolean} is_pk
 * @property {boolean} is_fk
 * @property {string} status  - "clean" | "passing" | "warning" | "failing"
 * @property {TermItem[]} static_terms
 * @property {TermItem[]} live_terms
 *
 * @typedef TableData
 * @type {object}
 * @property {string} name
 * @property {number} column_count
 * @property {TermItem[]} table_terms
 * @property {ColumnData[]} columns
 *
 * @typedef MatrixRow
 * @type {object}
 * @property {string} table
 * @property {string} column
 * @property {string} type
 * @property {string} not_null
 * @property {string} key
 * @property {string?} tests_status
 * @property {number} tests_count
 * @property {string?} anomaly_likelihood
 * @property {number} anomaly_count
 * @property {string} classification
 * @property {boolean} cde
 * @property {string[]} tiers
 *
 * @typedef SuiteScope
 * @type {object}
 * @property {string[]} included
 * @property {string[]} excluded
 * @property {number}   total
 *
 * @typedef Properties
 * @type {object}
 * @property {string} table_group_name
 * @property {object} meta
 * @property {string} yaml_content
 * @property {object} health
 * @property {SuiteScope} suite_scope
 * @property {MatrixRow[]} coverage_matrix
 * @property {object} gaps
 * @property {TableData[]} tables
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange } from '../utils.js';
import { Button } from '../components/button.js';

const { div, span, h2, h3, pre, table, thead, tbody, tr, th, td, input, label, p, ul, li, code, hr, a } = van.tags;

// ── Source → chip CSS class ──────────────────────────────────────────────────
const SOURCE_CLASS = { ddl: 'ddl', profiling: 'prof', governance: 'gov', test: 'tst' };
const SOURCE_LABEL = { ddl: 'DDL', profiling: 'Profiling', governance: 'Governance', test: 'Test' };

// ── Verification badge labels / icons ────────────────────────────────────────
const VERIF_META = {
    db_enforced: { icon: '🏛️', label: 'Enforced',  cls: 'badge-enforced' },
    tested:      { icon: '⚡',  label: 'Tested',    cls: 'badge-tested'   },
    monitored:   { icon: '📡', label: 'Monitored', cls: 'badge-mon'      },
    observed:    { icon: '📸', label: 'Observed',  cls: 'badge-obs'      },
    declared:    { icon: '🏷️', label: 'Declared',  cls: 'badge-decl'     },
};

const TIER_META = {
    db_enforced: { label: 'DB Enforced', cls: 'tier-badge db'   },
    tested:      { label: 'Tested',      cls: 'tier-badge test' },
    monitored:   { label: 'Monitored',   cls: 'tier-badge mon'  },
    observed:    { label: 'Observed',    cls: 'tier-badge obs'  },
    declared:    { label: 'Declared',    cls: 'tier-badge decl' },
};

// ── Small helpers ─────────────────────────────────────────────────────────────

const mat = (name, size = 16) =>
    span({ class: 'material', style: `font-size:${size}px` }, name);

const statusClass = (s) =>
    ({ passing: 'pass', warning: 'warn', failing: 'fail', error: 'fail' }[s] ?? 'none');

// ── Term chip ────────────────────────────────────────────────────────────────

// Format ODCS camelCase type to readable label: "notNull" → "Not Null"
const formatTestType = (t) =>
    t ? t.replace(/([A-Z])/g, ' $1').trim().replace(/^./, (s) => s.toUpperCase()) : '';

// Selection mode state — shared across all term chips and the filter bar
const _selectionMode = van.state(false);
const _selectedIds = van.state(new Set());    // Set<termKey>
const _confirmingDelete = van.state(false);   // true = showing "Are you sure?" prompt
const _flashBtn = van.state('');              // 'visible' | 'context' | '' for button flash
const _selectionHint = van.state('');         // brief status message shown in the bulk bar
// Registry: termKey → full term info for delete payload (populated by TermChip on creation)
const _termInfoByKey = new Map();

const TermChip = (term, tableName, colName) => {
    const srcCls = SOURCE_CLASS[term.source] || 'obs';
    const srcLabel = SOURCE_LABEL[term.source] || term.source;
    const verif = VERIF_META[term.verif] || { icon: '', label: term.verif, cls: 'badge-obs' };
    const isLive = term.source === 'test' || term.source === 'monitor';
    const status = term.status;
    const statusCls = status ? statusClass(status) : null;

    // Every chip is selectable — use rule_id when available, else generate a stable key
    const termKey = term.rule_id || `${term.source}|${term.name}|${String(term.value)}|${tableName}|${colName}`;
    // Register full term info for use in the delete payload
    _termInfoByKey.set(termKey, {
        term_key:    termKey,
        rule_id:     term.rule_id || '',
        source:      term.source,
        name:        term.name,
        value:       String(term.value || ''),
        table:       tableName,
        col:         colName,
        anomaly_type: term.anomaly_type || '',
    });

    // Only hygiene/anomaly terms (verif=monitored) skip the detail dialog.
    const hasDetail = term.verif !== 'monitored';

    // Attribute label shown next to source in the header — same pattern for all chip types
    const testTypeLabel = isLive ? formatTestType(term.test_type || '') : '';
    const testName = isLive ? (term.test_name || '') : '';
    const attrLabel = isLive
        ? (testTypeLabel && testTypeLabel.toLowerCase() !== testName.toLowerCase() ? testTypeLabel : term.name)
        : (term.name || '');

    // Static chip element — selection state handled via direct DOM class manipulation
    const chipCls = `term-chip ${srcCls} term-chip--clickable`;
    const attrs = { class: chipCls, 'data-term-key': termKey };

    attrs.onclick = (e) => {
        e.stopPropagation();
        if (_selectionMode.val) {
            const next = new Set(_selectedIds.val);
            if (next.has(termKey)) next.delete(termKey);
            else next.add(termKey);
            _selectedIds.val = next;
            // Immediate visual update on the clicked chip (derive fires async)
            const chip = e.currentTarget;
            const isSel = next.has(termKey);
            chip.classList.toggle('term-chip--selected', isSel && !_confirmingDelete.val);
            chip.classList.toggle('term-chip--deleting', isSel && _confirmingDelete.val);
            const cb = chip.querySelector('input[type=checkbox]');
            if (cb) cb.checked = isSel;
        } else if (hasDetail) {
            emitEvent('TermDetailClicked', { payload: { term, tableName, colName } });
        }
    };

    return div(
        attrs,
        // Checkbox in DOM for every chip; JS shows/hides via _syncDomToState
        div(
            {
                class: 'term-chip__checkbox',
                onclick: (e) => {
                    e.stopPropagation();
                    e.currentTarget.closest('.term-chip')?.dispatchEvent(new MouseEvent('click', { bubbles: false }));
                },
            },
            input({ type: 'checkbox' }),
        ),
        div(
            { class: 'term-chip__header' },
            span({ class: 'term-chip__src' }, srcLabel),
            attrLabel ? span({ class: 'term-chip__attr' }, `· ${attrLabel}`) : '',
        ),
        span({ class: 'term-chip__val' }, term.value),
        div(
            { class: 'dc-chip-footer' },
            span({ class: `term-chip__badge ${verif.cls}` }, `${verif.icon} ${verif.label}`),
            isLive && statusCls && statusCls !== 'none'
                ? span({ class: `status-pill ${statusCls}` }, status)
                : '',
        ),
    );
};

// ── Pending-deletion ghost chip ───────────────────────────────────────────────

const DeletedTermChip = (term) => {
    const srcCls = SOURCE_CLASS[term.source] || 'obs';
    const srcLabel = SOURCE_LABEL[term.source] || term.source;
    const verif = VERIF_META[term.verif] || { icon: '', label: term.verif, cls: 'badge-obs' };
    return div(
        { class: `term-chip ${srcCls} term-chip--deleted`, title: 'Pending deletion — will be removed when you save' },
        div(
            { class: 'term-chip__header' },
            span({ class: 'term-chip__src' }, srcLabel),
        ),
        span({ class: 'term-chip__val' }, term.name),
        div(
            { class: 'dc-chip-footer' },
            span({ class: `term-chip__badge ${verif.cls}` }, `${verif.icon} ${verif.label}`),
            span({ class: 'term-chip__deleted-label' }, 'deleted'),
        ),
    );
};

// ── Governance add/edit button ────────────────────────────────────────────────

const GovernanceButton = (col, tableName) => {
    const hasGov = [...col.static_terms, ...col.live_terms].some((c) => c.source === 'governance');
    return div(
        {
            class: 'gov-btn',
            title: hasGov ? 'Edit governance metadata' : 'Add governance metadata',
            onclick: (e) => {
                e.stopPropagation();
                emitEvent('GovernanceEditClicked', {
                    payload: { columnId: col.column_id, tableName, colName: col.name },
                });
            },
        },
        span({ class: 'material', style: 'font-size:13px;' }, hasGov ? 'edit' : 'add'),
        hasGov ? ' Edit governance' : ' Add governance',
    );
};

// ── Column row ────────────────────────────────────────────────────────────────

const ColumnRow = (col, tableName) => {
    const statusIndicator = col.status === 'failing' ? ' ❌' : col.status === 'warning' ? ' ⚠️' : '';
    return div(
        { class: 'col-row' },
        div(
            { class: 'col-header' },
            span({ class: 'col-name-link' }, col.name + statusIndicator),
            span({ class: 'col-type' }, col.type || ''),
            col.is_pk ? span({ class: 'key-badge' }, mat('key', 13), ' PK') : '',
            col.is_fk ? span({ class: 'key-badge' }, mat('call_made', 13), ' FK') : '',
            GovernanceButton(col, tableName),
        ),
        div(
            { class: 'terms-row' },
            ...col.static_terms.map((c) => TermChip(c, tableName, col.name)),
            ...col.live_terms.map((c) => TermChip(c, tableName, col.name)),
            ...(col.pending_delete_terms || []).map((c) => DeletedTermChip(c)),
        ),
    );
};

// ── Table-level terms row ────────────────────────────────────────────────────

const TableTermsRow = (tableTerms, tableName) => {
    if (!tableTerms || !tableTerms.length) return '';
    return div(
        { class: 'col-row table-terms-row' },
        div(
            { class: 'col-header' },
            span({ class: 'col-name-link table-level-label' }, mat('table_rows', 13), ' Table-level'),
        ),
        div(
            { class: 'terms-row' },
            ...tableTerms.map((c) => TermChip(c, tableName, '')),
        ),
    );
};

// ── Table section ─────────────────────────────────────────────────────────────

const TableSection = (tableData, startOpen = false) => {
    const open = van.state(startOpen);
    const tblTermCount = (tableData.table_terms || []).length;
    const colTermCount = tableData.columns.reduce(
        (sum, col) => sum + col.static_terms.length + col.live_terms.length, 0,
    );
    return div(
        { class: 'table-section' },
        div(
            {
                class: 'table-section-header',
                onclick: () => { open.val = !open.val; },
            },
            mat('table_rows', 22),
            span({ class: 'ts-name' }, tableData.name),
            div({ class: 'ts-meta' },
                span({ class: 'count-badge' }, `${tableData.column_count} column${tableData.column_count !== 1 ? 's' : ''}`),
                () => !open.val ? span({ class: 'count-badge count-badge--table' }, `${tblTermCount} table-level term${tblTermCount !== 1 ? 's' : ''}`) : '',
                () => !open.val ? span({ class: 'count-badge count-badge--terms' }, `${colTermCount} column-level term${colTermCount !== 1 ? 's' : ''}`) : '',
            ),
            span({ class: () => `table-section-chevron${open.val ? ' open' : ''}` }, 'expand_more'),
        ),
        () => open.val
            ? div(
                TableTermsRow(tableData.table_terms || [], tableData.name),
                ...tableData.columns.map((col) => ColumnRow(col, tableData.name)),
              )
            : '',
    );
};

// ── Terms detail tab ─────────────────────────────────────────────────────────

// Collect all selectable rule_ids from a filtered table list
// Collect term keys for all terms across a filtered table list
const _collectAllTermKeys = (filteredTables) => {
    const keys = [];
    const addTerm = (term, tableName, colName) => {
        const k = term.rule_id || `${term.source}|${term.name}|${String(term.value)}|${tableName}|${colName}`;
        keys.push(k);
        // Also register in _termInfoByKey so confirmDelete can build the full payload
        // even for terms that are off-screen (not rendered as DOM chips).
        if (!_termInfoByKey.has(k)) {
            _termInfoByKey.set(k, {
                term_key:    k,
                rule_id:     term.rule_id || '',
                source:      term.source,
                name:        term.name,
                value:       String(term.value || ''),
                table:       tableName,
                col:         colName,
                anomaly_type: term.anomaly_type || '',
            });
        }
    };
    for (const t of filteredTables) {
        for (const term of (t.table_terms || [])) addTerm(term, t.name, '');
        for (const col of t.columns) {
            for (const term of (col.static_terms || [])) addTerm(term, t.name, col.name);
            for (const term of (col.live_terms   || [])) addTerm(term, t.name, col.name);
        }
    }
    return keys;
};

const TermsDetail = (tables, activeFilter) => {
    const grandTotal = tables.reduce(
        (sum, t) => sum + t.columns.reduce(
            (s, col) => s + col.static_terms.length + col.live_terms.length, 0,
        ), 0,
    );


    // ── DOM sync: single source of truth for all chip visual state ──────────────
    // Called after entering/exiting selection mode AND after any filter change
    // (filter changes cause VanJS to recreate chip elements, losing inline styles).
    const _syncDomToState = () => {
        const inSel = _selectionMode.val;
        const selected = _selectedIds.val;
        const confirming = _confirmingDelete.val;

        // Show/hide every checkbox
        document.querySelectorAll('.term-chip__checkbox').forEach((el) => {
            el.style.cssText = inSel
                ? 'display:flex;align-items:center;justify-content:center;'
                : 'display:none;';
        });

        // Re-apply selected / deleting highlight on all chips
        document.querySelectorAll('.term-chip[data-term-key]').forEach((el) => {
            const isSel = selected.has(el.dataset.termKey);
            el.classList.toggle('term-chip--selected', isSel && !confirming);
            el.classList.toggle('term-chip--deleting', isSel && confirming);
            const cb = el.querySelector('input[type=checkbox]');
            if (cb) cb.checked = isSel;
        });
    };

    // Re-sync DOM after filter changes while in selection mode
    van.derive(() => {
        void activeFilter.val;           // register dependency
        void _selectionMode.val;
        void _selectedIds.val;
        void _confirmingDelete.val;
        setTimeout(_syncDomToState, 0);  // defer until VanJS finishes re-rendering chips
    });

    const enterSelectionMode = () => {
        _selectionMode.val = true;
        document.querySelector('.terms-detail-wrap')?.classList.add('selection-mode-active');
        setTimeout(_syncDomToState, 0);
    };

    const exitSelectionMode = () => {
        _selectionMode.val = false;
        _selectedIds.val = new Set();
        _confirmingDelete.val = false;
        _flashBtn.val = '';
        _selectionHint.val = '';
        document.querySelector('.terms-detail-wrap')?.classList.remove('selection-mode-active');
        _syncDomToState();
        _termInfoByKey.clear();
    };

    // Compute the filtered table list (same logic as the render below) for "Select All In Context"
    const getFilteredTables = () => {
        const filter = activeFilter.val;
        if (filter === 'all') return tables;
        const COVERED_VERIFS = new Set(['tested', 'monitored', 'declared']);
        const FAILING_STATUS  = new Set(['failing', 'error']);
        const termFilter = (c) => {
            if (filter === 'uncovered') return false;
            if (filter === 'failing')   return c.kind === 'live' && FAILING_STATUS.has(c.status);
            if (filter === 'anomalies') return c.kind === 'live' && c.source === 'profiling';
            return c.verif === filter;
        };
        const colFilter = (col) => {
            if (filter === 'uncovered') {
                const allTerms = [...(col.static_terms || []), ...(col.live_terms || [])];
                return !allTerms.some((c) => COVERED_VERIFS.has(c.verif));
            }
            return (col.static_terms || []).filter(termFilter).length > 0
                || (col.live_terms || []).filter(termFilter).length > 0;
        };
        return tables
            .map((t) => ({
                ...t,
                table_terms: filter === 'uncovered' ? [] : (t.table_terms || []).filter(termFilter),
                columns: t.columns
                    .filter(colFilter)
                    .map((col) => filter === 'uncovered' ? col : {
                        ...col,
                        static_terms: (col.static_terms || []).filter(termFilter),
                        live_terms:   (col.live_terms   || []).filter(termFilter),
                    }),
            }))
            .filter((t) => t.table_terms.length > 0 || t.columns.length > 0);
    };

    const _setHint = (msg) => {
        _selectionHint.val = msg;
        setTimeout(() => { _selectionHint.val = ''; }, 2500);
    };

    const selectAllInContext = () => {
        const ids = _collectAllTermKeys(getFilteredTables());
        if (!ids.length) {
            _setHint('No terms in this view');
            _flashBtn.val = 'context';
            setTimeout(() => { _flashBtn.val = ''; }, 700);
            return;
        }
        _selectedIds.val = new Set(ids);
        _confirmingDelete.val = false;
        _selectionHint.val = '';
        _flashBtn.val = 'context';
        setTimeout(() => { _flashBtn.val = ''; }, 700);
        _syncDomToState();
    };

    const selectAllVisible = () => {
        const vh = window.innerHeight || document.documentElement.clientHeight;
        const prev = _selectedIds.val;
        const next = new Set(prev);
        document.querySelectorAll('.term-chip[data-term-key]').forEach((el) => {
            const r = el.getBoundingClientRect();
            if (r.top < vh && r.bottom > 0) next.add(el.dataset.termKey);
        });
        if (next.size === prev.size) {
            _setHint('No terms visible — scroll to see more');
            _flashBtn.val = 'visible';
            setTimeout(() => { _flashBtn.val = ''; }, 700);
            return;
        }
        _selectedIds.val = next;
        _confirmingDelete.val = false;
        _selectionHint.val = '';
        _flashBtn.val = 'visible';
        setTimeout(() => { _flashBtn.val = ''; }, 700);
        _syncDomToState();
    };

    const requestDelete = () => {
        if (!_selectedIds.val.size) return;
        _confirmingDelete.val = true;
        _syncDomToState();
    };

    const confirmDelete = () => {
        const terms = [..._selectedIds.val].map((k) => _termInfoByKey.get(k)).filter(Boolean);
        emitEvent('BulkDeleteTermsClicked', { payload: { terms } });
        exitSelectionMode();
    };

    const cancelConfirm = () => {
        _confirmingDelete.val = false;
        _syncDomToState();
    };

    return div(
        { class: 'terms-detail-wrap' },
        div(
            { class: 'section-header' },
            div(
                { class: 'section-title' },
                mat('list_alt'), ' Data Contract Terms Detail',
                span({ style: 'font-weight: 300; font-size: 0.85em; color: var(--caption-text-color); margin-left: 6px;' }, `(${grandTotal} total terms)`),
            ),
            div(
                { class: 'filter-pills' },
                span({ class: 'dc-label' }, 'Filter:'),
                span(
                    {
                        class: () => `filter-pill ${activeFilter.val === 'all' ? 'active' : ''}`,
                        onclick: () => { activeFilter.val = 'all'; },
                    },
                    'All',
                ),
                ...['db_enforced', 'tested', 'monitored', 'observed', 'declared'].map((verif) => {
                    const meta = VERIF_META[verif] || { icon: '', label: verif, cls: 'badge-obs' };
                    return span(
                        {
                            class: () => `filter-pill filter-pill--verif filter-pill--${meta.cls} ${activeFilter.val === verif ? 'active' : ''}`,
                            onclick: () => { activeFilter.val = verif; },
                        },
                        `${meta.icon} ${meta.label}`,
                    );
                }),
                () => _selectionMode.val
                    ? ''
                    : span(
                        {
                            class: 'filter-pill select-mode-btn',
                            title: 'Select multiple test terms to delete',
                            onclick: enterSelectionMode,
                        },
                        mat('checklist', 13), ' Select',
                      ),
            ),
        ),
        // ── Bulk action bar (visible only in selection mode) ──────────────────
        () => _selectionMode.val
            ? div(
                { class: () => `bulk-action-bar${_confirmingDelete.val ? ' bulk-action-bar--confirming' : ''}` },
                // ── count ──
                span({ class: 'bulk-action-count' }, () => `${_selectedIds.val.size} selected`),
                // ── hint message (shown briefly when no selectable terms found) ──
                () => _selectionHint.val
                    ? span({ class: 'bulk-action-hint' }, mat('info', 13), ` ${_selectionHint.val}`)
                    : '',
                // ── select-all buttons (hidden when confirming) ──
                () => _confirmingDelete.val ? '' : span(
                    {
                        class: () => `bulk-action-btn${_flashBtn.val === 'visible' ? ' bulk-action-btn--flashing' : ''}`,
                        onclick: selectAllVisible,
                        title: 'Select terms currently visible in the viewport',
                    },
                    mat('select_all', 13), ' Select all visible',
                ),
                () => _confirmingDelete.val ? '' : span(
                    {
                        class: () => `bulk-action-btn${_flashBtn.val === 'context' ? ' bulk-action-btn--flashing' : ''}`,
                        onclick: selectAllInContext,
                        title: 'Select all test terms matching the current filter across the entire contract',
                    },
                    mat('done_all', 13), ' Select all in context',
                ),
                // ── delete / confirm buttons ──
                () => !_confirmingDelete.val && _selectedIds.val.size > 0
                    ? span(
                        { class: 'bulk-action-btn bulk-action-btn--delete', onclick: requestDelete },
                        mat('delete', 13), ' Delete contract terms',
                      )
                    : '',
                () => _confirmingDelete.val
                    ? span({ class: 'bulk-action-confirm__msg' },
                        mat('warning', 14), ` Delete ${_selectedIds.val.size} contract term${_selectedIds.val.size !== 1 ? 's' : ''}? This cannot be undone.`,
                      )
                    : '',
                () => _confirmingDelete.val
                    ? span({ class: 'bulk-action-btn bulk-action-btn--confirm-yes', onclick: confirmDelete },
                        mat('delete_forever', 13), ' Yes, delete',
                      )
                    : '',
                // ── cancel / no-keep ──
                () => _confirmingDelete.val
                    ? span({ class: 'bulk-action-btn bulk-action-btn--cancel', onclick: cancelConfirm }, 'No, keep')
                    : span({ class: 'bulk-action-btn bulk-action-btn--cancel', onclick: exitSelectionMode }, 'Cancel'),
              )
            : '',
        () => {
            const filter = activeFilter.val;
            if (filter === 'all') {
                return div(...tables.map((t, i) => TableSection(t, i === 0)));
            }

            const COVERED_VERIFS = new Set(['tested', 'monitored', 'declared']);
            const FAILING_STATUS  = new Set(['failing', 'error']);

            const termFilter = (c) => {
                if (filter === 'uncovered') return false; // handled at column level
                if (filter === 'failing')   return c.kind === 'live' && FAILING_STATUS.has(c.status);
                if (filter === 'anomalies') return c.kind === 'live' && c.source === 'profiling';
                return c.verif === filter; // verif-level filters
            };

            const colFilter = (col) => {
                if (filter === 'uncovered') {
                    // uncovered = column has NO tested/monitored/declared terms
                    const allTerms = [...(col.static_terms || []), ...(col.live_terms || [])];
                    return !allTerms.some((c) => COVERED_VERIFS.has(c.verif));
                }
                const sc = (col.static_terms || []).filter(termFilter);
                const lc = (col.live_terms   || []).filter(termFilter);
                return sc.length > 0 || lc.length > 0;
            };

            const filtered = tables
                .map((t) => {
                    const table_terms = filter === 'uncovered'
                        ? []
                        : (t.table_terms || []).filter(termFilter);
                    const cols = t.columns
                        .filter(colFilter)
                        .map((col) => filter === 'uncovered' ? col : {
                            ...col,
                            static_terms: (col.static_terms || []).filter(termFilter),
                            live_terms:   (col.live_terms   || []).filter(termFilter),
                        });
                    return { ...t, table_terms, columns: cols };
                })
                .filter((t) => t.table_terms.length > 0 || t.columns.length > 0);

            if (!filtered.length) {
                return div({ class: 'dc-empty' }, 'No terms match the current filter.');
            }
            return div(...filtered.map((t, i) => TableSection(t, i === 0)));
        },
    );
};

// ── Coverage matrix tab ───────────────────────────────────────────────────────

// Tier definitions — order: most enforced first
const COVERAGE_TIERS = [
    { key: 'tg_enforced', label: '⚡ TestGen Enforced', color: '#22c55e', textColor: '#4ade80', tier: 'tg'  },
    { key: 'db_enforced', label: '🏛 DB Enforced',        color: '#818cf8', textColor: '#a5b4fc', tier: 'db'  },
    { key: 'unenforced',  label: '📋 Unenforced',         color: '#f59e0b', textColor: '#fbbf24', tier: 'unf' },
    { key: 'uncovered',   label: '◯ Uncovered',          color: '#4b5563', textColor: '#6b7280', tier: 'none'},
];

const TIER_DOT_COLOR = { tg: '#22c55e', db: '#818cf8', unf: '#f59e0b', none: '#374151' };

// Sub-columns inside each enforcement group — determines matrix table columns
const MATRIX_COLS = [
    { key: 'tested', label: 'Tests',    group: 'tg',  groupLabel: '⚡ TestGen' },
    { key: 'mon',    label: 'Monitors', group: 'tg',  groupLabel: null },
    { key: 'db',     label: 'DDL',      group: 'db',  groupLabel: '🏛 DB Enforced' },
    { key: 'obs',    label: 'Observed', group: 'unf', groupLabel: '📋 Unenforced' },
    { key: 'decl',   label: 'Declared', group: 'unf', groupLabel: null },
];

const fmtCount = (n) => (n > 0 ? String(n) : '—');

// Shared four-tier progress bars component — used in HealthGrid card and matrix top
const CoverageTierBars = (health, activeFilter) => {
    const n = health.n_elements || 1;
    return div(
        { class: 'tier-bars' },
        ...COVERAGE_TIERS.map((t) => {
            const count = health[t.key] || 0;
            const pct   = Math.round(100 * count / n);
            const rowStyle = activeFilter
                ? () => `opacity:${activeFilter.val === 'all' || activeFilter.val === t.tier ? 1 : 0.3};transition:opacity 0.15s`
                : '';
            return div(
                {
                    class: 'tier-bar-row',
                    style: rowStyle,
                    onclick: activeFilter
                        ? () => { activeFilter.val = activeFilter.val === t.tier ? 'all' : t.tier; }
                        : null,
                    title: activeFilter ? `Filter to ${t.label}` : '',
                },
                span({ class: 'tier-bar-label', style: `color:${t.textColor}` }, t.label),
                div({ class: 'tier-bar-track' },
                    div({ class: 'tier-bar-fill', style: `width:${pct}%;background:${t.color}` }),
                ),
                span({ class: 'tier-bar-count', style: `color:${t.textColor}` }, `${count} / ${health.n_elements || 0}`),
            );
        }),
    );
};

const MatrixTableSection = (tableName, rows, startOpen, totals, tierCounts, activeMatrixTier) => {
    const open = van.state(startOpen);

    // Tier pills scoped to this table (shown only when closed)
    const TierPills = () => div(
        { class: 'ts-tier-pills', style: () => open.val ? 'visibility:hidden' : 'visibility:visible' },
        span({ class: 'ts-element-count' }, `${rows.length} elements:`),
        ...COVERAGE_TIERS.map((t) =>
            span({ class: 'tier-pill', style: `color:${t.textColor};border-color:${t.color}33` },
                `${t.label} ${tierCounts[t.tier] || 0}`),
        ),
    );

    // Group headers row
    const GroupHeaderRow = () => {
        const groups = [
            { label: '⚡ TestGen Enforced', span: 2, color: '#22c55e', bg: 'rgba(34,197,94,0.04)'   },
            { label: '🏛 DB Enforced',      span: 1, color: '#818cf8', bg: 'rgba(129,140,248,0.04)' },
            { label: '📋 Unenforced',        span: 2, color: '#f59e0b', bg: 'rgba(245,158,11,0.04)'  },
        ];
        return tr(
            { class: 'matrix-group-header-row' },
            th({ class: 'col-col' }),
            ...groups.map((g) => th(
                { class: 'matrix-group-header', colspan: g.span, style: `color:${g.color};background:${g.bg}` },
                g.label,
            )),
        );
    };

    return div(
        { class: 'table-section' },
        div(
            {
                class: 'table-section-header',
                onclick: () => { open.val = !open.val; },
            },
            mat('table_rows', 22),
            span({ class: 'ts-name' }, tableName),
            TierPills(),
            span({ class: () => `table-section-chevron${open.val ? ' open' : ''}` }, 'expand_more'),
        ),
        () => open.val
            ? div(
                { class: 'matrix-table-wrap' },
                table(
                    { class: 'matrix-table matrix-table--tiers' },
                    thead(
                        GroupHeaderRow(),
                        tr(
                            th({ class: 'col-col' }, 'Column / Table'),
                            ...MATRIX_COLS.map((c) => th({ class: `tier-col tier-cell--${c.group}`, title: c.label }, c.label)),
                            th({ class: 'unc-col', rowspan: '2', style: 'color:#ef4444;text-align:center;vertical-align:middle' }, 'Uncovered'),
                        ),
                    ),
                    tbody(
                        ...rows.map((row) => {
                            const isTableLevel = row.column === '(table-level)';
                            const rowVisible = !activeMatrixTier
                                ? () => true
                                : () => activeMatrixTier.val === 'all' || activeMatrixTier.val === row.tier;
                            return tr(
                                {
                                    class: isTableLevel ? 'matrix-row--table-level' : '',
                                    'data-tier': row.tier,
                                    style: activeMatrixTier
                                        ? () => rowVisible() ? '' : 'display:none'
                                        : '',
                                },
                                td(
                                    span({ class: 'tier-dot', style: `background:${TIER_DOT_COLOR[row.tier] || '#374151'};${row.tier === 'none' ? 'border:1px solid #6b7280' : ''}` }),
                                    span({
                                        class: isTableLevel ? 'col-name col-name--table-level' : 'col-name',
                                    }, row.column),
                                ),
                                ...MATRIX_COLS.map((c) => td(
                                    { class: `tier-cell tier-cell--${c.group} ${row[c.key] > 0 ? 'has-terms' : 'no-terms'}` },
                                    fmtCount(row[c.key]),
                                )),
                                td({ class: 'unc-cell' },
                                    MATRIX_COLS.every((c) => (row[c.key] || 0) === 0)
                                        ? span({ class: 'uncovered-pill' }, 'Yes')
                                        : '—',
                                ),
                            );
                        }),
                        tr(
                            { class: 'matrix-totals-row' },
                            td('Total'),
                            ...MATRIX_COLS.map((c) => td({ class: 'tier-cell' }, fmtCount(totals[c.key]))),
                            td(),
                        ),
                    ),
                ),
              )
            : '',
    );
};

const CoverageMatrix = (matrix, suiteScope, tables, health, activeTab) => {
    if (!matrix.length) {
        return div({ class: 'dc-empty' }, 'No schema data available.');
    }

    // Cross-filter state — 'all' means no filter; resets whenever tab changes away and back
    const activeMatrixTier = van.state('all');
    if (activeTab) {
        van.derive(() => {
            if (activeTab.val !== 'matrix') activeMatrixTier.val = 'all';
        });
    }

    // Group rows by table preserving order
    const tableMap = new Map();
    for (const row of matrix) {
        if (!tableMap.has(row.table)) tableMap.set(row.table, []);
        tableMap.get(row.table).push(row);
    }

    const scope = suiteScope || {};
    const scopeNote = scope.total > 0 && scope.excluded && scope.excluded.length > 0
        ? div(
            { class: 'matrix-scope-note' },
            mat('info', 13),
            ` Test counts reflect ${scope.included.length} of ${scope.total} suites — `,
            span({ style: 'opacity:0.7' }, scope.excluded.join(', ')),
            ' excluded.',
          )
        : '';

    // Grand totals
    const grand = { db: 0, tested: 0, mon: 0, obs: 0, decl: 0 };
    for (const row of matrix) {
        for (const c of MATRIX_COLS) grand[c.key] += row[c.key] || 0;
    }

    // Contract completeness section at top of matrix tab
    const completenessSection = health
        ? div(
            { class: 'matrix-completeness-section' },
            div({ class: 'matrix-section-label' },
                'Contract Claim Completeness',
                span({ class: 'matrix-completeness-subtitle' },
                    ` · ${health.n_elements || 0} elements grouped by enforcement tier`,
                ),
            ),
            CoverageTierBars(health, activeMatrixTier),
          )
        : '';

    const tableEntries = [...tableMap.entries()];
    return div(
        { class: 'dc-matrix-wrap' },
        completenessSection,
        scopeNote,
        health ? div({ class: 'matrix-section-label' }, 'Coverage by table') : '',
        ...tableEntries.map(([tableName, rows], idx) => {
            const totals = { db: 0, tested: 0, mon: 0, obs: 0, decl: 0 };
            for (const r of rows) for (const c of MATRIX_COLS) totals[c.key] += r[c.key] || 0;
            // Per-table tier counts — each tier independently counts rows with any claim at that level
            const tierCounts = { tg: 0, db: 0, unf: 0, none: 0 };
            for (const r of rows) {
                const hasTg  = (r.tested || 0) + (r.mon  || 0) > 0;
                const hasDb  = (r.db    || 0) > 0;
                const hasUnf = (r.obs   || 0) + (r.decl || 0) > 0;
                if (hasTg)  tierCounts.tg++;
                if (hasDb)  tierCounts.db++;
                if (hasUnf) tierCounts.unf++;
                if (!hasTg && !hasDb && !hasUnf) tierCounts.none++;
            }
            return MatrixTableSection(tableName, rows, idx === 0, totals, tierCounts, activeMatrixTier);
        }),
        (() => {
            const grandTier = { tg: 0, db: 0, unf: 0, none: 0 };
            for (const row of matrix) {
                const hasTg  = (row.tested || 0) + (row.mon  || 0) > 0;
                const hasDb  = (row.db    || 0) > 0;
                const hasUnf = (row.obs   || 0) + (row.decl || 0) > 0;
                if (hasTg)  grandTier.tg++;
                if (hasDb)  grandTier.db++;
                if (hasUnf) grandTier.unf++;
                if (!hasTg && !hasDb && !hasUnf) grandTier.none++;
            }
            return div(
                { class: 'matrix-grand-total' },
                span({ class: 'matrix-grand-label' }, 'All tables'),
                div({ class: 'ts-tier-pills', style: 'margin-left:auto;margin-right:0' },
                    span({ class: 'ts-element-count' }, `${matrix.length} elements:`),
                    ...COVERAGE_TIERS.map((t) =>
                        span({ class: 'tier-pill', style: `color:${t.textColor};border-color:${t.color}33` },
                            `${t.label} ${grandTier[t.tier] || 0}`),
                    ),
                ),
            );
        })(),
    );
};

// ── Term counts summary bar ──────────────────────────────────────────────────

const TermCountsBar = (tables) => {
    // Accumulate counts across all tables/columns for both static and live terms
    // monitor source is grouped under test (monitors are a type of test, not a distinct origin)
    const bySrc  = { ddl: 0, profiling: 0, governance: 0, test: 0 };
    const byVerif = { db_enforced: 0, tested: 0, monitored: 0, observed: 0, declared: 0 };

    for (const t of tables) {
        for (const c of (t.table_terms || [])) {
            const srcKey = c.source === 'monitor' ? 'test' : c.source;
            if (srcKey in bySrc)     bySrc[srcKey]++;
            if (c.verif in byVerif)  byVerif[c.verif]++;
        }
        for (const col of t.columns) {
            for (const c of [...col.static_terms, ...col.live_terms]) {
                const srcKey = c.source === 'monitor' ? 'test' : c.source;
                if (srcKey in bySrc)    bySrc[srcKey]++;
                if (c.verif in byVerif) byVerif[c.verif]++;
            }
        }
    }

    const SrcCard = (label, count, chipCls, icon) =>
        div(
            { class: 'ccbar-card' },
            div({ class: `ccbar-chip ${chipCls}` }, icon, ' ', label),
            div({ class: 'ccbar-count' }, count),
        );

    const VerifCard = (key) => {
        const meta = VERIF_META[key];
        if (!meta) return '';
        return div(
            { class: 'ccbar-card' },
            div({ class: `ccbar-verif-badge ${meta.cls}` }, `${meta.icon} ${meta.label}`),
            div({ class: 'ccbar-count' }, byVerif[key]),
        );
    };

    return div(
        { class: 'ccbar-wrap' },
        // ── By Source ───────────────────────────────────────────────────────
        div(
            { class: 'ccbar-group' },
            div({ class: 'ccbar-group-label' }, 'By Source'),
            div(
                { class: 'ccbar-cards' },
                SrcCard('DDL',        bySrc.ddl,        'ccbar-chip--ddl',  '🏛️'),
                SrcCard('Profiling',  bySrc.profiling,  'ccbar-chip--prof', '📊'),
                SrcCard('Governance', bySrc.governance, 'ccbar-chip--gov',  '🏷️'),
                SrcCard('Test',       bySrc.test,       'ccbar-chip--test', '⚡'),
            ),
        ),
        div({ class: 'ccbar-divider' }),
        // ── By Verification Level ────────────────────────────────────────────
        div(
            { class: 'ccbar-group' },
            div({ class: 'ccbar-group-label' }, 'By Verification Level'),
            div(
                { class: 'ccbar-cards' },
                VerifCard('db_enforced'),
                VerifCard('tested'),
                VerifCard('monitored'),
                VerifCard('observed'),
                VerifCard('declared'),
            ),
        ),
    );
};

// ── Gap analysis tab ──────────────────────────────────────────────────────────

const GapAnalysis = (gaps, tables) => {
    const items = gaps.items || [];
    const countsBar = (tables && tables.length) ? TermCountsBar(tables) : '';

    if (items.length === 0) {
        return div(
            countsBar,
            div(
                { class: 'gap-clean', style: 'margin-top: 16px;' },
                mat('check_circle', 18),
                ' No completeness gaps detected.',
            ),
        );
    }

    const GapItem = ({ msg, severity }) => {
        const cls  = severity === 'error' ? 'error' : severity === 'warning' ? 'warning' : 'info';
        const icon = severity === 'error' ? 'error' : severity === 'warning' ? 'warning' : 'info';
        return div(
            { class: `gap-item ${cls}` },
            span({ class: 'gap-icon' }, icon),
            span(
                { class: 'gap-text' },
                ...msg.split(/(`[^`]+`)/).map((part) =>
                    part.startsWith('`') && part.endsWith('`')
                        ? code(part.slice(1, -1))
                        : part
                ),
            ),
        );
    };

    // Group by table preserving order
    const tableMap = new Map();
    for (const item of items) {
        if (!tableMap.has(item.table)) tableMap.set(item.table, []);
        tableMap.get(item.table).push(item);
    }

    const GapTableSection = (tableName, tableItems, startOpen) => {
        const open = van.state(startOpen);
        const errorCt   = tableItems.filter((i) => i.severity === 'error').length;
        const warnCt    = tableItems.filter((i) => i.severity === 'warning').length;
        const badge = errorCt
            ? span({ class: 'gap-table-badge error' }, `${errorCt} error${errorCt > 1 ? 's' : ''}`)
            : warnCt
            ? span({ class: 'gap-table-badge warning' }, `${warnCt} warning${warnCt > 1 ? 's' : ''}`)
            : span({ class: 'gap-table-badge info' }, `${tableItems.length} info`);

        return div(
            { class: 'table-section' },
            div(
                {
                    class: 'table-section-header',
                    onclick: () => { open.val = !open.val; },
                },
                mat('table_rows', 22),
                tableName,
                badge,
                span({ class: () => `table-section-chevron${open.val ? ' open' : ''}` }, 'expand_more'),
            ),
            () => open.val
                ? div({ class: 'gap-list gap-list--indent' }, ...tableItems.map(GapItem))
                : '',
        );
    };

    const tableEntries = [...tableMap.entries()];
    return div(
        { class: 'dc-gap-wrap' },
        countsBar,
        ...tableEntries.map(([tableName, tableItems], idx) =>
            GapTableSection(tableName, tableItems, idx === 0),
        ),
    );
};

// ── YAML viewer tab ───────────────────────────────────────────────────────────

// Prism.js loaded once as classic scripts (not ESM — they set window.Prism).
// We inject them the first time YamlViewer renders and highlight after load.
let _prismReady = false;
let _prismCallbacks = [];

function _loadPrism(cb) {
    if (_prismReady) { cb(); return; }
    _prismCallbacks.push(cb);
    if (_prismCallbacks.length > 1) return; // already loading
    // import.meta.url is the URL of this module file (…/js/pages/data_contract.js)
    const base = new URL('..', import.meta.url).href;
    const inject = (src, next) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = next;
        document.head.appendChild(s);
    };
    inject(`${base}prism.min.js`, () =>
        inject(`${base}prism-yaml.min.js`, () => {
            _prismReady = true;
            window.Prism.manual = true;
            _prismCallbacks.forEach((f) => f());
            _prismCallbacks = [];
        }),
    );
}

const YamlViewer = (yamlContent, tgName) => {
    const content = yamlContent || '# No contract data yet';
    const preEl = document.createElement('pre');
    const codeEl = document.createElement('code');
    codeEl.className = 'language-yaml';
    codeEl.textContent = content;
    preEl.className = 'yaml-block language-yaml';
    preEl.appendChild(codeEl);

    // Highlight once Prism is ready (may be immediate on re-renders)
    _loadPrism(() => window.Prism?.highlightElement(codeEl));

    // Copy-to-clipboard button
    const copied = van.state(false);
    const copyBtn = div(
        {
            class: 'yaml-copy-btn',
            onclick: () => {
                navigator.clipboard?.writeText(content).then(() => {
                    copied.val = true;
                    setTimeout(() => { copied.val = false; }, 1800);
                });
            },
        },
        () => copied.val ? span(mat('check', 14), ' Copied') : span(mat('content_copy', 14), ' Copy'),
    );

    // Download button
    const downloadBtn = div(
        {
            class: 'yaml-copy-btn',
            onclick: () => {
                const blob = new Blob([content], { type: 'text/yaml' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${tgName || 'contract'}_contract.yaml`;
                a.click();
                URL.revokeObjectURL(url);
            },
        },
        span(mat('download', 14), ' Download'),
    );

    return div(
        { class: 'yaml-wrap' },
        div({ class: 'yaml-toolbar' }, copyBtn, downloadBtn),
        preEl,
    );
};

// ── Upload tab ────────────────────────────────────────────────────────────────

const UploadTab = () => {
    const fileContent = van.state(null);
    const fileName = van.state('');
    const importing = van.state(false);

    const fileError = van.state('');
    const onFileChange = (e) => {
        const file = e.target.files[0];
        if (!file) { fileContent.val = null; fileName.val = ''; fileError.val = ''; return; }
        fileName.val = file.name;
        fileError.val = '';
        const reader = new FileReader();
        reader.onload = (ev) => { fileContent.val = ev.target.result; };
        reader.onerror = () => {
            fileContent.val = null;
            fileError.val = `Could not read "${file.name}". Please try again.`;
        };
        reader.readAsText(file);
    };

    return div(
        { class: 'upload-tab' },
        div({ class: 'upload-desc' },
            p({ style: 'margin: 0 0 10px;' },
                'Upload a modified ODCS v3.1.0 YAML to sync changes back to TestGen. ',
                'Rules without an ',
                span({ style: 'font-family:monospace' }, 'id'),
                ' field are ',
                span({ style: 'font-weight:600' }, 'created'),
                ' as new tests; rules with an ',
                span({ style: 'font-family:monospace' }, 'id'),
                ' field ',
                span({ style: 'font-weight:600' }, 'update'),
                ' the matching test. After import, download the updated YAML to capture the new test IDs.',
            ),
            div({ class: 'upload-desc-cols' },
                div(
                    p({ class: 'upload-desc-heading' }, 'Updated on upload'),
                    ul(
                        li('Contract version, status, and description'),
                        li('Business domain and data product'),
                        li('Latency SLA (profiling delay days)'),
                        li('Quality rule thresholds, tolerances, severity, and description'),
                        li(span({ style: 'font-weight:600' }, 'New quality rules'), ' — add rules without an ', span({ style: 'font-family:monospace' }, 'id'), ' to create tests'),
                    ),
                ),
                div(
                    p({ class: 'upload-desc-heading' }, 'Not updated — manage in TestGen'),
                    ul(
                        li('Tables, columns, and data types'),
                        li('Test suite settings and connections'),
                        li('Test type, target table, or column (ignored on import — immutable once created)'),
                    ),
                ),
            ),
        ),
        div(
            { class: 'file-drop' },
            mat('upload_file', 32),
            label(
                { class: 'file-label' },
                input({ type: 'file', accept: '.yaml,.yml', style: 'display:none', onchange: onFileChange }),
                'Choose YAML file',
            ),
            () => fileName.val
                ? span({ class: 'file-name' }, mat('description', 14), ' ', fileName.val)
                : span({ class: 'file-hint' }, 'ODCS v3.1.0 data contract (.yaml, .yml)'),
        ),
        () => fileError.val ? div({ class: 'upload-error' }, mat('error', 14), ' ', fileError.val) : '',
        () => fileContent.val
            ? Button({
                type: 'stroked',
                color: 'primary',
                icon: 'upload',
                label: importing.val ? 'Importing…' : 'Import Changes',
                disabled: importing.val,
                onclick: () => {
                    importing.val = true;
                    emitEvent('ImportContractClicked', { payload: fileContent.val });
                },
              })
            : '',
    );
};

// ── Health grid ───────────────────────────────────────────────────────────────

const HealthGrid = (health, activeFilter, activeTab, termDiff, diffFilter, versionNum) => {
    const coverageCls = health.coverage_pct >= 80 ? 'good' : health.coverage_pct >= 50 ? 'warn' : 'bad';

    // Suite runs from the new backend field; fall back to legacy counts if absent.
    const suiteRuns = health.suite_runs || [];
    const totalRunTests = suiteRuns.length
        ? suiteRuns.reduce((s, r) => s + (r.test_ct || 0), 0)
        : health.n_tests;
    const totalPassed  = suiteRuns.reduce((s, r) => s + (r.passed_ct  || 0), 0) || health.passing;
    const totalWarning = suiteRuns.reduce((s, r) => s + (r.warning_ct || 0), 0) || health.warning;
    const totalFailed  = suiteRuns.reduce((s, r) => s + (r.failed_ct  || 0) + (r.error_ct || 0), 0) || health.failing;

    const SummarySegment = (pct, color) =>
        div({ class: 'summary-bar__seg', style: `width:${pct}%;background:${color}` });

    const CountDot = (color, label, n) =>
        n ? span({ class: 'count-item' }, span({ class: 'count-dot', style: `background:${color}` }), ` ${n} ${label}`) : '';

    const filterButton = (label, filterVal) =>
        span(
            {
                class: () => `health-filter-btn ${activeFilter.val === filterVal ? 'active' : ''}`,
                onclick: () => { activeFilter.val = activeFilter.val === filterVal ? 'all' : filterVal; },
            },
            label,
        );

    const handleTestCardClick = () => {
        if (!health.last_test_run_id) return;
        if (suiteRuns.length > 1) {
            // Multiple suites — open a Streamlit dialog (can't use iframe-bound popups)
            emitEvent('SuitePickerClicked', {});
        } else {
            emitEvent('LinkClicked', { href: 'test-runs:results', params: { run_id: health.last_test_run_id } });
        }
    };

    const DiffStatusRow = (count, statusKey, label) =>
        div(
            {
                class: 'diff-status-row',
                onclick: (e) => {
                    e.stopPropagation();
                    diffFilter.val = diffFilter.val === statusKey ? '' : statusKey;
                    activeTab.val  = 'differences';
                },
            },
            span({ class: 'diff-status-count' }, count),
            span({ class: 'diff-status-label' }, label),
        );

    const StatusCount = (color, label, count) =>
        count
            ? span({ class: 'count-item' },
                   span({ class: 'count-dot', style: `background:${color}` }),
                   ` ${count} ${label}`)
            : '';

    const ComplianceCardContent = (h, tdf) => {
        const TierRow = (cnt, lbl, color) =>
            div({ class: 'ct-tier-row' },
                span({ class: 'ct-count' }, cnt),
                span({ class: 'ct-label', style: `color:${color}` }, lbl),
            );

        const SubRow = (lbl, children) =>
            div({ class: 'ct-sub-row' },
                span({ class: 'ct-sublabel' }, lbl),
                div({ class: 'ct-chips' }, ...children),
            );

        const S = (color, lbl, count) =>
            count ? span({ class: 'ct-chip', style: `color:${color}` }, `${count} ${lbl}`) : '';

        const monitorTotal = tdf.tg_monitor_passed + tdf.tg_monitor_failed + tdf.tg_monitor_warning
                           + tdf.tg_monitor_error  + tdf.tg_monitor_not_run;

        return div(
            { class: 'ct-card-content' },
            TierRow(h.db_enforced || 0, 'database enforced', '#818cf8'),
            TierRow(h.unenforced  || 0, 'unenforced',        '#f59e0b'),
            TierRow(h.tg_enforced || 0, 'TestGen enforced',  '#22c55e'),
            monitorTotal > 0
                ? SubRow('Monitors', [
                    S('#22c55e', 'passed',  tdf.tg_monitor_passed),
                    S('#ef4444', 'failed',  tdf.tg_monitor_failed),
                    S('#f59e0b', 'warning', tdf.tg_monitor_warning),
                    S('#94a3b8', 'error',   tdf.tg_monitor_error),
                    S('#6b7280', 'not run', tdf.tg_monitor_not_run),
                  ])
                : '',
            SubRow('Tests', [
                S('#22c55e', 'passed',  tdf.tg_test_passed),
                S('#ef4444', 'failed',  tdf.tg_test_failed),
                S('#f59e0b', 'warning', tdf.tg_test_warning),
                S('#94a3b8', 'error',   tdf.tg_test_error),
                S('#6b7280', 'not run', tdf.tg_test_not_run),
            ]),
            tdf.tg_hygiene_definite + tdf.tg_hygiene_likely + tdf.tg_hygiene_possible > 0
                ? SubRow('Hygiene', [
                    S('#ef4444', 'definite', tdf.tg_hygiene_definite),
                    S('#f59e0b', 'likely',   tdf.tg_hygiene_likely),
                    S('#94a3b8', 'possible', tdf.tg_hygiene_possible),
                  ])
                : '',
        );
    };

    return div(
        { class: 'health-grid' },
        // — Coverage card
        div(
            {
                class: 'health-card coverage health-card--link',
                onclick: () => { activeTab.val = 'matrix'; },
                title: 'View Coverage Matrix',
            },
            div({ class: 'health-card__label' },
                mat('verified', 13), ' Contract Term Coverage',
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
            health.n_elements != null
                ? CoverageTierBars(health, null)
                : [
                    div({ class: `health-card__value ${coverageCls}` }, `${health.coverage_pct}%`),
                    div({ class: 'progress-track' },
                        div({ class: `progress-fill ${coverageCls}`, style: `width:${health.coverage_pct}%` }),
                    ),
                  ],
        ),
        // — Differences card
        div(
            {
                class: 'health-card tests health-card--link',
                onclick: () => { activeTab.val = 'differences'; },
                title: 'View Contract Term Differences',
            },
            div({ class: 'health-card__label' },
                mat('compare', 13), ` Version ${versionNum} Contract Term Differences`,
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
            termDiff
                ? [
                    div({ class: 'health-card__sub' },
                        `Saved: ${termDiff.saved_count}  ·  Current: ${termDiff.current_count}`,
                    ),
                    div(
                        { class: 'diff-rows' },
                        termDiff.same_count    ? DiffStatusRow(termDiff.same_count,    'same',    'same')    : '',
                        termDiff.changed_count ? DiffStatusRow(termDiff.changed_count, 'changed', 'changed') : '',
                        termDiff.deleted_count ? DiffStatusRow(termDiff.deleted_count, 'deleted', 'deleted') : '',
                        termDiff.new_count     ? DiffStatusRow(termDiff.new_count,     'new',     'new')     : '',
                    ),
                  ]
                : div({ class: 'health-card__sub' }, 'No saved version yet'),
        ),
        // — Compliance card
        div(
            {
                class: 'health-card hygiene health-card--link',
                onclick: () => { activeTab.val = 'compliance'; },
                title: 'View Contract Term Compliance',
            },
            div({ class: 'health-card__label' },
                mat('fact_check', 13), ` Version ${versionNum} Contract Term Compliance`,
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
            termDiff
                ? ComplianceCardContent(health, termDiff)
                : div({ class: 'health-card__sub' }, 'No saved version yet'),
        ),
    );
};

// ── Suite scope bar ───────────────────────────────────────────────────────────

const SuiteScope = (suiteScope, meta) => {
    const included = suiteScope.included || [];
    const excluded = suiteScope.excluded || [];
    const total    = suiteScope.total    || 0;

    if (total === 0) return '';

    const SuiteChip = (name, isIncluded) =>
        span(
            {
                class: `suite-chip ${isIncluded ? 'suite-chip--in' : 'suite-chip--out'} suite-chip--clickable`,
                role: 'link',
                tabindex: '0',
                title: `Go to ${name} in Test Suites`,
                onclick: () => emitEvent('LinkClicked', {
                    href: 'test-suites',
                    params: {
                        project_code: meta.project_code,
                        table_group_id: meta.table_group_id,
                        test_suite_name: name,
                    },
                }),
                onkeydown: (e) => e.key === 'Enter' && emitEvent('LinkClicked', {
                    href: 'test-suites',
                    params: {
                        project_code: meta.project_code,
                        table_group_id: meta.table_group_id,
                        test_suite_name: name,
                    },
                }),
            },
            span({ class: 'suite-chip__icon' }, isIncluded ? 'check' : 'remove'),
            name,
            span({ class: 'suite-chip__arrow' }, mat('arrow_forward', 14)),
        );

    return div(
        { class: 'suite-scope-bar' },
        span({ class: 'suite-scope-label' }, mat('rule', 13), ' Contract Scope:'),
        div(
            { class: 'suite-scope-chips' },
            ...included.map((s) => SuiteChip(s, true)),
            ...excluded.map((s) => SuiteChip(s, false)),
        ),
        excluded.length > 0
            ? span({ class: 'suite-scope-hint' }, `${excluded.length} suite(s) excluded — edit in Test Suites to change`)
            : '',
    );
};

// ── Page header ───────────────────────────────────────────────────────────────

const PageHeader = (tgName, meta, yamlContent, suiteScope) => {
    return div(
        { class: 'dc-page-header' },
        div(
            { class: 'dc-page-header__left' },
            meta.description_purpose
                ? p({ class: 'purpose-text' }, meta.description_purpose)
                : '',
            suiteScope ? SuiteScope(suiteScope, meta) : '',
        ),
    );
};

// ── Tab bar ───────────────────────────────────────────────────────────────────

const TABS = [
    { id: 'overview',    label: 'Contract Terms'      },
    { id: 'matrix',      label: 'Contract Coverage'   },
    { id: 'differences', label: 'Contract Differences' },
    { id: 'compliance',  label: 'Contract Compliance'  },
    { id: 'yaml',        label: 'YAML'                 },
    { id: 'upload',      label: 'Upload Changes'       },
];

const TabBar = (activeTab) =>
    div(
        { class: 'dc-tabs' },
        ...TABS.map((t) =>
            div(
                {
                    class: () => `dc-tab${activeTab.val === t.id ? ' active' : ''}`,
                    onclick: () => { activeTab.val = t.id; },
                },
                t.label,
            )
        ),
        div({ class: 'dc-tabs-spacer' }),
        div(
            {
                class: () => `dc-tab-help${activeTab.val === 'help' ? ' active' : ''}`,
                onclick: () => { activeTab.val = activeTab.val === 'help' ? 'overview' : 'help'; },
            },
            mat('help_outline', 13), ' What are contract terms?',
        ),
    );

// ── Terms help panel ─────────────────────────────────────────────────────────

const TermsHelpPanel = () => {
    const SectionLabel = (title) =>
        div({ class: 'help-section-label' }, title);

    const SourceRow = (cls, chipLabel, verifLabel, desc) =>
        div(
            { class: 'help-row' },
            span({ class: `help-src-chip chip-${cls}` }, chipLabel),
            span({ class: 'help-verif' }, verifLabel),
            span({ class: 'help-desc' }, desc),
        );

    const VerifRow = (icon, label, badgeCls, desc) =>
        div(
            { class: 'help-row' },
            span({ class: `help-verif-badge ${badgeCls}` }, `${icon} ${label}`),
            span({ class: 'help-desc' }, desc),
        );

    return div(
        { class: 'terms-help-panel' },
        div(
            { class: 'help-intro' },
            'A ',
            span({ class: 'help-em' }, 'contract term'),
            ' is any assertion TestGen can make about a column. Every term has two dimensions: ',
            span({ class: 'help-em' }, 'Source'),
            ' — where we learned it — and ',
            span({ class: 'help-em' }, 'Verification Level'),
            ' — how strongly it is enforced.',
        ),
        div(
            { class: 'help-columns' },

            // ── Sources column ──────────────────────────────────────────
            div(
                { class: 'help-col' },
                SectionLabel('Term Sources'),
                div(
                    { class: 'help-col-header' },
                    span('Source'),
                    span('Evidence Level'),
                    span('What it provides'),
                ),
                SourceRow('ddl',  'DDL',        '🏛️ DB Enforced',
                    'Column type, length, nullability, primary key, foreign key — declared in the CREATE TABLE schema.'),
                SourceRow('prof', 'Profiling',  '📸 Observed',
                    'Null %, max length, value distribution, semantic type detection — measured from actual data during profiling.'),
                SourceRow('gov',  'Governance', '🏷️ Declared',
                    'PII classification, Critical Data Element flag, description, standard pattern (EMAIL, ZIP, SSN, etc.).'),
                SourceRow('tst',  'Test',       '⚡ Tested',
                    'Active quality rule — format check, LOV match, range bound, custom SQL assertion — executes on every test run.'),
            ),

            div({ class: 'help-divider' }),

            // ── Verification levels column ───────────────────────────────
            div(
                { class: 'help-col help-col--verif' },
                SectionLabel('Verification Levels'),
                div(
                    { class: 'help-col-header help-col-header--verif' },
                    span('Level'),
                    span('What it means'),
                ),
                VerifRow('🏛️', 'DB Enforced', 'hbadge-db',
                    'A database constraint (PK, FK, NOT NULL, CHECK). The database itself rejects violations — the strongest guarantee.'),
                VerifRow('⚡',  'Tested',      'hbadge-test',
                    'Actively tested by TestGen on every run. Results are tracked, scored, and can trigger alerts.'),
                VerifRow('🔬', 'Monitored',   'hbadge-mon',
                    'Anomaly detection watches for deviation from observed norms. Alerts when thresholds are crossed.'),
                VerifRow('📸', 'Observed',    'hbadge-obs',
                    'Seen during profiling — evidence exists in the data but no active test enforces it yet.'),
                VerifRow('🏷️', 'Declared',    'hbadge-decl',
                    'Stated in governance metadata (description, classification). Informational — not yet verified at runtime.'),
            ),
        ),

        div(
            { class: 'help-footer' },
            span({ class: 'help-em' }, 'Contract Completeness'),
            ' assigns each column and table-level element to its highest enforcement tier: ',
            span({ class: 'help-em' }, '⚡ TestGen Enforced'),
            ' (active test or monitor), ',
            span({ class: 'help-em' }, '🏛 DB Enforced'),
            ' (NOT NULL, PK, FK, or constrained type — no active test), ',
            span({ class: 'help-em' }, '📋 Unenforced'),
            ' (observed stats or declared metadata only), or ',
            span({ class: 'help-em' }, '○ Uncovered'),
            ' (bare data type with no additional constraints or metadata). ',
            'Click a tier bar in the Coverage Matrix to cross-filter the table rows below.',
        ),
    );
};

// ── Differences tab ───────────────────────────────────────────────────────────

const DifferencesTab = (termDiff, diffFilter) => {
    if (!termDiff || termDiff.saved_count === 0) {
        return div({ class: 'dc-empty-state' }, 'No saved contract version yet.');
    }

    const entries = termDiff.entries || [];
    const grouped = {
        changed: entries.filter(e => e.status === 'changed'),
        new:     entries.filter(e => e.status === 'new'),
        deleted: entries.filter(e => e.status === 'deleted'),
        same:    entries.filter(e => e.status === 'same'),
    };

    const STATUS = {
        changed: { color: '#f59e0b', label: 'changed' },
        new:     { color: '#22c55e', label: 'new'     },
        deleted: { color: '#ef4444', label: 'deleted' },
        same:    { color: '#6b7280', label: 'same'    },
    };

    const DetailCell = (detail) => {
        if (!detail) return td({ class: 'diff-detail-cell' }, '');
        const idx = detail.indexOf(' → ');
        if (idx !== -1) {
            return td({ class: 'diff-detail-cell' },
                span({ class: 'diff-detail-before' }, detail.slice(0, idx)),
                span({ class: 'diff-detail-arrow' }, ' → '),
                span({ class: 'diff-detail-after' },  detail.slice(idx + 3)),
            );
        }
        return td({ class: 'diff-detail-cell' }, detail);
    };

    const DiffRow = (entry) => {
        const col = (STATUS[entry.status] || {}).color || '#6b7280';
        return tr(
            { class: 'dc-term-row' },
            td({ class: 'diff-element-cell', style: `box-shadow:inset 3px 0 0 ${col}` }, entry.element),
            td({ class: 'diff-type-cell' },   entry.test_type || ''),
            DetailCell(entry.detail),
        );
    };

    const DiffTable = (items) =>
        div({ class: 'dc-term-table-wrap' },
            table({ class: 'dc-term-table' },
                thead(tr(
                    th({ class: 'diff-element-cell' }, 'Element'),
                    th('Test Type'),
                    th('Detail'),
                )),
                tbody(...items.map(DiffRow)),
            ),
        );

    const DiffAccordion = (statusKey, label, items, defaultOpen) => {
        if (items.length === 0) return '';
        const s = STATUS[statusKey] || {};
        const isOpen = van.state(diffFilter.val ? diffFilter.val === statusKey : defaultOpen);
        // Re-sync when diffFilter changes while the tab is already active (no re-render of tab)
        van.derive(() => { isOpen.val = diffFilter.val ? diffFilter.val === statusKey : defaultOpen; });
        return div(
            { class: 'diff-accordion' },
            div(
                {
                    class: 'diff-accordion-header',
                    style: `border-left: 3px solid ${s.color}`,
                    onclick: () => { isOpen.val = !isOpen.val; },
                },
                () => mat(isOpen.val ? 'expand_more' : 'chevron_right', 14),
                span({ class: 'diff-accordion-label' }, ` ${label}`),
                span({
                    class: 'diff-count-badge',
                    style: `color:${s.color};background:${s.color}18;border-color:${s.color}40`,
                }, items.length),
            ),
            () => isOpen.val ? DiffTable(items) : '',
        );
    };

    const total = entries.length || 1;
    const BarSeg = (color, count) =>
        count > 0
            ? div({ class: 'diff-bar-seg', style: `width:${(100 * count / total).toFixed(1)}%;background:${color}` })
            : '';

    const SummaryPill = (color, label, count) =>
        count > 0
            ? div({ class: 'diff-summary-pill', style: `color:${color};border-color:${color}40;background:${color}10` },
                  span({ class: 'diff-summary-count' }, count),
                  span({ class: 'diff-summary-label' }, label),
              )
            : '';

    const DiffSummaryBar = () =>
        div({ class: 'tab-summary-bar' },
            div({ class: 'tab-summary-meta' },
                span({ class: 'tab-summary-kv-label' }, 'Saved'),
                span({ class: 'tab-summary-kv-num' }, termDiff.saved_count),
                div({ class: 'tab-summary-vsep' }),
                span({ class: 'tab-summary-kv-label' }, 'Current'),
                span({ class: 'tab-summary-kv-num' }, termDiff.current_count),
            ),
            div({ class: 'diff-stacked-bar' },
                BarSeg('#6b7280', grouped.same.length),
                BarSeg('#f59e0b', grouped.changed.length),
                BarSeg('#ef4444', grouped.deleted.length),
                BarSeg('#22c55e', grouped.new.length),
            ),
            div({ class: 'diff-summary-pills' },
                SummaryPill('#6b7280', 'same',    grouped.same.length),
                SummaryPill('#f59e0b', 'changed', grouped.changed.length),
                SummaryPill('#ef4444', 'deleted', grouped.deleted.length),
                SummaryPill('#22c55e', 'new',     grouped.new.length),
            ),
        );

    return div(
        { class: 'dc-differences-tab' },
        DiffSummaryBar(),
        DiffAccordion('changed', 'Changed', grouped.changed, true),
        DiffAccordion('new',     'New',     grouped.new,     true),
        DiffAccordion('deleted', 'Deleted', grouped.deleted, true),
        DiffAccordion('same',    'Same',    grouped.same,    false),
    );
};

// ── Compliance tab ────────────────────────────────────────────────────────────

const ComplianceTab = (termDiff, health) => {
    if (!termDiff || termDiff.saved_count === 0) {
        return div({ class: 'dc-empty-state' }, 'No saved contract version yet.');
    }

    const entries       = termDiff.entries || [];
    const activeEntries = entries.filter(e => e.status === 'same' || e.status === 'changed');
    const monitorRows   = activeEntries.filter(e => e.is_monitor);
    const testRows      = activeEntries.filter(e => !e.is_monitor);
    const hygieneRows   = termDiff.hygiene_entries || [];

    const statusColor = {
        passed: '#22c55e', failed: '#ef4444', warning: '#f59e0b',
        error: '#94a3b8', not_run: '#6b7280',
    };
    const likelihoodColor = { Definite: '#ef4444', Likely: '#f59e0b', Possible: '#94a3b8' };

    const Chip = (color, label) =>
        span({
            class: 'compliance-chip',
            style: `color:${color};background:${color}18;border-color:${color}50`,
        }, label);

    const ComplianceRow = (entry) => {
        const col = statusColor[entry.last_result] || '#6b7280';
        return tr(
            { class: 'dc-term-row' },
            td({ class: 'diff-element-cell', style: `box-shadow:inset 3px 0 0 ${col}` }, entry.element),
            td({ class: 'diff-type-cell' },    entry.test_type || ''),
            td(Chip(col, (entry.last_result || 'not run').replace('_', ' '))),
        );
    };

    const HygieneRow = (entry) => {
        const col = likelihoodColor[entry.issue_likelihood] || '#94a3b8';
        return tr(
            { class: 'dc-term-row' },
            td({ class: 'diff-element-cell', style: `box-shadow:inset 3px 0 0 ${col}` }, entry.element),
            td({ class: 'diff-type-cell' },    entry.anomaly_type || ''),
            td(Chip(col, entry.issue_likelihood || '')),
        );
    };

    const ComplianceTable = (rows, col2Label) =>
        div(
            { class: 'dc-term-table-wrap' },
            table(
                { class: 'dc-term-table' },
                thead(tr(th('Element'), th(col2Label), th('Status'))),
                tbody(...rows),
            ),
        );

    // Render mini status chips in the accordion header
    const HeaderChips = (pairs) =>
        div({ class: 'accordion-header-chips' },
            ...pairs
                .filter(([, n]) => n > 0)
                .map(([lbl, n, col]) =>
                    span({
                        class: 'accordion-header-chip',
                        style: `color:${col};background:${col}18;border-color:${col}40`,
                    }, `${n} ${lbl}`),
                ),
        );

    const ComplianceAccordion = (label, rows, chipPairs, col2Label) => {
        if (rows.length === 0) return '';
        const isOpen = van.state(true);
        return div(
            { class: 'diff-accordion' },
            div(
                { class: 'diff-accordion-header', onclick: () => { isOpen.val = !isOpen.val; } },
                () => mat(isOpen.val ? 'expand_more' : 'chevron_right', 14),
                span({ class: 'diff-accordion-label' }, ` ${label}`),
                span({
                    class: 'diff-count-badge',
                    style: 'color:var(--caption-text-color);background:rgba(128,128,128,0.1);border-color:var(--border-color)',
                }, rows.length),
                HeaderChips(chipPairs),
            ),
            () => isOpen.val ? ComplianceTable(rows, col2Label) : '',
        );
    };

    const complianceStat = (color, count, label) =>
        count > 0
            ? span({ class: 'compliance-summary-stat', style: `color:${color}` }, `${count} ${label}`)
            : '';

    const ComplianceSummaryBar = () => {
        const h = termDiff;
        return div(
            { class: 'tab-summary-bar' },
            div({ class: 'compliance-summary-section' },
                span({ class: 'compliance-summary-tier' }, 'Monitors:'),
                complianceStat('#22c55e', h.tg_monitor_passed,  'passed'),
                complianceStat('#ef4444', h.tg_monitor_failed,  'failed'),
                complianceStat('#f59e0b', h.tg_monitor_warning, 'warning'),
                complianceStat('#94a3b8', h.tg_monitor_error,   'error'),
                complianceStat('#6b7280', h.tg_monitor_not_run, 'not run'),
            ),
            div({ class: 'compliance-summary-sep' }),
            div({ class: 'compliance-summary-section' },
                span({ class: 'compliance-summary-tier' }, 'Tests:'),
                complianceStat('#22c55e', h.tg_test_passed,  'passed'),
                complianceStat('#ef4444', h.tg_test_failed,  'failed'),
                complianceStat('#f59e0b', h.tg_test_warning, 'warning'),
                complianceStat('#94a3b8', h.tg_test_error,   'error'),
                complianceStat('#6b7280', h.tg_test_not_run, 'not run'),
            ),
            div({ class: 'compliance-summary-sep' }),
            div({ class: 'compliance-summary-section' },
                span({ class: 'compliance-summary-tier' }, 'Hygiene:'),
                complianceStat('#ef4444', h.tg_hygiene_definite, 'definite'),
                complianceStat('#f59e0b', h.tg_hygiene_likely,   'likely'),
                complianceStat('#94a3b8', h.tg_hygiene_possible, 'possible'),
            ),
        );
    };

    return div(
        { class: 'dc-compliance-tab' },
        ComplianceSummaryBar(),
        ComplianceAccordion('Monitors', monitorRows.map(ComplianceRow), [
            ['passed',  termDiff.tg_monitor_passed,  '#22c55e'],
            ['failed',  termDiff.tg_monitor_failed,  '#ef4444'],
            ['warning', termDiff.tg_monitor_warning, '#f59e0b'],
            ['error',   termDiff.tg_monitor_error,   '#94a3b8'],
            ['not run', termDiff.tg_monitor_not_run, '#6b7280'],
        ], 'Test Type'),
        ComplianceAccordion('Tests', testRows.map(ComplianceRow), [
            ['passed',  termDiff.tg_test_passed,  '#22c55e'],
            ['failed',  termDiff.tg_test_failed,  '#ef4444'],
            ['warning', termDiff.tg_test_warning, '#f59e0b'],
            ['error',   termDiff.tg_test_error,   '#94a3b8'],
            ['not run', termDiff.tg_test_not_run, '#6b7280'],
        ], 'Test Type'),
        ComplianceAccordion('Hygiene', hygieneRows.map(HygieneRow), [
            ['definite', termDiff.tg_hygiene_definite, '#ef4444'],
            ['likely',   termDiff.tg_hygiene_likely,   '#f59e0b'],
            ['possible', termDiff.tg_hygiene_possible, '#94a3b8'],
        ], 'Anomaly Type'),
    );
};

// ── Main component ────────────────────────────────────────────────────────────

const DataContract = (props) => {
    loadStylesheet('data-contract', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const wrapperId = 'data-contract-wrapper';
    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    const activeTab    = van.state('overview');
    const activeFilter = van.state('all');
    const diffFilter   = van.state('');

    return div(
        { id: wrapperId, class: 'dc-page' },
        () => {
            const tgName     = getValue(props.table_group_name) || '';
            const meta       = getValue(props.meta)             || {};
            const health     = getValue(props.health)           || {};
            const yaml       = getValue(props.yaml_content)     || '';
            const tables     = getValue(props.tables)           || [];
            const matrix     = getValue(props.coverage_matrix)  || [];
            const gaps       = getValue(props.gaps)             || {};
            const suiteScope = getValue(props.suite_scope)      || {};
            const termDiff   = getValue(props.term_diff)        || null;
            const versionNum = (getValue(props.version_info)    || {}).version || '';

            return div(
                PageHeader(tgName, meta, yaml, suiteScope),
                HealthGrid(health, activeFilter, activeTab, termDiff, diffFilter, versionNum),
                TabBar(activeTab),
                () => {
                    const tab = activeTab.val;
                    if (tab === 'overview')    return TermsDetail(tables, activeFilter);
                    if (tab === 'matrix')      return CoverageMatrix(matrix, suiteScope, tables, health, activeTab);
                    if (tab === 'differences') return DifferencesTab(termDiff, diffFilter);
                    if (tab === 'compliance')  return ComplianceTab(termDiff, health);
                    if (tab === 'yaml')        return YamlViewer(yaml, tgName);
                    if (tab === 'upload')      return UploadTab();
                    if (tab === 'help')        return TermsHelpPanel();
                    return '';
                },
            );
        },
    );
};

// ── Stylesheet ────────────────────────────────────────────────────────────────

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.dc-page {
    overflow-y: auto;
    min-height: 400px;
    padding-bottom: 48px;
}

/* ── Material icon helper ── */
.material {
    font-family: 'Material Symbols Rounded', sans-serif;
    font-style: normal;
    font-variation-settings: 'FILL' 0, 'wght' 300, 'GRAD' 0, 'opsz' 20;
    display: inline-block;
    line-height: 1;
    vertical-align: middle;
}

/* ── Page header ── */
.dc-page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 20px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border-color);
    gap: 16px;
    flex-wrap: wrap;
}
.dc-page-header__left { flex: 1; min-width: 0; }
.status-chip {
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: inline-flex;
    align-items: center;
}
.purpose-text {
    font-size: 13px;
    color: var(--secondary-text-color);
    margin: 4px 0 8px 0;
    font-style: italic;
    line-height: 1.6;
}
.meta-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.pill {
    font-size: 12px;
    color: var(--secondary-text-color);
    background: var(--button-generic-background-color);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 3px 10px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

/* ── Health grid ── */
.health-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-bottom: 20px;
}
@media (max-width: 640px) {
    .health-grid { grid-template-columns: 1fr; }
}
.health-card {
    background: var(--card-background-color);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 16px 18px;
    position: relative;
    overflow: hidden;
    animation: dcFadeUp 0.3s ease both;
    display: flex;
    flex-direction: column;
}
.health-card:nth-child(1) { animation-delay: 0.05s; }
.health-card:nth-child(2) { animation-delay: 0.10s; }
.health-card:nth-child(3) { animation-delay: 0.15s; }
@keyframes dcFadeUp {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
}
.health-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
}
.health-card.coverage::before { background: linear-gradient(90deg, #4f8ef7, #818cf8); }
.health-card.tests::before    { background: linear-gradient(90deg, #22c55e, #10b981); }
.health-card.hygiene::before  { background: linear-gradient(90deg, #f59e0b, #f97316); }
.health-card--link { cursor: pointer; transition: box-shadow 0.15s, border-color 0.15s; }
.health-card--link:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.12); border-color: var(--primary-color, #4f8ef7); }
.health-card__nav-icon { margin-left: 4px; opacity: 0.5; vertical-align: middle; }
.health-card--link:hover .health-card__nav-icon { opacity: 1; }

.health-card__label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--caption-text-color);
    margin-bottom: 10px;
}
.health-card__value {
    font-size: 26px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 8px;
    letter-spacing: -0.5px;
}
.health-card__value.neutral { color: var(--primary-text-color); font-size: 22px; }
.health-card__value-row { display: flex; align-items: baseline; gap: 4px; }
.health-card__value-unit { font-size: 13px; color: var(--caption-text-color); font-weight: 400; }
.health-card__suite-inline {
    font-size: 11px;
    font-weight: 600;
    color: var(--caption-text-color);
    background: rgba(128,128,128,0.1);
    padding: 2px 7px;
    border-radius: 10px;
    white-space: nowrap;
}
.health-card__value.good    { color: #22c55e; }
.health-card__value.warn    { color: #f59e0b; }
.health-card__value.bad     { color: #ef4444; }
.health-card__sub { font-size: 12px; color: var(--caption-text-color); margin-top: 4px; }
.health-card__run-time {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: var(--caption-text-color);
    margin-top: auto;
    padding-top: 10px;
    border-top: 1px solid var(--border-color);
    opacity: 0.75;
}

.progress-track {
    background: rgba(128,128,128,0.15);
    border-radius: 4px;
    height: 5px;
    margin: 8px 0;
    overflow: hidden;
}
.progress-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.8s cubic-bezier(0.4,0,0.2,1);
}
.progress-fill.good { background: #22c55e; }
.progress-fill.warn { background: #f59e0b; }
.progress-fill.bad  { background: #ef4444; }

.summary-bar {
    display: flex;
    height: 6px;
    border-radius: 4px;
    overflow: hidden;
    margin: 8px 0;
    gap: 1px;
}
.summary-bar__seg { height: 100%; }
.summary-counts { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; }
.count-item {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: var(--secondary-text-color);
}
.count-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }

.health-filter-btn {
    display: inline-block;
    margin-top: 10px;
    padding: 4px 10px;
    font-size: 12px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--button-generic-background-color);
    color: var(--secondary-text-color);
    cursor: pointer;
    transition: all 0.15s;
}
.health-filter-btn:hover, .health-filter-btn.active {
    color: var(--link-text-color);
    border-color: rgba(79,142,247,0.4);
    background: rgba(79,142,247,0.08);
}

/* ── Tabs ── */
.dc-tabs {
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--border-color);
    margin-bottom: 20px;
}
.dc-tab {
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 500;
    color: var(--caption-text-color);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    transition: all 0.15s;
    user-select: none;
}
.dc-tab:hover { color: var(--secondary-text-color); }
.dc-tab.active { color: var(--link-text-color); border-bottom-color: var(--link-text-color); }

/* ── Section header ── */
.section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
}
.section-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--secondary-text-color);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    display: flex;
    align-items: center;
    gap: 6px;
}
.filter-pills { display: flex; gap: 4px; align-items: center; }
.dc-label { font-size: 11px; color: var(--caption-text-color); margin-right: 2px; }
.filter-pill {
    padding: 3px 10px;
    font-size: 11px;
    border-radius: 20px;
    border: 1px solid var(--border-color);
    color: var(--caption-text-color);
    cursor: pointer;
    transition: all 0.15s;
    background: var(--button-generic-background-color);
}
.filter-pill:hover { color: var(--secondary-text-color); }
.filter-pill.active { color: var(--link-text-color); border-color: rgba(79,142,247,0.4); background: rgba(79,142,247,0.08); }
.filter-pill--badge-enforced.active { color: #a78bfa; border-color: rgba(129,140,248,0.4); background: rgba(129,140,248,0.15); }
.filter-pill--badge-tested.active   { color: #22c55e; border-color: rgba(34,197,94,0.4);   background: rgba(34,197,94,0.15);   }
.filter-pill--badge-mon.active      { color: #f97316; border-color: rgba(249,115,22,0.4);  background: rgba(249,115,22,0.15);  }
.filter-pill--badge-obs.active      { color: #94a3b8; border-color: rgba(100,116,139,0.4); background: rgba(100,116,139,0.15); }
.filter-pill--badge-decl.active     { color: #f59e0b; border-color: rgba(245,158,11,0.4);  background: rgba(245,158,11,0.15);  }

/* ── Table section (terms detail) ── */
.table-section { margin-bottom: 24px; }
.table-section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: var(--card-background-color);
    border: 1px solid var(--border-color);
    border-radius: 6px 6px 0 0;
    font-weight: 600;
    color: var(--primary-text-color);
    font-size: 14px;
}
.ts-name { flex: 1; }
.ts-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
}
.count-badge {
    font-size: 11px;
    color: var(--caption-text-color);
    font-weight: 400;
}
.count-badge--terms {
    font-size: 11px;
    color: var(--link-text-color);
    font-weight: 500;
    background: rgba(79,142,247,0.08);
    border: 1px solid rgba(79,142,247,0.2);
    padding: 1px 7px;
    border-radius: 10px;
}
.count-badge--table {
    font-size: 11px;
    color: #d97706;
    font-weight: 500;
    background: rgba(245,158,11,0.08);
    border: 1px solid rgba(245,158,11,0.25);
    padding: 1px 7px;
    border-radius: 10px;
}
.table-terms-row {
    background: rgba(245,158,11,0.03);
    border-left: 2px solid rgba(245,158,11,0.3) !important;
}
.table-level-label {
    font-size: 11px !important;
    font-style: italic;
    color: var(--caption-text-color) !important;
    font-family: inherit !important;
    font-weight: 500 !important;
    display: flex;
    align-items: center;
    gap: 3px;
}
.col-row {
    padding: 10px 14px;
    border: 1px solid var(--border-color);
    border-top: none;
    display: grid;
    grid-template-columns: 240px 1fr;
    gap: 12px;
    align-items: start;
}
.col-row:last-child { border-radius: 0 0 6px 6px; }
.col-row:hover { background: rgba(128,128,128,0.03); }
.col-header { display: flex; flex-direction: column; gap: 3px; padding-top: 2px; }
.gov-btn {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 11px;
    color: var(--caption-text-color);
    border: 1px dashed var(--border-color);
    border-radius: 12px;
    padding: 2px 8px;
    cursor: pointer;
    transition: all 0.15s;
    width: fit-content;
    margin-top: 2px;
    font-weight: 500;
    background: transparent;
}
.gov-btn:hover { color: var(--link-text-color); border-color: var(--link-text-color); background: rgba(79,142,247,0.06); }
.col-name-link {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px;
    color: var(--link-text-color);
    font-weight: 600;
    line-height: 1.3;
}
.col-type { font-size: 13px; color: var(--caption-text-color); font-family: monospace; }
.key-badge { font-size: 11px; color: var(--link-text-color); display: flex; align-items: center; gap: 2px; }
.terms-row { display: flex; flex-wrap: wrap; gap: 6px; }

/* ── Term chips ── */
.term-chip {
    display: inline-flex;
    flex-direction: column;
    gap: 3px;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid;
    min-width: 90px;
    max-width: 180px;
    min-height: 68px;
    justify-content: space-between;
    transition: transform 0.1s;
    cursor: default;
}
.term-chip:hover { transform: translateY(-1px); }
.term-chip--deleted { opacity: 0.45; cursor: default; pointer-events: none; }
.term-chip--deleted:hover { transform: none; }
.term-chip__deleted-label {
    font-size: 9px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: #ef4444;
    margin-left: auto;
}
.term-chip.ddl  { border-color: rgba(167,139,250,0.3); background: rgba(167,139,250,0.07); }
.term-chip.prof { border-color: rgba(79,142,247,0.3);  background: rgba(79,142,247,0.07);  }
.term-chip.tst  { border-color: rgba(34,197,94,0.3);   background: rgba(34,197,94,0.07);   }
.term-chip.gov  { border-color: rgba(245,158,11,0.3);  background: rgba(245,158,11,0.07);  }
.term-chip.obs  { border-color: rgba(100,116,139,0.3); background: rgba(100,116,139,0.07); }
.term-chip__header { display: flex; align-items: center; gap: 5px; }
.term-chip__src {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    opacity: 0.65;
}
.term-chip.ddl  .term-chip__src { color: #a78bfa; }
.term-chip.prof .term-chip__src { color: #4f8ef7; }
.term-chip.tst  .term-chip__src { color: #22c55e; }
.term-chip.gov  .term-chip__src { color: #f59e0b; }
.term-chip.obs  .term-chip__src { color: #94a3b8; }
.term-chip__attr {
    font-size: 10px;
    font-weight: 500;
    color: var(--caption-text-color);
    opacity: 0.9;
}
.term-chip__val { font-size: 12px; font-weight: 600; color: var(--primary-text-color); word-break: break-word; }
.dc-chip-footer { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-top: 1px; }
.term-chip__badge {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    font-size: 10px;
    padding: 1px 5px;
    border-radius: 3px;
    font-weight: 600;
}
.badge-enforced { background: rgba(129,140,248,0.2); color: #a78bfa; }
.badge-tested   { background: rgba(34,197,94,0.2);   color: #22c55e; }
.badge-mon      { background: rgba(249,115,22,0.2);  color: #f97316; }
.badge-obs      { background: rgba(100,116,139,0.2); color: #94a3b8; }
.badge-decl     { background: rgba(245,158,11,0.2);  color: #f59e0b; }
.status-pill {
    font-size: 10px;
    padding: 1px 5px;
    border-radius: 3px;
    font-weight: 600;
}
.status-pill.pass { background: rgba(34,197,94,0.15);  color: #22c55e; }
.status-pill.warn { background: rgba(245,158,11,0.15); color: #f59e0b; }
.status-pill.fail { background: rgba(239,68,68,0.15);  color: #ef4444; }

/* ── Coverage matrix ── */
.dc-matrix-wrap { overflow-x: auto; }
.matrix-table-wrap { overflow-x: auto; margin-top: 4px; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.matrix-table.matrix-table--tiers .col-col { min-width: 160px; }
.matrix-table.matrix-table--tiers .tier-col { text-align: center; min-width: 110px; }
.matrix-table th {
    text-align: left;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: var(--caption-text-color);
    padding: 6px 10px;
    border-bottom: 1px solid var(--border-color);
}
.matrix-table td {
    padding: 9px 10px;
    border-bottom: 1px solid var(--border-color);
    vertical-align: middle;
    color: var(--secondary-text-color);
}
.matrix-table tr:hover td { background: rgba(128,128,128,0.03); }
.tier-cell { text-align: center; font-variant-numeric: tabular-nums; }
.tier-cell.has-terms { font-weight: 600; color: var(--primary-text-color); }
.tier-cell.no-terms  { color: var(--caption-text-color); }
.matrix-totals-row td { font-weight: 700; background: rgba(128,128,128,0.04); border-top: 2px solid var(--border-color); }

/* Tier bars — shared between HealthGrid card and matrix completeness section */
.tier-bars { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.tier-bar-row {
    display: grid;
    grid-template-columns: 160px 1fr 64px;
    align-items: center;
    gap: 8px;
    cursor: default;
}
.tier-bar-row[title] { cursor: pointer; }
.tier-bar-label { font-size: 12px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tier-bar-track { height: 8px; background: rgba(128,128,128,0.15); border-radius: 4px; overflow: hidden; }
.tier-bar-fill  { height: 100%; border-radius: 4px; transition: width 0.3s ease; }
.tier-bar-count { font-size: 11px; text-align: right; font-variant-numeric: tabular-nums; }

/* Matrix completeness section at top of matrix tab */
.matrix-completeness-section {
    background: rgba(128,128,128,0.04);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 12px 16px 14px;
    margin-bottom: 16px;
}
.matrix-completeness-subtitle { font-size: 12px; color: var(--caption-text-color); font-weight: 400; margin-left: 6px; }
.matrix-section-label { font-size: 13px; font-weight: 600; color: var(--primary-text-color); margin: 12px 0 8px; }

/* Tier dot in column name cell */
.tier-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 6px;
    flex-shrink: 0;
    vertical-align: middle;
}
.col-name--table-level { font-style: italic; color: var(--caption-text-color); font-family: inherit; }

/* Uncovered flag column */
.unc-col { text-align: center; min-width: 80px; vertical-align: middle; }
.unc-cell { text-align: center; }
.uncovered-pill {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 4px;
    background: rgba(239,68,68,0.18);
    color: #f87171;
    border: 1px solid rgba(239,68,68,0.35);
}

/* Per-table tier pills (shown when accordion closed) */
.ts-tier-pills { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-left: auto; margin-right: 8px; }
.ts-element-count { font-size: 12px; color: var(--caption-text-color); white-space: nowrap; }
.tier-pill {
    font-size: 11px;
    font-weight: 500;
    padding: 2px 7px;
    border-radius: 4px;
    border: 1px solid;
    white-space: nowrap;
}

/* Matrix group header row */
.matrix-group-header-row th { padding: 4px 6px 2px; text-align: center; }
.matrix-group-header { text-align: center; font-size: 11px; font-weight: 700; letter-spacing: 0.3px; border-bottom: 2px solid currentColor; }

/* Per-group cell tinting */
.tier-cell--tg  { background: rgba(34,197,94,0.04); }
.tier-cell--db  { background: rgba(129,140,248,0.04); }
.tier-cell--unf { background: rgba(245,158,11,0.04); }

/* Matrix table-level row — same background as regular rows */
.matrix-row--table-level td { }

.matrix-grand-total {
    margin-top: 16px;
    padding: 10px 14px;
    background: rgba(128,128,128,0.04);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    font-size: 13px;
    display: flex;
    align-items: center;
}
.matrix-grand-label { font-weight: 600; }
.matrix-grand-items { display: flex; gap: 16px; flex-wrap: wrap; margin-left: auto; }
.matrix-grand-item { font-weight: 600; color: var(--primary-text-color); }
.col-name { font-weight: 600; color: var(--primary-text-color); font-family: monospace; font-size: 13px; }
.type-tag {
    font-family: monospace;
    font-size: 11px;
    color: var(--caption-text-color);
    background: rgba(128,128,128,0.1);
    padding: 2px 6px;
    border-radius: 4px;
}
.status-icon {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    padding: 2px 7px;
    border-radius: 4px;
    font-weight: 500;
}
.status-icon.pass { color: #22c55e; background: rgba(34,197,94,0.1); }
.status-icon.warn { color: #f59e0b; background: rgba(245,158,11,0.1); }
.status-icon.fail { color: #ef4444; background: rgba(239,68,68,0.1); }
.status-icon.none { color: var(--caption-text-color); }
.anomaly-chip {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 8px; border-radius: 6px;
    font-size: 11px; font-weight: 600; border: 1px solid;
}
.anomaly-chip.definite { border-color: rgba(239,68,68,0.4); background: rgba(239,68,68,0.1); color: #ef4444; }
.anomaly-chip.likely   { border-color: rgba(245,158,11,0.4); background: rgba(245,158,11,0.1); color: #f59e0b; }
.anomaly-chip.possible { border-color: rgba(79,142,247,0.4); background: rgba(79,142,247,0.1); color: #4f8ef7; }
.tier-badges { display: flex; gap: 3px; flex-wrap: wrap; }
.tier-badge {
    font-size: 10px; padding: 2px 6px; border-radius: 20px; border: 1px solid; white-space: nowrap;
}
.tier-badge.db   { color: #818cf8; border-color: rgba(129,140,248,0.3); background: rgba(129,140,248,0.08); }
.tier-badge.test { color: #22c55e; border-color: rgba(34,197,94,0.3);   background: rgba(34,197,94,0.08);   }
.tier-badge.mon  { color: #f97316; border-color: rgba(249,115,22,0.3);  background: rgba(249,115,22,0.08);  }
.tier-badge.obs  { color: #94a3b8; border-color: rgba(100,116,139,0.3); background: rgba(100,116,139,0.08); }
.tier-badge.decl { color: #d97706; border-color: rgba(245,158,11,0.3);  background: rgba(245,158,11,0.08);  }

/* ── Term counts bar ── */
.ccbar-wrap {
    display: flex;
    align-items: flex-start;
    gap: 0;
    padding: 14px 16px;
    background: var(--card-background-color);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
}
.ccbar-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex: 1;
    min-width: 0;
}
.ccbar-group-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--caption-text-color);
    padding-bottom: 4px;
    border-bottom: 1px solid var(--border-color);
}
.ccbar-cards {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.ccbar-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    padding: 8px 12px;
    border-radius: 6px;
    background: rgba(128,128,128,0.04);
    border: 1px solid var(--border-color);
    min-width: 80px;
}
.ccbar-chip {
    font-size: 10px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 10px;
    white-space: nowrap;
    display: inline-flex;
    align-items: center;
    gap: 3px;
}
.ccbar-chip--ddl  { background: rgba(167,139,250,0.12); color: #a78bfa; border: 1px solid rgba(167,139,250,0.3); }
.ccbar-chip--prof { background: rgba(79,142,247,0.10);  color: #4f8ef7; border: 1px solid rgba(79,142,247,0.28); }
.ccbar-chip--gov  { background: rgba(245,158,11,0.10);  color: #d97706; border: 1px solid rgba(245,158,11,0.28); }
.ccbar-chip--test { background: rgba(34,197,94,0.10);   color: #16a34a; border: 1px solid rgba(34,197,94,0.28);  }
.ccbar-verif-badge {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 10px;
    white-space: nowrap;
}
.ccbar-count {
    font-size: 16px;
    font-weight: 700;
    color: var(--primary-text-color);
    line-height: 1;
}
.ccbar-divider {
    width: 1px;
    background: var(--border-color);
    align-self: stretch;
    margin: 0 16px;
    flex-shrink: 0;
}

/* ── Gap analysis ── */
.dc-gap-wrap { display: flex; flex-direction: column; }
.gap-list { display: flex; flex-direction: column; gap: 6px; }
.gap-list--indent { padding: 8px 16px 12px; }
.gap-table-badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; margin-left: 8px; }
.gap-table-badge.error   { background: rgba(239,68,68,0.12);  color: #ef4444; }
.gap-table-badge.warning { background: rgba(245,158,11,0.12); color: #f59e0b; }
.gap-table-badge.info    { background: rgba(79,142,247,0.12); color: #4f8ef7; }
.gap-item {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 10px 12px; border-radius: 6px; font-size: 13px;
}
.gap-item.error   { background: rgba(239,68,68,0.06);  border-left: 3px solid #ef4444; }
.gap-item.warning { background: rgba(245,158,11,0.06); border-left: 3px solid #f59e0b; }
.gap-item.info    { background: rgba(79,142,247,0.06); border-left: 3px solid #4f8ef7; }
.gap-icon { font-family: 'Material Symbols Rounded', sans-serif; font-size: 16px; flex-shrink: 0; margin-top: 1px; }
.gap-item.error   .gap-icon { color: #ef4444; }
.gap-item.warning .gap-icon { color: #f59e0b; }
.gap-item.info    .gap-icon { color: #4f8ef7; }
.gap-text { color: var(--secondary-text-color); line-height: 1.5; }
.gap-text code {
    font-family: monospace; font-size: 11px;
    background: rgba(128,128,128,0.12); padding: 1px 5px;
    border-radius: 3px; color: var(--primary-text-color);
}
.gap-clean {
    display: flex; align-items: center; gap: 8px;
    color: #22c55e; padding: 12px;
    background: rgba(34,197,94,0.06); border-radius: 6px;
}

/* ── YAML viewer ── */
.yaml-wrap { overflow-x: hidden; border: 1px solid var(--border-color); border-radius: 6px; }
.yaml-toolbar {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: rgba(128,128,128,0.04);
    border-bottom: 1px solid var(--border-color);
}
.yaml-copy-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    color: var(--caption-text-color);
    border: 1px solid var(--border-color);
    border-radius: 5px;
    cursor: pointer;
    background: var(--card-background-color);
    transition: color 0.15s, border-color 0.15s;
    user-select: none;
}
.yaml-copy-btn:hover { color: var(--link-text-color); border-color: rgba(79,142,247,0.4); }
.yaml-block {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px;
    line-height: 1.6;
    white-space: pre;
    color: var(--primary-text-color);
    background: var(--card-background-color);
    border: none;
    border-radius: 0 0 6px 6px;
    padding: 16px 20px;
    overflow-x: auto;
    margin: 0;
}
/* Prism YAML token colors — compatible with both light and dark themes */
.token.key     { color: #4f8ef7; font-weight: 600; }
.token.string  { color: #22c55e; }
.token.number  { color: #f97316; }
.token.boolean { color: #a78bfa; font-weight: 600; }
.token.null.keyword { color: #94a3b8; font-style: italic; }
.token.comment { color: var(--caption-text-color); font-style: italic; }
.token.punctuation { color: var(--caption-text-color); }
.token.important { color: #ef4444; font-weight: 600; }

/* ── Upload tab ── */
.upload-tab { max-width: 680px; }
.upload-desc { font-size: 13px; color: var(--secondary-text-color); margin-bottom: 20px; line-height: 1.6; }
.upload-desc-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 24px; }
.upload-desc-heading { margin: 0 0 4px; font-weight: 600; color: var(--primary-text-color); }
.upload-desc ul { margin: 0; padding-left: 18px; }
.upload-desc li { margin-bottom: 2px; }
.file-drop {
    border: 2px dashed var(--border-color);
    border-radius: 10px;
    padding: 32px;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    color: var(--caption-text-color);
    cursor: pointer;
    transition: border-color 0.2s;
}
.file-drop:hover { border-color: var(--link-text-color); }
.file-label {
    display: inline-block;
    padding: 7px 16px;
    background: var(--button-generic-background-color);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    color: var(--secondary-text-color);
    cursor: pointer;
    transition: all 0.15s;
}
.file-label:hover { color: var(--link-text-color); border-color: rgba(79,142,247,0.4); }
.file-hint { font-size: 12px; color: var(--caption-text-color); }
.file-name { font-size: 13px; color: var(--primary-text-color); display: flex; align-items: center; gap: 4px; }
.upload-error { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #ef4444; margin: 6px 0; }

/* ── Empty / misc ── */
.dc-empty {
    padding: 24px;
    text-align: center;
    color: var(--caption-text-color);
    font-size: 13px;
}

/* ── Help button (far-right of tab bar, visually distinct from tabs) ── */
.dc-tabs-spacer { flex: 1; }
.dc-tab-help {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    font-weight: 500;
    color: var(--caption-text-color);
    background: transparent;
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 3px 12px;
    margin: 5px 0 5px 8px;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s, background 0.15s;
    white-space: nowrap;
    /* Override dc-tab underline styles */
    border-bottom: 1px solid var(--border-color) !important;
    margin-bottom: 5px !important;
}
.dc-tab-help:hover {
    color: var(--link-text-color);
    border-color: rgba(79,142,247,0.4) !important;
    background: rgba(79,142,247,0.06);
}
.dc-tab-help.active {
    color: var(--link-text-color);
    border-color: rgba(79,142,247,0.5) !important;
    background: rgba(79,142,247,0.10);
}

/* ── Terms help panel ── */
.terms-help-panel {
    padding: 28px 0 12px;
    max-width: 960px;
}
.help-intro {
    font-size: 14px;
    color: var(--secondary-text-color);
    line-height: 1.6;
    margin-bottom: 28px;
    padding: 14px 18px;
    background: rgba(79,142,247,0.05);
    border-left: 3px solid rgba(79,142,247,0.4);
    border-radius: 0 6px 6px 0;
}
.help-em { font-weight: 600; color: var(--primary-text-color); }
.help-columns {
    display: grid;
    grid-template-columns: 1fr 2px 1fr;
    gap: 0 24px;
    align-items: start;
}
.help-divider {
    background: var(--border-color);
    align-self: stretch;
    margin: 32px 0;
}
.help-col { display: flex; flex-direction: column; gap: 0; }
.help-section-label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--caption-text-color);
    margin-bottom: 12px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border-color);
}
.help-col-header {
    display: grid;
    grid-template-columns: 100px 130px 1fr;
    gap: 10px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--caption-text-color);
    padding: 0 4px 6px;
    margin-bottom: 4px;
    border-bottom: 1px dashed var(--border-color);
}
.help-col-header--verif { grid-template-columns: 130px 1fr; }
.help-col--verif .help-row { grid-template-columns: 130px 1fr; }
.help-row {
    display: grid;
    grid-template-columns: 100px 130px 1fr;
    gap: 10px;
    align-items: flex-start;
    padding: 8px 4px;
    border-radius: 4px;
    transition: background 0.1s;
}
.help-row:hover { background: rgba(128,128,128,0.04); }
.help-src-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 10px;
    border-radius: 10px;
    white-space: nowrap;
    align-self: start;
}
.chip-ddl  { background: rgba(167,139,250,0.15); color: #a78bfa; border: 1px solid rgba(167,139,250,0.3); }
.chip-prof { background: rgba(79,142,247,0.12);  color: #4f8ef7; border: 1px solid rgba(79,142,247,0.3);  }
.chip-gov  { background: rgba(245,158,11,0.12);  color: #d97706; border: 1px solid rgba(245,158,11,0.3);  }
.chip-tst  { background: rgba(34,197,94,0.12);   color: #16a34a; border: 1px solid rgba(34,197,94,0.3);   }
.help-verif {
    font-size: 12px;
    color: var(--secondary-text-color);
    align-self: start;
    line-height: 1.4;
}
.help-desc {
    font-size: 12px;
    color: var(--secondary-text-color);
    line-height: 1.5;
}
.help-verif-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 10px;
    white-space: nowrap;
    align-self: start;
}
.hbadge-db   { background: rgba(129,140,248,0.15); color: #818cf8; border: 1px solid rgba(129,140,248,0.3); }
.hbadge-test { background: rgba(34,197,94,0.12);   color: #16a34a; border: 1px solid rgba(34,197,94,0.3);   }
.hbadge-mon  { background: rgba(249,115,22,0.12);  color: #ea580c; border: 1px solid rgba(249,115,22,0.3);  }
.hbadge-obs  { background: rgba(100,116,139,0.12); color: #64748b; border: 1px solid rgba(100,116,139,0.3); }
.hbadge-decl { background: rgba(245,158,11,0.12);  color: #d97706; border: 1px solid rgba(245,158,11,0.3);  }
.help-footer {
    margin-top: 32px;
    font-size: 13px;
    color: var(--secondary-text-color);
    line-height: 1.6;
    padding: 14px 18px;
    background: rgba(128,128,128,0.04);
    border: 1px solid var(--border-color);
    border-radius: 6px;
}

/* ── Suite scope bar ── */
.suite-scope-bar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;
    padding: 8px 12px;
    background: rgba(79,142,247,0.04);
    border: 1px solid rgba(79,142,247,0.15);
    border-radius: 8px;
}
.suite-scope-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--caption-text-color);
    display: flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
}
.suite-scope-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    flex: 1;
}
.suite-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    font-weight: 500;
    padding: 3px 9px 3px 6px;
    border-radius: 20px;
    border: 1px solid;
}
.suite-chip__icon {
    font-family: 'Material Symbols Rounded', sans-serif;
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 16;
    font-size: 13px;
    line-height: 1;
}
.suite-chip--in  { color: #16a34a; background: rgba(34,197,94,0.08);  border-color: rgba(34,197,94,0.3);  }
.suite-chip--out { color: #94a3b8; background: rgba(100,116,139,0.06); border-color: rgba(100,116,139,0.2); text-decoration: line-through; opacity: 0.75; }
.suite-chip--clickable { cursor: pointer; transition: filter 0.15s, box-shadow 0.15s; }
.suite-chip--clickable:hover { filter: brightness(1.08); box-shadow: 0 1px 6px rgba(0,0,0,0.12); text-decoration: underline; opacity: 1; }
.suite-chip__arrow { opacity: 0.4; transition: opacity 0.15s; margin-left: 2px; }
.suite-chip--clickable:hover .suite-chip__arrow { opacity: 1; }
.suite-scope-hint {
    font-size: 11px;
    color: var(--caption-text-color);
    font-style: italic;
    flex-basis: 100%;
}

/* ── Multi-select: select button & bulk action bar ── */
.select-mode-btn { margin-left: 4px; display: inline-flex; align-items: center; gap: 3px; }
.select-mode-btn .material { font-size: 13px; }
.bulk-action-bar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 10px;
    padding: 8px 12px;
    background: rgba(239,68,68,0.05);
    border: 1px solid rgba(239,68,68,0.2);
    border-radius: 8px;
    font-size: 12px;
}
.bulk-action-count {
    font-weight: 600;
    color: var(--primary-text-color);
    min-width: 70px;
}
.bulk-action-btn {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 3px 10px;
    border-radius: 20px;
    border: 1px solid var(--border-color);
    background: var(--button-generic-background-color);
    color: var(--secondary-text-color);
    cursor: pointer;
    font-size: 11px;
    transition: all 0.15s;
    user-select: none;
}
.bulk-action-btn:hover { color: var(--link-text-color); border-color: rgba(79,142,247,0.4); background: rgba(79,142,247,0.08); }
.bulk-action-btn--delete { color: #ef4444; border-color: rgba(239,68,68,0.3); background: rgba(239,68,68,0.07); }
.bulk-action-btn--delete:hover { color: #dc2626; border-color: rgba(239,68,68,0.6); background: rgba(239,68,68,0.14); }
.bulk-action-btn--cancel { color: var(--caption-text-color); }
.bulk-action-btn--confirm-yes { color: #fff; border-color: #dc2626; background: #dc2626; font-weight: 600; }
.bulk-action-btn--confirm-yes:hover { background: #b91c1c; border-color: #b91c1c; color: #fff; }
/* Flash animation for Select All buttons */
@keyframes btn-flash {
    0%   { background: rgba(79,142,247,0.25); border-color: rgba(79,142,247,0.7); color: var(--link-text-color); }
    60%  { background: rgba(79,142,247,0.18); }
    100% { background: var(--button-generic-background-color); border-color: var(--border-color); color: var(--secondary-text-color); }
}
.bulk-action-btn--flashing { animation: btn-flash 0.65s ease-out forwards; }
.bulk-action-bar--confirming { background: rgba(239,68,68,0.08); border-color: rgba(239,68,68,0.4); }
.bulk-action-confirm__msg { flex: 1; font-weight: 600; color: #dc2626; display: inline-flex; align-items: center; gap: 5px; }
.bulk-action-hint { color: var(--caption-text-color); font-style: italic; display: inline-flex; align-items: center; gap: 4px; flex: 1; font-size: 11px; }
/* ── Multi-select: chip checkbox & selected state ── */
.term-chip { position: relative; }
.term-chip__checkbox {
    position: absolute;
    top: 4px;
    left: 4px;
    cursor: pointer;
    z-index: 2;
    line-height: 0;
    display: none;           /* hidden by default */
    pointer-events: none;    /* invisible = not interactive */
}
/* Checkbox visibility is controlled entirely by JS (enterSelectionMode / exitSelectionMode) */
.term-chip__checkbox input[type='checkbox'] {
    width: 16px;
    height: 16px;
    cursor: pointer;
    accent-color: #22c55e;
    display: block;
}
.term-chip--selected {
    outline: 2px solid rgba(34,197,94,0.8);
    outline-offset: 1px;
    background: rgba(34,197,94,0.1) !important;
}
.term-chip--deleting {
    outline: 2px solid rgba(239,68,68,0.85);
    outline-offset: 1px;
    background: rgba(239,68,68,0.1) !important;
    opacity: 0.85;
}

/* ── Coverage matrix scope note ── */
.matrix-scope-note {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--caption-text-color);
    padding: 8px 12px;
    margin-bottom: 10px;
    background: rgba(79,142,247,0.04);
    border: 1px solid rgba(79,142,247,0.12);
    border-radius: 6px;
}

/* ── Collapsible table sections ── */
.table-section-header {
    cursor: pointer;
    user-select: none;
}
.table-section-header:hover { background: var(--hover-background-color, rgba(128,128,128,0.06)); }
.table-section-chevron {
    margin-left: auto;
    font-family: 'Material Symbols Rounded', sans-serif;
    font-variation-settings: 'FILL' 0, 'wght' 300, 'GRAD' 0, 'opsz' 20;
    font-size: 18px;
    color: var(--caption-text-color);
    transition: transform 0.2s;
    line-height: 1;
}
.table-section-chevron.open { transform: rotate(180deg); }

/* ── Term chip — clickable indicator ── */
.term-chip--clickable { cursor: pointer; }
.term-chip--clickable:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.12); }

/* ── Differences card ── */
.diff-rows { margin-top: 6px; }
.diff-status-row {
    display: flex; align-items: baseline; gap: 8px; padding: 2px 4px;
    border-radius: 4px; cursor: pointer;
}
.diff-status-row:hover { background: var(--hover-background-color, rgba(128,128,128,0.06)); }
.diff-status-count { font-size: 15px; font-weight: 700; min-width: 28px; text-align: right; color: var(--primary-text-color); }
.diff-status-label { font-size: 12px; color: var(--caption-text-color); text-transform: lowercase; }

/* ── Compliance card content ── */
.ct-card-content { margin-top: 4px; }
.ct-tier-row { display: flex; align-items: baseline; gap: 8px; padding: 1px 0; }
.ct-count { font-size: 15px; font-weight: 700; min-width: 28px; text-align: right; color: var(--primary-text-color); }
.ct-label { font-size: 12px; color: var(--caption-text-color); }
.ct-sub-row { display: flex; align-items: flex-start; padding-left: 36px; padding-top: 2px; gap: 6px; }
.ct-sublabel { font-size: 11px; color: var(--caption-text-color); min-width: 52px; padding-top: 1px; }
.ct-chips { display: flex; flex-wrap: wrap; gap: 2px 8px; }
.ct-chip { font-size: 11px; white-space: nowrap; }

/* ── Differences & Compliance tabs ── */
.dc-differences-tab { padding: 16px 0; }
.dc-compliance-tab  { padding: 16px 0; }
.dc-empty-state { padding: 32px; text-align: center; color: var(--caption-text-color); font-size: 14px; }

/* Accordions */
.diff-accordion { margin-bottom: 8px; border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden; }
.diff-accordion-header {
    display: flex; align-items: center; gap: 6px; padding: 9px 14px;
    background: var(--card-background-color); color: var(--secondary-text-color);
    font-size: 13px; font-weight: 600; cursor: pointer; user-select: none;
    border-left: 3px solid transparent; /* overridden inline per accordion */
    transition: background 0.1s;
}
.diff-accordion-header:hover { background: var(--hover-background-color, rgba(128,128,128,0.06)); }
.diff-accordion-label { flex: 0 0 auto; }
.diff-count-badge {
    font-size: 11px; font-weight: 700; border-radius: 10px; padding: 1px 7px;
    border: 1px solid; margin-left: 2px; flex-shrink: 0;
}
.accordion-header-chips { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-left: 6px; }
.accordion-header-chip {
    font-size: 10px; font-weight: 600; border-radius: 10px; padding: 1px 6px;
    border: 1px solid; white-space: nowrap;
}

/* Term tables — shared by Differences and Compliance accordions */
.dc-term-table-wrap { overflow-x: auto; }
.dc-term-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.dc-term-table th {
    text-align: left; font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.6px; color: var(--caption-text-color);
    padding: 6px 10px; border-bottom: 1px solid var(--border-color);
}
.dc-term-table th:first-child { padding-left: 14px; }
.dc-term-table td {
    padding: 8px 10px; border-bottom: 1px solid var(--border-color);
    vertical-align: middle; color: var(--secondary-text-color);
    transition: background 0.1s;
}
.dc-term-table tr:last-child td { border-bottom: none; }
.dc-term-row:hover td { background: rgba(128,128,128,0.04); }

/* Column cells */
.diff-element-cell {
    font-weight: 600; color: var(--primary-text-color);
    font-family: monospace; font-size: 12px; white-space: nowrap;
    padding-left: 14px !important; /* space for the left-border stripe */
}
.diff-type-cell { color: var(--caption-text-color); font-size: 12px; white-space: nowrap; }
.diff-detail-cell { font-size: 12px; }
.diff-detail-before { color: var(--caption-text-color); }
.diff-detail-arrow  { color: var(--caption-text-color); opacity: 0.5; }
.diff-detail-after  { color: #f59e0b; font-weight: 600; }

/* Compliance status chips — tinted border pills */
.compliance-chip {
    font-size: 10px; font-weight: 600; border-radius: 10px;
    padding: 1px 7px; white-space: nowrap; text-transform: lowercase;
    display: inline-block; border: 1px solid;
}

/* Tab summary bars */
.tab-summary-bar {
    display: flex; align-items: center; flex-wrap: wrap; gap: 14px;
    padding: 10px 16px; margin-bottom: 12px;
    background: var(--card-background-color);
    border: 1px solid var(--border-color); border-radius: 6px;
}
.tab-summary-meta { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.tab-summary-vsep { width: 1px; height: 18px; background: var(--border-color); }
.tab-summary-kv-label { font-size: 11px; font-weight: 600; color: var(--caption-text-color); text-transform: uppercase; letter-spacing: 0.04em; }
.tab-summary-kv-num   { font-size: 15px; font-weight: 700; color: var(--primary-text-color); }

/* Stacked proportion bar */
.diff-stacked-bar {
    display: flex; height: 6px; border-radius: 3px; overflow: hidden;
    flex: 1; min-width: 80px; max-width: 200px; gap: 1px;
}
.diff-bar-seg { height: 100%; border-radius: 1px; transition: width 0.3s; }

/* Summary pills */
.diff-summary-pills { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.diff-summary-pill {
    display: flex; align-items: center; gap: 5px;
    border-radius: 10px; padding: 2px 9px; border: 1px solid;
    cursor: pointer; transition: filter 0.15s;
}
.diff-summary-pill:hover { filter: brightness(1.1); }
.diff-summary-count { font-size: 12px; font-weight: 700; }
.diff-summary-label { font-size: 11px; font-weight: 500; }

/* Compliance summary bar sections */
.compliance-summary-section { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.compliance-summary-tier { font-size: 11px; font-weight: 700; color: var(--caption-text-color); text-transform: uppercase; letter-spacing: 0.04em; }
.compliance-summary-stat { font-size: 12px; font-weight: 600; }
.compliance-summary-sep { width: 1px; height: 20px; background: var(--border-color); flex-shrink: 0; }
`);

export { DataContract };
