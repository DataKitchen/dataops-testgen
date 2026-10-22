/**
 * @typedef VersionOption
 * @type {object}
 * @property {number} value
 * @property {string} label
 *
 * @typedef Verification
 * @type {object}
 * @property {string} version
 * @property {string} run_id
 * @property {number?} started_at
 * @property {number} passed_ct
 * @property {number} warning_ct
 * @property {number} failed_ct
 * @property {number} error_ct
 * @property {number} log_ct
 * @property {number} dismissed_ct
 *
 * @typedef Summary
 * @type {object}
 * @property {VersionOption[]} versions
 * @property {number} selected_version
 * @property {string} state
 * @property {string?} caption
 * @property {{label: string, version: number}?} caption_link
 * @property {Verification?} verification
 * @property {string?} verification_message
 * @property {number?} draft_version
 * @property {{history: boolean, export: boolean, import: boolean, discard: boolean, freeze: boolean}} actions
 *
 * @typedef Properties
 * @type {object}
 * @property {Summary} summary
 * @property {string} project_code
 * @property {Function} emit
 * @property {((version: number) => void)} onVersionChange
 * @property {(() => void)?} onHistory
 * @property {(() => void)?} onExport
 * @property {(() => void)?} onImport
 * @property {(() => void)?} onDiscard
 * @property {(() => void)?} onFreeze
 */
import van from '../van.min.js';
import { getValue } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { Button } from './button.js';
import { Caption } from './caption.js';
import { Link } from './link.js';
import { Select } from './select.js';
import { SummaryBar } from './summary_bar.js';

const { div, span } = van.tags;

const ACTION_STYLE = 'background-color: var(--button-generic-background-color);';

const ContractSummary = (/** @type Properties */ props) => {
    return () => {
        const summary = getValue(props.summary);
        if (!summary) {
            return div();
        }
        const { actions } = summary;

        return div(
            { class: 'flex-row fx-gap-4 fx-align-flex-start fx-flex-wrap mb-3', 'data-testid': 'contract-summary' },
            Select({
                label: 'Version',
                value: summary.selected_version,
                options: summary.versions,
                style: 'min-width: 160px',
                onChange: (value) => props.onVersionChange(value),
            }),
            div(
                { class: 'flex-column', style: 'min-width: 220px; max-width: 280px;' },
                Caption({ content: 'Contract', style: 'margin-bottom: 2px;' }),
                span({ class: 'text-large', 'data-testid': 'contract-state' }, summary.state),
                summary.caption
                    ? span(
                        { class: 'text-caption mt-1', 'data-testid': 'contract-caption' },
                        summary.caption,
                        summary.caption_link
                            ? [' ', Link({
                                href: '',
                                label: summary.caption_link.label,
                                right_icon: 'chevron_right',
                                right_icon_size: 14,
                                style: 'display: inline-flex; font-size: inherit; vertical-align: bottom;',
                                onClick: (event) => {
                                    event.preventDefault();
                                    props.onVersionChange(summary.caption_link.version);
                                },
                            })]
                            : '',
                    )
                    : '',
            ),
            div(
                { class: 'flex-column fx-flex', style: 'min-width: 200px;' },
                Caption({ content: 'Latest Verification', style: 'margin-bottom: 2px;' }),
                summary.verification
                    ? LatestVerification(summary.verification, props)
                    : span({ class: 'text-secondary', 'data-testid': 'contract-verification-message' }, summary.verification_message),
            ),
            div(
                { class: 'flex-column fx-gap-2 fx-align-flex-end', style: 'margin-left: auto;' },
                div(
                    { class: 'flex-row fx-gap-2 fx-justify-flex-end fx-flex-wrap' },
                    actions.history
                        ? Button({ type: 'stroked', icon: 'history', label: 'History', width: 'auto', style: ACTION_STYLE, onclick: props.onHistory })
                        : '',
                    actions.export
                        ? Button({ type: 'stroked', icon: 'download', label: 'Export Contract', width: 'auto', style: ACTION_STYLE, onclick: props.onExport })
                        : '',
                    actions.import
                        ? Button({ type: 'stroked', icon: 'upload', label: 'Import Contract', width: 'auto', style: ACTION_STYLE, onclick: props.onImport })
                        : '',
                ),
                actions.discard || actions.freeze
                    ? div(
                        { class: 'flex-row fx-gap-2 fx-justify-flex-end fx-flex-wrap' },
                        actions.discard
                            ? Button({ type: 'stroked', color: 'warn', icon: 'close', label: 'Discard Draft', width: 'auto', onclick: props.onDiscard })
                            : '',
                        actions.freeze
                            ? Button({
                                type: 'stroked',
                                color: 'primary',
                                icon: 'ac_unit',
                                label: `Freeze Version ${summary.draft_version}`,
                                width: 'auto',
                                onclick: props.onFreeze,
                            })
                            : '',
                    )
                    : '',
            ),
        );
    };
};

const LatestVerification = (/** @type Verification */ verification, /** @type Properties */ props) => {
    const items = [
        { label: 'Passed', value: verification.passed_ct ?? 0, color: 'green' },
        { label: 'Warning', value: verification.warning_ct ?? 0, color: 'yellow' },
        { label: 'Failed', value: verification.failed_ct ?? 0, color: 'red' },
        { label: 'Error', value: verification.error_ct ?? 0, color: 'brown' },
        { label: 'Log', value: verification.log_ct ?? 0, color: 'blue' },
        { label: 'Dismissed', value: verification.dismissed_ct ?? 0, color: 'grey' },
    ];
    return div(
        { class: 'flex-column', 'data-testid': 'contract-verification' },
        div(
            { class: 'flex-row fx-gap-1 mb-1' },
            span(`${verification.version} ·`),
            Link({
                emit: props.emit,
                href: 'test-runs:results',
                params: { run_id: verification.run_id, project_code: getValue(props.project_code) },
                label: verification.started_at ? formatTimestamp(verification.started_at) : '--',
            }),
        ),
        items.some((item) => item.value)
            ? SummaryBar({ items, height: 20, width: 350 })
            : span('--'),
    );
};

export { ContractSummary };
