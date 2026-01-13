/**
 * @typedef MonitorSummary
 * @type {object}
 * @property {number} freshness_anomalies
 * @property {number} volume_anomalies
 * @property {number} schema_anomalies
 * @property {number} quality_drift_anomalies
 * @property {number} lookback
 * @property {string?} project_code
 * @property {string?} table_group_id
 */
import { emitEvent } from '../utils.js';
import van from '../van.min.js';

const { a, div, i, span } = van.tags;

/**`
 * @param {MonitorSummary} summary 
 * @param {any?} topLabel
 */
const AnomaliesSummary = (summary, topLabel) => {
    const SummaryTag = (label, value) => div(
        {class: 'flex-row fx-gap-1'},
        div(
            {class: `flex-row fx-justify-center anomali-tag ${value > 0 ? 'has-anomalies' : ''}`},
            value > 0
                ? value
                : i({class: 'material-symbols-rounded'}, 'check'),
        ),
        span({}, label),
    );

    let label = `Total anomalies in last ${summary.lookback} runs`;
    if (summary.lookback === 1) {
        label = `Anomalies in last run`;
    }

    const labelElement = (topLabel && typeof topLabel !== 'string')
        ? topLabel
        : span({class: 'text-small text-secondary'}, topLabel || label);
    const contentElement = div(
        {class: 'flex-row fx-gap-5'},
        SummaryTag('Freshness', summary.freshness_anomalies),
        // SummaryTag('Volume', summary.volume_anomalies),
        SummaryTag('Schema', summary.schema_anomalies),
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
