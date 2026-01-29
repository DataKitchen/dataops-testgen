/**
 * @typedef MonitorSummary
 * @type {object}
 * @property {number} freshness_anomalies
 * @property {number} volume_anomalies
 * @property {number} schema_anomalies
 * @property {number} quality_drift_anomalies
 * @property {boolean?} freshness_is_training
 * @property {boolean?} volume_is_training
 * @property {boolean?} freshness_is_pending
 * @property {boolean?} volume_is_pending
 * @property {boolean?} schema_is_pending
 * @property {number} lookback
 * @property {number} lookback_start
 * @property {number} lookback_end
 * @property {string?} project_code
 * @property {string?} table_group_id
 */
import { emitEvent } from '../utils.js';
import { formatDuration, humanReadableDuration } from '../display_utils.js';
import { withTooltip } from './tooltip.js';
import van from '../van.min.js';

const { a, div, i, span } = van.tags;

/**
 * @param {MonitorSummary} summary
 * @param {any?} topLabel
 */
const AnomaliesSummary = (summary, label = 'Anomalies') => {
    if (!summary.lookback) {
        return span({class: 'text-secondary mt-3 mb-2'}, 'No monitor runs yet');
    }

    const SummaryTag = (label, value, isTraining, isPending) => div(
        {class: 'flex-row fx-gap-1'},
        div(
            {class: `flex-row fx-justify-center anomaly-tag ${value > 0 ? 'has-anomalies' : isTraining ? 'is-training' : isPending ? 'is-pending' : ''}`},
            value > 0
                ? value
                : isTraining
                    ? withTooltip(
                        i({class: 'material-symbols-rounded'}, 'more_horiz'),
                        {text: 'Training model', position: 'top-right'},
                    )
                    : isPending
                        ? span({class: 'mr-2'}, '-')
                        : i({class: 'material-symbols-rounded'}, 'check'),
        ),
        span({}, label),
    );

    const numRuns = summary.lookback === 1 ? 'run' : `${summary.lookback} runs`;
    // TODO: Display lookback duration?
    // const duration = humanReadableDuration(formatDuration(summary.lookback_start, new Date()))
    const labelElement = span({class: 'text-small text-secondary'}, `${label} in last ${numRuns}`);

    const contentElement = div(
        {class: 'flex-row fx-gap-5'},
        SummaryTag('Freshness', summary.freshness_anomalies, summary.freshness_is_training, summary.freshness_is_pending),
        SummaryTag('Volume', summary.volume_anomalies, summary.volume_is_training, summary.volume_is_pending),
        SummaryTag('Schema', summary.schema_anomalies, false, summary.schema_is_pending),
        // SummaryTag('Quality Drift', summary.quality_drift_anomalies),
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

export { AnomaliesSummary };
