/**
 * @typedef MonitorSummary
 * @type {object}
 * @property {number} freshness_anomalies
 * @property {number} volume_anomalies
 * @property {number} schema_anomalies
 * @property {number} metric_anomalies
 * @property {boolean?} freshness_has_errors
 * @property {boolean?} volume_has_errors
 * @property {boolean?} schema_has_errors
 * @property {boolean?} metric_has_errors
 * @property {boolean?} freshness_is_training
 * @property {boolean?} volume_is_training
 * @property {boolean?} metric_is_training
 * @property {boolean?} freshness_is_pending
 * @property {boolean?} volume_is_pending
 * @property {boolean?} schema_is_pending
 * @property {boolean?} metric_is_pending
 * @property {number} lookback
 * @property {number} lookback_start
 * @property {number} lookback_end
 * @property {string?} project_code
 * @property {string?} table_group_id
 *
 * @typedef SummaryOptions
 * @type {object}
 * @property {function(string)?} onTagClick
 * @property {object?} activeTypes
 */
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { formatDuration, humanReadableDuration } from '../display_utils.js';
import { withTooltip } from './tooltip.js';
import van from '../van.min.js';

const { a, div, i, span } = van.tags;

/**
 * @param {MonitorSummary} summary
 * @param {string?} label
 * @param {SummaryOptions?} options
 */
const AnomaliesSummary = (summary, label = 'Anomalies', options = {}) => {
    loadStylesheet('anomalies-summary', summaryStylesheet);

    if (!summary.lookback) {
        return span({class: 'text-secondary mt-3 mb-2'}, 'No monitor runs yet');
    }

    const SummaryTag = (typeKey, tagLabel, value, hasErrors, isTraining, isPending) => {
        const isClickable = !!options.onTagClick;
        const isActive = van.derive(() => (getValue(options.activeTypes) ?? []).includes(typeKey));

        return div(
            {
                class: () => `flex-row fx-gap-1 p-1 border-radius-1 summary-tag ${isClickable ? 'clickable' : ''} ${isActive.val ? 'active' : ''}`,
                onclick: isClickable ? (event) => {
                    event.stopPropagation();
                    options.onTagClick(typeKey);
                } : undefined,
            },
            div(
                {class: `flex-row fx-justify-center anomaly-tag ${value > 0 ? 'has-anomalies' : hasErrors ? 'has-errors' : isTraining ? 'is-training' : isPending ? 'is-pending' : ''}`},
                value > 0
                    ? value
                    : hasErrors
                        ? withTooltip(
                            i({class: 'material-symbols-rounded'}, 'warning'),
                            {text: 'Execution error', position: 'top-right'},
                        )
                        : isTraining
                            ? withTooltip(
                                i({class: 'material-symbols-rounded'}, 'more_horiz'),
                                {text: 'Training model', position: 'top-right'},
                            )
                            : isPending
                                ? withTooltip(
                                    span({class: 'pl-2 pr-2', style: 'position: relative;'}, '-'),
                                    {text: 'No results yet or not configured'},
                                )
                                : i({class: 'material-symbols-rounded'}, 'check'),
            ),
            span({}, tagLabel),
        );
    };

    const numRuns = summary.lookback === 1 ? 'run' : `${summary.lookback} runs`;
    const duration = humanReadableDuration(formatDuration(summary.lookback_start, new Date()), true)
    const labelElement = span({class: 'text-small text-secondary'}, `${label} in last ${numRuns} (${duration})`);

    const contentElement = div(
        {class: 'flex-row fx-gap-5'},
        SummaryTag('freshness', 'Freshness', summary.freshness_anomalies, summary.freshness_has_errors, summary.freshness_is_training, summary.freshness_is_pending),
        SummaryTag('volume', 'Volume', summary.volume_anomalies, summary.volume_has_errors, summary.volume_is_training, summary.volume_is_pending),
        SummaryTag('schema', 'Schema', summary.schema_anomalies, summary.schema_has_errors, false, summary.schema_is_pending),
        SummaryTag('metrics', 'Metrics', summary.metric_anomalies, summary.metric_has_errors, summary.metric_is_training, summary.metric_is_pending),
    );

    if (summary.project_code && summary.table_group_id) {
        return a(
            {
                class: `flex-column fx-gap-2 clickable`,
                style: 'text-decoration: none; color: unset;',
                href: summary.table_group_id ? `/monitors?project_code=${summary.project_code}&table_group_id=${summary.table_group_id}`: null,
                onclick: summary.table_group_id ? (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    emitEvent('LinkClicked', { href: 'monitors', params: {project_code: summary.project_code, table_group_id: summary.table_group_id} });
                }: null,
            },
            labelElement,
            contentElement,
        );
    }

    return div({class: 'flex-column fx-gap-2'}, labelElement, contentElement);
};

const summaryStylesheet = new CSSStyleSheet();
summaryStylesheet.replace(`
.summary-tag.clickable:hover,
.summary-tag.active {
    background: var(--select-hover-background);
}
`);

export { AnomaliesSummary };
