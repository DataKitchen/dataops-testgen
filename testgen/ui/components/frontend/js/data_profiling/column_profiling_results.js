/**
 * @import { Column } from './data_profiling_utils.js';
 * 
 * @typedef Properties
 * @type {object}
 * @property {Column} column
 * @property {boolean?} data_preview
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { getValue, resizeFrameHeightToElement, resizeFrameHeightOnDOMChange, loadStylesheet } from '../utils.js';
import { ColumnDistributionCard } from './column_distribution.js';
import { DataCharacteristicsCard } from './data_characteristics.js';
import { LatestProfilingTime } from './data_profiling_utils.js';
import { HygieneIssuesCard, PotentialPIICard } from './data_issues.js';

const { div, h2, span } = van.tags;

const ColumnProfilingResults = (/** @type Properties */ props) => {
    loadStylesheet('column-profiling-results', stylesheet);
    Streamlit.setFrameHeight(1); // Non-zero value is needed to render
    window.testgen.isPage = true;

    const column = van.derive(() => {
        try {
            return JSON.parse(getValue(props.column));
        } catch (e) {
            console.error(e)
            return null;
        }
    });

    const domId = 'column-profiling-results';
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId },
        () => div(
            div(
                { class: 'mb-2' },
                h2(
                    { class: 'tg-column-profiling--title' },
                    span(
                        { class: 'text-secondary' },
                        `${column.val.table_name} > `,
                    ),
                    column.val.column_name,
                ),
                column.val.is_latest_profile ? LatestProfilingTime({}, column.val) : null,
            ),
            DataCharacteristicsCard({ border: true }, column.val),
            ColumnDistributionCard({ border: true, dataPreview: !!props.data_preview?.val }, column.val),
            column.val.hygiene_issues ? [
                PotentialPIICard({ border: true }, column.val),
                HygieneIssuesCard({ border: true }, column.val),
            ] : null,
        ),
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
