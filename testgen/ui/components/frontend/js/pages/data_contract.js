/**
 * Data Contract page — VanJS component.
 *
 * @typedef ClaimItem
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
 * @property {ClaimItem[]} static_claims
 * @property {ClaimItem[]} live_claims
 *
 * @typedef TableData
 * @type {object}
 * @property {string} name
 * @property {number} column_count
 * @property {ClaimItem[]} table_claims
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

const likelihoodClass = (l) =>
    ({ Definite: 'definite', Likely: 'likely', Possible: 'possible' }[l] ?? 'none');

// ── Claim chip ────────────────────────────────────────────────────────────────

const ClaimChip = (claim, tableName, colName) => {
    const srcCls = SOURCE_CLASS[claim.source] || 'obs';
    const srcLabel = SOURCE_LABEL[claim.source] || claim.source;
    const verif = VERIF_META[claim.verif] || { icon: '', label: claim.verif, cls: 'badge-obs' };
    const isLive = claim.source === 'test';
    const status = claim.status;
    const statusCls = status ? statusClass(status) : null;

    // Only hygiene/anomaly claims (verif=monitored) skip the detail dialog.
    const hasDetail = claim.verif !== 'monitored';

    return div(
        {
            class: `claim-chip ${srcCls}${hasDetail ? ' claim-chip--clickable' : ''}`,
            onclick: hasDetail
                ? (e) => {
                    e.stopPropagation();
                    emitEvent('ClaimDetailClicked', {
                        payload: { claim, tableName, colName },
                    });
                }
                : null,
        },
        span({ class: 'claim-chip__src' }, srcLabel),
        span({ class: 'claim-chip__val' }, claim.value),
        div(
            { class: 'dc-chip-footer' },
            span({ class: `claim-chip__badge ${verif.cls}` }, `${verif.icon} ${verif.label}`),
            isLive && statusCls && statusCls !== 'none'
                ? span({ class: `status-pill ${statusCls}` }, status)
                : '',
        ),
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
        ),
        div(
            { class: 'claims-row' },
            ...col.static_claims.map((c) => ClaimChip(c, tableName, col.name)),
            ...col.live_claims.map((c) => ClaimChip(c, tableName, col.name)),
        ),
    );
};

// ── Table-level claims row ────────────────────────────────────────────────────

const TableClaimsRow = (tableClaims, tableName) => {
    if (!tableClaims || !tableClaims.length) return '';
    return div(
        { class: 'col-row table-claims-row' },
        div(
            { class: 'col-header' },
            span({ class: 'col-name-link table-level-label' }, mat('table_rows', 13), ' Table-level'),
        ),
        div(
            { class: 'claims-row' },
            ...tableClaims.map((c) => ClaimChip(c, tableName, '')),
        ),
    );
};

// ── Table section ─────────────────────────────────────────────────────────────

const TableSection = (tableData, startOpen = false) => {
    const open = van.state(startOpen);
    const tblClaimCount = (tableData.table_claims || []).length;
    const colClaimCount = tableData.columns.reduce(
        (sum, col) => sum + col.static_claims.length + col.live_claims.length, 0,
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
                () => !open.val ? span({ class: 'count-badge count-badge--table' }, `${tblClaimCount} table-level claim${tblClaimCount !== 1 ? 's' : ''}`) : '',
                () => !open.val ? span({ class: 'count-badge count-badge--claims' }, `${colClaimCount} column-level claim${colClaimCount !== 1 ? 's' : ''}`) : '',
            ),
            span({ class: () => `table-section-chevron${open.val ? ' open' : ''}` }, 'expand_more'),
        ),
        () => open.val
            ? div(
                TableClaimsRow(tableData.table_claims || [], tableData.name),
                ...tableData.columns.map((col) => ColumnRow(col, tableData.name)),
              )
            : '',
    );
};

// ── Claims detail tab ─────────────────────────────────────────────────────────

const ClaimsDetail = (tables, activeFilter) => {
    const grandTotal = tables.reduce(
        (sum, t) => sum + t.columns.reduce(
            (s, col) => s + col.static_claims.length + col.live_claims.length, 0,
        ), 0,
    );
    return div(
        div(
            { class: 'section-header' },
            div(
                { class: 'section-title' },
                mat('list_alt'), ' Data Contract Claims Detail',
                span({ style: 'font-weight: 300; font-size: 0.85em; color: var(--caption-text-color); margin-left: 6px;' }, `(${grandTotal} total claims)`),
            ),
            div(
                { class: 'filter-pills' },
                span({ class: 'dc-label' }, 'Filter:'),
                ...['all', 'failing', 'uncovered'].map((f) =>
                    span(
                        {
                            class: () => `filter-pill ${activeFilter.val === f ? 'active' : ''}`,
                            onclick: () => { activeFilter.val = f; },
                        },
                        f.charAt(0).toUpperCase() + f.slice(1),
                    )
                ),
            ),
        ),
        () => {
            const filter = activeFilter.val;
            const visible = tables.filter((t) => {
                if (filter === 'all') return true;
                return t.columns.some((col) => {
                    if (filter === 'failing') return col.status === 'failing';
                    if (filter === 'uncovered') return !col.covered;
                    return true;
                });
            });
            if (!visible.length) {
                return div({ class: 'dc-empty' }, 'No columns match the current filter.');
            }
            const filtered = visible.map((t) => {
                if (filter === 'all') return t;
                const cols = t.columns.filter((col) => {
                    if (filter === 'failing') return col.status === 'failing';
                    if (filter === 'uncovered') return !col.covered;
                    return true;
                });
                return { ...t, columns: cols };
            });
            return div(...filtered.map((t, i) => TableSection(t, i === 0)));
        },
    );
};

// ── Coverage matrix tab ───────────────────────────────────────────────────────

const MATRIX_COLS = [
    { key: 'db',     label: '🏛️ DB Enforced' },
    { key: 'tested', label: '⚡ Tested'       },
    { key: 'mon',    label: '📡 Monitored'    },
    { key: 'obs',    label: '📸 Observed'     },
    { key: 'decl',   label: '🏷️ Declared'    },
];

const fmtCount = (n) => (n > 0 ? String(n) : '—');

const MatrixTableSection = (tableName, rows, startOpen, totals) => {
    const open = van.state(startOpen);
    return div(
        { class: 'table-section' },
        div(
            {
                class: 'table-section-header',
                onclick: () => { open.val = !open.val; },
            },
            mat('table_rows', 22),
            span({ class: 'ts-name' }, tableName),
            div({ class: 'ts-meta' },
                span({ class: 'count-badge' }, `${rows.length} col${rows.length !== 1 ? 's' : ''}`),
                ...MATRIX_COLS
                    .filter((c) => c.key === 'mon' || totals[c.key] > 0)
                    .map((c) => () => open.val ? '' : span({ class: 'count-badge matrix-collapsed-summary' }, `${c.label} ${totals[c.key]}`)),
            ),
            span({ class: () => `table-section-chevron${open.val ? ' open' : ''}` }, 'expand_more'),
        ),
        () => open.val
            ? div(
                { class: 'matrix-table-wrap' },
                table(
                    { class: 'matrix-table matrix-table--tiers' },
                    thead(tr(
                        th({ class: 'col-col' }, 'Column'),
                        ...MATRIX_COLS.map((c) => th({ class: 'tier-col', title: c.label }, c.label)),
                    )),
                    tbody(
                        ...rows.map((row) => tr(
                            td(span({ class: 'col-name' }, row.column)),
                            ...MATRIX_COLS.map((c) => td(
                                { class: `tier-cell ${row[c.key] > 0 ? 'has-claims' : 'no-claims'}` },
                                fmtCount(row[c.key]),
                            )),
                        )),
                        tr(
                            { class: 'matrix-totals-row' },
                            td('Total'),
                            ...MATRIX_COLS.map((c) => td({ class: 'tier-cell' }, fmtCount(totals[c.key]))),
                        ),
                    ),
                ),
              )
            : '',
    );
};

const CoverageMatrix = (matrix, suiteScope, tables) => {
    if (!matrix.length) {
        return div({ class: 'dc-empty' }, 'No schema data available.');
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

    const countsBar = (tables && tables.length) ? ClaimCountsBar(tables) : '';

    const tableEntries = [...tableMap.entries()];
    return div(
        { class: 'dc-matrix-wrap' },
        countsBar,
        scopeNote,
        ...tableEntries.map(([tableName, rows], idx) => {
            const totals = { db: 0, tested: 0, mon: 0, obs: 0, decl: 0 };
            for (const r of rows) for (const c of MATRIX_COLS) totals[c.key] += r[c.key] || 0;
            return MatrixTableSection(tableName, rows, idx === 0, totals);
        }),
        div(
            { class: 'matrix-grand-total' },
            span({ class: 'matrix-grand-label' }, 'All tables'),
            div({ class: 'matrix-grand-items' },
                ...MATRIX_COLS.map((c) => span({ class: 'matrix-grand-item' }, `${c.label} ${grand[c.key]}`)),
            ),
        ),
    );
};

// ── Claim counts summary bar ──────────────────────────────────────────────────

const ClaimCountsBar = (tables) => {
    // Accumulate counts across all tables/columns for both static and live claims
    // monitor source is grouped under test (monitors are a type of test, not a distinct origin)
    const bySrc  = { ddl: 0, profiling: 0, governance: 0, test: 0 };
    const byVerif = { db_enforced: 0, tested: 0, monitored: 0, observed: 0, declared: 0 };

    for (const t of tables) {
        for (const c of (t.table_claims || [])) {
            const srcKey = c.source === 'monitor' ? 'test' : c.source;
            if (srcKey in bySrc)     bySrc[srcKey]++;
            if (c.verif in byVerif)  byVerif[c.verif]++;
        }
        for (const col of t.columns) {
            for (const c of [...col.static_claims, ...col.live_claims]) {
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
    const countsBar = (tables && tables.length) ? ClaimCountsBar(tables) : '';

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

const YamlViewer = (yamlContent) => {
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

    return div(
        { class: 'yaml-wrap' },
        div({ class: 'yaml-toolbar' }, copyBtn),
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
                'Upload a modified YAML to sync selected fields back to TestGen. ',
                'Only the fields listed below are writable — everything else is ignored.',
            ),
            div({ class: 'upload-desc-cols' },
                div(
                    p({ class: 'upload-desc-heading' }, 'Updated on upload'),
                    ul(
                        li('Contract version, status, and description'),
                        li('Business domain and data product'),
                        li('Latency SLA (profiling delay days)'),
                        li('Quality rule thresholds, tolerances, severity, and description'),
                    ),
                ),
                div(
                    p({ class: 'upload-desc-heading' }, 'Not updated — manage in TestGen'),
                    ul(
                        li('Tables, columns, and data types'),
                        li('Which quality rules (tests) exist'),
                        li('Test suite settings and connections'),
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

const HealthGrid = (health, activeFilter, activeTab) => {
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

    return div(
        { class: 'health-grid' },
        // — Coverage card
        div(
            {
                class: 'health-card coverage health-card--link',
                onclick: () => { activeTab.val = 'gaps'; },
                title: 'View Completeness Analysis',
            },
            div({ class: 'health-card__label' },
                mat('verified', 13), ' Contract Completeness',
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
            div({ class: `health-card__value ${coverageCls}` }, `${health.coverage_pct}%`),
            div({ class: 'progress-track' },
                div({ class: `progress-fill ${coverageCls}`, style: `width:${health.coverage_pct}%` }),
            ),
            div({ class: 'health-card__sub' }, `${health.covered} of ${health.n_cols} columns have ≥1 non-schema claim`),
            health.n_cols - health.covered > 0
                ? filterButton(`View ${health.n_cols - health.covered} uncovered →`, 'uncovered')
                : '',
        ),
        // — Test health card
        div(
            {
                class: () => `health-card tests${health.last_test_run_id ? ' health-card--link' : ''}`,
                style: 'position: relative;',
                onclick: handleTestCardClick,
                title: suiteRuns.length > 1 ? 'Click to choose a test suite' : (health.last_test_run_id ? 'View test results' : ''),
            },
            div({ class: 'health-card__label' },
                mat('science', 13), ' Test Health',
                health.last_test_run_id
                    ? span({ class: 'health-card__nav-icon' }, mat(suiteRuns.length > 1 ? 'expand_more' : 'open_in_new', 11))
                    : '',
            ),
            totalRunTests
                ? [
                    div(
                        { class: 'health-card__value-row' },
                        span({ class: 'health-card__value neutral', style: 'font-size:24px' }, `${totalRunTests} tests`),
                        suiteRuns.length > 1
                            ? span({ class: 'health-card__suite-inline' }, `${suiteRuns.length} suites`)
                            : (health.suites_total > 0 && health.suites_included < health.suites_total
                                ? span({ class: 'health-card__suite-inline' }, `${health.suites_included} of ${health.suites_total}`)
                                : ''),
                    ),
                    div(
                        { class: 'summary-bar' },
                        totalPassed  ? SummarySegment(Math.round(100 * totalPassed  / totalRunTests), '#22c55e') : '',
                        totalWarning ? SummarySegment(Math.round(100 * totalWarning / totalRunTests), '#f59e0b') : '',
                        totalFailed  ? SummarySegment(Math.round(100 * totalFailed  / totalRunTests), '#ef4444') : '',
                    ),
                    div(
                        { class: 'summary-counts' },
                        CountDot('#22c55e', 'passed',  totalPassed),
                        CountDot('#f59e0b', 'warn',    totalWarning),
                        CountDot('#ef4444', 'failed',  totalFailed),
                    ),
                  ]
                : div({ class: 'health-card__sub' }, 'No tests defined yet'),
            health.last_test_run
                ? div({ class: 'health-card__run-time' }, mat('schedule', 11), ` Last run: ${health.last_test_run}`)
                : div({ class: 'health-card__run-time' }, mat('schedule', 11), ' Never run'),
        ),
        // — Hygiene card
        div(
            {
                class: () => `health-card hygiene${health.last_profiling_run_id ? ' health-card--link' : ''}`,
                onclick: health.last_profiling_run_id
                    ? () => emitEvent('LinkClicked', { href: 'profiling-runs:hygiene', params: { run_id: health.last_profiling_run_id } })
                    : null,
                title: health.last_profiling_run_id ? 'View hygiene issues' : '',
            },
            div({ class: 'health-card__label' },
                mat('health_and_safety', 13), ' Hygiene',
                health.last_profiling_run_id ? span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)) : '',
            ),
            health.hygiene_total
                ? [
                    div({ class: 'health-card__value warn' }, `${health.hygiene_total} issues`),
                    div(
                        { class: 'summary-counts', style: 'margin-top:8px' },
                        CountDot('#ef4444', 'definite', health.hygiene_definite),
                        CountDot('#f59e0b', 'likely',   health.hygiene_likely),
                        CountDot('#94a3b8', 'possible', health.hygiene_possible),
                    ),
                  ]
                : div({ class: 'health-card__value good' }, 'Clean'),
            health.last_profiling_run
                ? div({ class: 'health-card__run-time' }, mat('schedule', 11), ` Last profiled: ${health.last_profiling_run}`)
                : div({ class: 'health-card__run-time' }, mat('schedule', 11), ' Never profiled'),
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
                title: `Go to test suite: ${name}`,
                onclick: () => emitEvent('LinkClicked', {
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
            span({ class: 'suite-chip__arrow' }, mat('arrow_forward', 10)),
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
    const statusColors = {
        active:     { bg: 'rgba(34,197,94,0.15)',   color: '#22c55e', border: 'rgba(34,197,94,0.3)'   },
        proposed:   { bg: 'rgba(79,142,247,0.15)',  color: '#4f8ef7', border: 'rgba(79,142,247,0.3)'  },
        draft:      { bg: 'rgba(249,115,22,0.15)',  color: '#f97316', border: 'rgba(249,115,22,0.3)'  },
        deprecated: { bg: 'rgba(239,68,68,0.15)',   color: '#ef4444', border: 'rgba(239,68,68,0.3)'   },
        retired:    { bg: 'rgba(100,116,139,0.15)', color: '#94a3b8', border: 'rgba(100,116,139,0.3)' },
    };
    const sc = statusColors[meta.status] || statusColors.draft;

    const downloadYaml = () => {
        const blob = new Blob([yamlContent || ''], { type: 'text/yaml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${tgName}_contract.yaml`;
        a.click();
        URL.revokeObjectURL(url);
    };

    return div(
        { class: 'dc-page-header' },
        div(
            { class: 'dc-page-header__left' },
            h2(
                { class: 'dc-page-title' },
                mat('contract', 22),
                ' ',
                tgName,
                span(
                    {
                        class: 'status-chip',
                        style: `background:${sc.bg};color:${sc.color};border:1px solid ${sc.border}`,
                    },
                    meta.status.charAt(0).toUpperCase() + meta.status.slice(1),
                ),
            ),
            meta.description_purpose
                ? p({ class: 'purpose-text' }, meta.description_purpose)
                : '',
            div(
                { class: 'meta-pills' },
                meta.version    ? span({ class: 'pill' }, mat('tag', 13), ` v${meta.version}`)          : '',
                meta.domain     ? span({ class: 'pill' }, mat('domain', 13), ` ${meta.domain}`)         : '',
                meta.data_product ? span({ class: 'pill' }, mat('inventory_2', 13), ` ${meta.data_product}`) : '',
                meta.server_type  ? span({ class: 'pill' }, mat('storage', 13), ` ${meta.server_type}`)  : '',
            ),
            suiteScope ? SuiteScope(suiteScope, meta) : '',
        ),
        div(
            { class: 'dc-page-actions' },
            Button({
                type: 'stroked',
                icon: 'refresh',
                label: 'Refresh',
                width: 'fit-content',
                onclick: () => emitEvent('RefreshClicked', {}),
            }),
            Button({
                type: 'stroked',
                icon: 'download',
                label: 'Download YAML',
                width: 'fit-content',
                onclick: downloadYaml,
            }),
        ),
    );
};

// ── Tab bar ───────────────────────────────────────────────────────────────────

const TABS = [
    { id: 'overview',  label: 'Overview'        },
    { id: 'matrix',    label: 'Coverage Matrix' },
    { id: 'yaml',      label: 'YAML'            },
    { id: 'upload',    label: 'Upload Changes'  },
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
            mat('help_outline', 13), ' What are contract claims?',
        ),
    );

// ── Claims help panel ─────────────────────────────────────────────────────────

const ClaimsHelpPanel = () => {
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
        { class: 'claims-help-panel' },
        div(
            { class: 'help-intro' },
            'A ',
            span({ class: 'help-em' }, 'contract claim'),
            ' is any assertion TestGen can make about a column. Every claim has two dimensions: ',
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
                SectionLabel('Claim Sources'),
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
            ' measures what percentage of columns have at least one non-schema claim ',
            '(classification, description, format pattern, or a quality test rule). ',
            'Columns with only DDL claims — and nothing richer — appear in the ',
            span({ class: 'help-em' }, 'Uncovered'),
            ' filter on the Overview tab.',
        ),
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

    const activeTab = van.state('overview');
    const activeFilter = van.state('all');

    return div(
        { id: wrapperId, class: 'dc-page' },
        () => {
            const tgName     = getValue(props.table_group_name) || '';
            const meta       = getValue(props.meta)         || {};
            const health     = getValue(props.health)       || {};
            const yaml       = getValue(props.yaml_content) || '';
            const tables     = getValue(props.tables)       || [];
            const matrix     = getValue(props.coverage_matrix) || [];
            const gaps       = getValue(props.gaps)         || {};
            const suiteScope = getValue(props.suite_scope)  || {};

            return div(
                PageHeader(tgName, meta, yaml, suiteScope),
                HealthGrid(health, activeFilter, activeTab),
                TabBar(activeTab),
                () => {
                    const tab = activeTab.val;
                    if (tab === 'overview') return ClaimsDetail(tables, activeFilter);
                    if (tab === 'matrix')   return CoverageMatrix(matrix, suiteScope, tables);
                    if (tab === 'yaml')     return YamlViewer(yaml);
                    if (tab === 'upload')   return UploadTab();
                    if (tab === 'help')     return ClaimsHelpPanel();
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
.dc-page-title {
    margin: 0 0 6px 0;
    font-size: 22px;
    font-weight: 600;
    color: var(--primary-text-color);
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}
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
.dc-page-actions { display: flex; gap: 8px; align-items: flex-start; flex-shrink: 0; }

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
.health-card__value-row { display: flex; align-items: baseline; gap: 8px; }
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

/* ── Table section (claims detail) ── */
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
.count-badge--claims {
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
.table-claims-row {
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
.col-name-link {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px;
    color: var(--link-text-color);
    font-weight: 600;
    line-height: 1.3;
}
.col-type { font-size: 13px; color: var(--caption-text-color); font-family: monospace; }
.key-badge { font-size: 11px; color: var(--link-text-color); display: flex; align-items: center; gap: 2px; }
.claims-row { display: flex; flex-wrap: wrap; gap: 6px; }

/* ── Claim chips ── */
.claim-chip {
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
.claim-chip:hover { transform: translateY(-1px); }
.claim-chip.ddl  { border-color: rgba(167,139,250,0.3); background: rgba(167,139,250,0.07); }
.claim-chip.prof { border-color: rgba(79,142,247,0.3);  background: rgba(79,142,247,0.07);  }
.claim-chip.tst  { border-color: rgba(34,197,94,0.3);   background: rgba(34,197,94,0.07);   }
.claim-chip.gov  { border-color: rgba(245,158,11,0.3);  background: rgba(245,158,11,0.07);  }
.claim-chip.obs  { border-color: rgba(100,116,139,0.3); background: rgba(100,116,139,0.07); }
.claim-chip__src {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    opacity: 0.65;
}
.claim-chip.ddl  .claim-chip__src { color: #a78bfa; }
.claim-chip.prof .claim-chip__src { color: #4f8ef7; }
.claim-chip.tst  .claim-chip__src { color: #22c55e; }
.claim-chip.gov  .claim-chip__src { color: #f59e0b; }
.claim-chip.obs  .claim-chip__src { color: #94a3b8; }
.claim-chip__val { font-size: 12px; font-weight: 600; color: var(--primary-text-color); word-break: break-word; }
.dc-chip-footer { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-top: 1px; }
.claim-chip__badge {
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
.edit-btn {
    display: none;
    padding: 1px 5px;
    font-size: 10px;
    border-radius: 3px;
    border: 1px solid var(--border-color);
    color: var(--caption-text-color);
    cursor: pointer;
    align-items: center;
    gap: 2px;
    background: transparent;
}
.claim-chip:hover .edit-btn { display: inline-flex; }
.edit-btn:hover { color: var(--link-text-color); }

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
.tier-cell.has-claims { font-weight: 600; color: var(--primary-text-color); }
.tier-cell.no-claims  { color: var(--caption-text-color); }
.matrix-totals-row td { font-weight: 700; background: rgba(128,128,128,0.04); border-top: 2px solid var(--border-color); }
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

/* ── Claim counts bar ── */
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

/* ── Claims help panel ── */
.claims-help-panel {
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
.suite-chip--clickable:hover { filter: brightness(1.12); box-shadow: 0 1px 6px rgba(0,0,0,0.12); text-decoration: none; opacity: 1; }
.suite-chip__arrow { opacity: 0; transition: opacity 0.15s; margin-left: 2px; }
.suite-chip--clickable:hover .suite-chip__arrow { opacity: 0.7; }
.suite-scope-hint {
    font-size: 11px;
    color: var(--caption-text-color);
    font-style: italic;
    flex-basis: 100%;
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

/* ── Claim chip — clickable indicator ── */
.claim-chip--clickable { cursor: pointer; }
.claim-chip--clickable:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
`);

export { DataContract };
