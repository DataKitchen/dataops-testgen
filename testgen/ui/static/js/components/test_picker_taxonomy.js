// Faceted Add-Test picker taxonomy: colors, axis definitions, and the column-aware pre-filter.
// All seven facets read a column on test_types (no derivation here): `impact_dimension`,
// `dq_dimension`, `health_dimension`, `algorithm`, `statistical_technique`, `test_scope`, and
// `criteria`. `criteria` is derived once in Python (derive_test_criteria) and shared by UI + MCP,
// so this file holds presentation only. Colors reference the --facet-* CSS variables defined in
// shared.css, which carry light values plus higher-contrast dark-mode overrides.

const IMPACT_COLOR = {
    'Conformance': 'var(--facet-crimson)', 'Reliability': 'var(--facet-blue)', 'Regularity': 'var(--facet-amber)', 'Usability': 'var(--facet-purple)',
};

const QD_COLOR = {
    'Validity': 'var(--facet-crimson)', 'Completeness': 'var(--facet-blue)', 'Consistency': 'var(--facet-rust)', 'Accuracy': 'var(--facet-teal)',
    'Timeliness': 'var(--facet-amber)', 'Uniqueness': 'var(--facet-purple)', 'Recency': 'var(--facet-bronze)',
};

const HD_COLOR = {
    'Schema Drift': 'var(--facet-indigo)', 'Data Drift': 'var(--facet-orange)', 'Volume': 'var(--facet-teal)', 'Freshness': 'var(--facet-amber)',
};

const ALGO_COLOR = {
    'Boundary check': 'var(--facet-rust)',
    'Counting': 'var(--facet-blue)',
    'Pattern / regex': 'var(--facet-crimson)',
    'Set / lookup': 'var(--facet-purple)',
    'Statistical drift': 'var(--facet-orange)',
    'Aggregate reconciliation': 'var(--facet-bronze)',
    'Freshness / time': 'var(--facet-amber)',
    'Schema / metadata': 'var(--facet-indigo)',
    'Custom SQL': 'var(--facet-teal)',
};

const TECH_COLOR = {
    "Cohen's D": 'var(--facet-blue)',
    "Cohen's H": 'var(--facet-purple)',
    'Outlier Detection': 'var(--facet-orange)',
    'SD Shift': 'var(--facet-rust)',
    'Jensen-Shannon Divergence': 'var(--facet-teal)',
};

// Canonical order for the sparse Statistical Technique facet.
const TECHNIQUE_ORDER = ["Cohen's D", "Cohen's H", 'Outlier Detection', 'SD Shift', 'Jensen-Shannon Divergence'];

const CRITERIA_COLOR = {
    'Defined Rule': 'var(--facet-teal)', 'Defined Threshold': 'var(--facet-blue)', 'Defined Value': 'var(--facet-emerald)',
    'List of Values': 'var(--facet-purple)', 'Reference Dataset': 'var(--facet-bronze)', 'Custom Criteria': 'var(--facet-crimson)',
};
// Canonical order for the Criteria facet (least to most setup effort).
const CRITERIA_ORDER = [
    'Defined Rule', 'Defined Threshold', 'Defined Value',
    'List of Values', 'Reference Dataset', 'Custom Criteria',
];

const SCOPE_LABEL = {
    column: 'Column', table: 'Table', referential: 'Referential', custom: 'Custom', tablegroup: 'Table Group',
};
const SCOPE_ORDER = ['Column', 'Table', 'Referential', 'Custom', 'Table Group'];

const FALLBACK = 'var(--facet-grey)';
const EMPTY = '—';

const NUMERIC_ONLY = ['Min_Val', 'Avg_Shift', 'Incr_Avg_Shift', 'Variability_Increase', 'Variability_Decrease',
    'Outlier_Pct_Above', 'Outlier_Pct_Below', 'Dec_Trunc', 'Distribution_Shift', 'Aggregate_Minimum'];
const DATE_ONLY = ['Min_Date', 'Future_Date', 'Future_Date_1Y', 'Recency', 'Distinct_Date_Ct',
    'Daily_Record_Ct', 'Weekly_Rec_Ct', 'Monthly_Rec_Ct', 'Valid_Month', 'Freshness_Trend', 'Table_Freshness'];

function appliesToSelectedColumn(t, generalType) {
    if (['table', 'tablegroup', 'referential'].includes(t.test_scope)) return false;
    // Unknown column type (null/undefined/empty): we can't assert a test is inapplicable, so
    // don't hide it. Without this, an absent general_type fails every type check below and
    // silently hides all numeric/date tests. Known non-numeric/non-date codes ('A','B','X')
    // are truthy and still filter correctly.
    if (!generalType) return true;
    if (NUMERIC_ONLY.includes(t.test_type) && generalType !== 'N') return false;
    const isDate = generalType === 'D' || generalType === 'T';
    if (DATE_ONLY.includes(t.test_type) && !isDate) return false;
    return true;
}

// ── Axis registry ─────────────────────────────────────────────────────────────
// `value(t)` returns the facet value for a test (or null when absent). `color(key)` returns a
// hex color. `sparse` axes filter out null-valued tests when active. `order`, when present,
// fixes the facet's display order.

const AXES = {
    impact: { label: 'Impact Dimension', value: (t) => t.impact_dimension || null, color: (k) => IMPACT_COLOR[k] || FALLBACK },
    dq: { label: 'Quality Dimension', value: (t) => t.dq_dimension || null, color: (k) => QD_COLOR[k] || FALLBACK },
    health: { label: 'Health Dimension', value: (t) => t.health_dimension || null, color: (k) => HD_COLOR[k] || FALLBACK },
    algorithm: { label: 'Algorithm', value: (t) => t.algorithm || null, color: (k) => ALGO_COLOR[k] || FALLBACK },
    technique: { label: 'Statistical Technique', value: (t) => t.statistical_technique || null, color: (k) => TECH_COLOR[k] || FALLBACK, sparse: true, order: TECHNIQUE_ORDER },
    scope: { label: 'Test Scope', value: (t) => SCOPE_LABEL[t.test_scope] || 'Other', color: () => FALLBACK, order: SCOPE_ORDER },
    criteria: { label: 'Criteria', value: (t) => t.criteria || null, color: (k) => CRITERIA_COLOR[k] || FALLBACK, order: CRITERIA_ORDER },
};

// Facet order in the rail (PRD facet review). All facets are always visible.
const FACET_AXES = ['impact', 'dq', 'health', 'algorithm', 'technique', 'scope', 'criteria'];
// Group-by options offered in the result-list dropdown.
const GROUP_BY_AXES = ['impact', 'dq', 'health', 'algorithm', 'technique', 'scope', 'criteria'];

export {
    AXES, FACET_AXES, GROUP_BY_AXES, TECHNIQUE_ORDER, CRITERIA_ORDER, SCOPE_LABEL, EMPTY,
    appliesToSelectedColumn,
};
