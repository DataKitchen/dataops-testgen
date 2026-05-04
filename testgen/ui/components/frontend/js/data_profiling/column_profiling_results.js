/**
 * @import { Column } from './data_profiling_utils.js';
 * 
 * @typedef Properties
 * @type {object}
 * @property {Column} column
 * @property {boolean?} data_preview
 */
import van from '/app/static/js/van.min.js';
import { getValue, loadStylesheet } from '/app/static/js/utils.js';
import { ColumnDistributionCard } from './column_distribution.js';
import { DataCharacteristicsCard } from './data_characteristics.js';
import { LatestProfilingTime } from './data_profiling_utils.js';
import { HygieneIssuesCard } from './data_issues.js';

const { div, h2, span } = van.tags;

const ColumnProfilingResults = (/** @type Properties */ props) => {
    const emit = props.emit;
    loadStylesheet('column-profiling-results', stylesheet);

    const column = van.derive(() => {
        try {
            return JSON.parse(getValue(props.column));
        } catch (e) {
            console.error(e)
            return null;
        }
    });

    return div(
        {},
        () => {
            if (!column.val) return '';
            return div(
                {class: 'flex-column fx-gap-2' },
                div(
                    {},
                    h2(
                        { class: 'tg-column-profiling--title' },
                        span(
                            { class: 'text-secondary' },
                            `${column.val.table_name} > `,
                        ),
                        column.val.column_name,
                    ),
                    column.val.is_latest_profile ? LatestProfilingTime({ emit,}, column.val) : null,
                ),
                DataCharacteristicsCard({ emit,  border: true }, column.val),
                ColumnDistributionCard({ emit,  border: true, dataPreview: !!props.data_preview?.val }, column.val),
                column.val.hygiene_issues ? HygieneIssuesCard({ emit,  border: true }, column.val) : null,
            );
        },
    );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-column-profiling--title {
    margin: 0;
    color: var(--primary-text-color);
    font-size: 18px;
    font-weight: 400;
}
`);

export { ColumnProfilingResults };
