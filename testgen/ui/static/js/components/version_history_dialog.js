/**
 * @typedef VersionRuns
 * @type {object}
 * @property {number} count
 * @property {string?} latest_run_id
 * @property {number?} latest_started_at
 * @property {string?} latest_status
 *
 * @typedef VersionDetail
 * @type {object}
 * @property {string} title
 * @property {string} state
 * @property {number} terms
 * @property {VersionRuns} runs
 * @property {string?} label
 * @property {string?} frozen_by
 * @property {number?} frozen_at
 * @property {boolean} frozen
 * @property {{source: number, target: number}?} comparison - the pair its Compare opens on
 *
 * @typedef HistoryVersion
 * @type {object}
 * @property {number} version
 * @property {string} state
 * @property {string} caption
 * @property {VersionDetail} detail
 *
 * @typedef Comparison
 * @type {object}
 * @property {number} source
 * @property {number} target
 * @property {string?} source_label
 * @property {string?} target_label
 * @property {string?} source_document
 * @property {string?} target_document
 * @property {string?} error
 *
 * @typedef HistoryData
 * @type {object}
 * @property {string} contract
 * @property {string} project_code
 * @property {HistoryVersion[]} versions
 * @property {{value: number, label: string}[]} options
 * @property {string?} compare_disabled_reason
 * @property {{source: number, target: number}?} open_comparison - opens the dialog on this comparison
 * @property {Comparison?} comparison
 *
 * @typedef Properties
 * @type {object}
 * @property {HistoryData?} data - reactive: set to open the dialog, null to close it
 * @property {Function} emit
 * @property {((source: number, target: number) => void)} onCompare
 * @property {(() => void)?} onClose
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { Alert } from './alert.js';
import { Attribute } from './attribute.js';
import { Button } from './button.js';
import { CodeDiff } from './code_diff.js';
import { Dialog } from './dialog.js';
import { Link } from './link.js';
import { Select } from './select.js';
import { Spinner } from './spinner.js';

const { div, span } = van.tags;

const VersionHistoryDialog = (/** @type Properties */ props) => {
    loadStylesheet('version-history-dialog', stylesheet);
    const open = van.state(false);
    const data = van.state(null);
    const selected = van.state(null);
    const pair = van.state(null);

    van.derive(() => {
        const raw = getValue(props.data) ?? null;
        const opening = !!raw && !open.rawVal;
        data.val = raw;
        open.val = !!raw;
        if (opening) {
            selected.val = raw.versions[0]?.version ?? null;
            pair.val = raw.open_comparison ?? null;
            if (pair.rawVal) {
                props.onCompare(pair.rawVal.source, pair.rawVal.target);
            }
        }
    });

    const title = van.derive(() => data.val ? `Version History: ${data.val.contract}` : 'Version History');

    const onClose = () => {
        open.val = false;
        pair.val = null;
        props.onClose?.();
    };

    const compare = (source, target) => {
        pair.val = { source, target };
        props.onCompare(source, target);
    };

    return Dialog(
        { title, open, onClose, width: '72rem' },
        () => {
            if (!open.val) {
                return '';
            }
            return pair.val ? ComparisonView(props, data, pair, compare) : ListView(props, data, selected, compare);
        },
    );
};

const ListView = (props, data, selected, compare) => {
    const d = data.rawVal;
    return div(
        { class: 'tg-version-history flex-row fx-align-stretch', 'data-testid': 'version-history' },
        div(
            { class: 'tg-version-history--list' },
            d.versions.map((item) => div(
                {
                    class: () => `tg-version-history--item clickable ${selected.val === item.version ? 'selected' : ''}`,
                    'data-testid': 'version-history-item',
                    onclick: () => selected.val = item.version,
                },
                div(`v${item.version}`),
                span({ class: 'text-caption' }, item.caption),
            )),
        ),
        span({ class: 'tg-version-history--divider' }),
        () => {
            const item = d.versions.find((v) => v.version === selected.val);
            return item
                ? VersionDetail(props, item.detail, d, compare)
                : div();
        },
    );
};

const VersionDetail = (props, detail, d, compare) => {
    const comparison = detail.comparison;
    return div(
        { class: 'tg-version-history--detail flex-column fx-gap-3', 'data-testid': 'version-history-detail' },
        span({ class: 'text-large' }, detail.title),
        Attribute({ label: 'State', value: detail.state }),
        Attribute({ label: 'Terms', value: detail.terms }),
        div(
            { class: 'flex-column fx-gap-1' },
            span({ class: 'text-caption' }, 'Runs'),
            RunsValue(props, detail.runs, d.project_code),
        ),
        detail.frozen ? Attribute({ label: 'Label', value: detail.label ?? '--' }) : '',
        detail.frozen ? Attribute({ label: 'Frozen By', value: detail.frozen_by ?? '--' }) : '',
        detail.frozen ? Attribute({ label: 'Frozen At', value: formatTimestamp(detail.frozen_at) }) : '',
        div(
            { class: 'flex-row fx-justify-flex-end mt-2' },
            Button({
                type: 'stroked',
                icon: 'compare_arrows',
                label: 'Compare',
                width: 'auto',
                disabled: !comparison,
                tooltip: d.compare_disabled_reason ?? null,
                tooltipPosition: 'left',
                onclick: () => comparison && compare(comparison.source, comparison.target),
            }),
        ),
    );
};

const RunsValue = (props, runs, projectCode) => {
    if (!runs.count) {
        return span('None');
    }
    return div(
        { class: 'flex-row fx-gap-1 fx-flex-wrap' },
        span(`${runs.count} · latest`),
        runs.latest_run_id
            ? Link({
                emit: props.emit,
                href: 'test-runs:results',
                params: { run_id: runs.latest_run_id, project_code: projectCode },
                label: runs.latest_started_at ? formatTimestamp(runs.latest_started_at) : '--',
            })
            : span('--'),
        runs.latest_status ? span(`· ${runs.latest_status}`) : '',
    );
};

const ComparisonView = (props, data, pair, compare) => {
    const d = data.rawVal;
    const current = pair.rawVal;
    return div(
        { class: 'flex-column fx-gap-3', 'data-testid': 'version-comparison' },
        div(
            { class: 'flex-row fx-gap-3 fx-align-flex-end' },
            Button({
                type: 'stroked',
                icon: 'arrow_back',
                label: 'Back',
                width: 'auto',
                onclick: () => pair.val = null,
            }),
            span({ class: 'mb-2' }, 'Compare'),
            Select({
                label: '',
                value: current.source,
                options: d.options,
                style: 'min-width: 160px',
                onChange: (value) => value !== current.source && compare(value, current.target),
            }),
            span({ class: 'mb-2' }, 'with'),
            Select({
                label: '',
                value: current.target,
                options: d.options,
                style: 'min-width: 160px',
                onChange: (value) => value !== current.target && compare(current.source, value),
            }),
        ),
        () => {
            const comparison = data.val?.comparison;
            const ready = comparison && comparison.source === current.source && comparison.target === current.target;
            if (!ready) {
                return div({ class: 'flex-row fx-justify-center p-4' }, Spinner({}));
            }
            if (comparison.error) {
                return Alert({ type: 'error', icon: 'error' }, span(comparison.error));
            }
            return CodeDiff({
                source: comparison.source_document,
                target: comparison.target_document,
                sourceLabel: comparison.source_label,
                targetLabel: comparison.target_label,
                language: 'yaml',
                height: 520,
            });
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-version-history {
    min-height: 320px;
}

.tg-version-history--list {
    flex: 220px 0 0;
    max-height: 520px;
    overflow-y: auto;
}

.tg-version-history--item {
    padding: 8px;
    border-radius: 4px;
}

.tg-version-history--item:hover {
    background-color: var(--sidebar-item-hover-color);
}

.tg-version-history--item.selected {
    background-color: var(--selected-item-background);
}

.tg-version-history--item.selected > div {
    font-weight: 500;
}

.tg-version-history--divider {
    width: 1px;
    background-color: var(--border-color);
    margin: 0 16px;
}

.tg-version-history--detail {
    flex: auto;
}
`);

export { VersionHistoryDialog };
