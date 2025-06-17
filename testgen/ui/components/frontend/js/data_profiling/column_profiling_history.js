/**
 * @import { Column } from './data_profiling_utils.js';
 * 
 * @typedef ProfilingRun
 * @type {object}
 * @property {string} run_id
 * @property {number} run_date
 * 
 * @typedef Properties
 * @type {object}
 * @property {ProfilingRun} profiling_runs
 * @property {Column} selected_item
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { ColumnDistributionCard } from './column_distribution.js';

const { div, span } = van.tags;

const ColumnProfilingHistory = (/** @type Properties */ props) => {
    loadStylesheet('column-profiling-history', stylesheet);
    Streamlit.setFrameHeight(600);
    window.testgen.isPage = true;

    return div(
        { class: 'column-history flex-row fx-align-stretch' },
        () => div(
            { class: 'column-history--list' },
            getValue(props.profiling_runs).map(({ run_id, run_date }, index) => div(
                { 
                    class: () => `column-history--item clickable ${getValue(props.selected_item).profile_run_id === run_id ? 'selected' : ''}`,
                    onclick: () => emitEvent('RunSelected', { payload: run_id }),
                },
                div(formatTimestamp(run_date)),
                index === 0 ? span({ class: 'text-caption' }, 'Latest run') : null,
            )),
        ),
        span({class: 'column-history--divider'}),
        () => div(
            { class: 'column-history--details' },
            ColumnDistributionCard({}, getValue(props.selected_item)),
        ),
    );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.column-history {
    height: 100%;
}

.column-history--list {
    flex: 150px 1 1;
}

.column-history--item {
    padding: 8px;
}

.column-history--item:hover {
    background-color: var(--sidebar-item-hover-color);
}

.column-history--item.selected {
    background-color: #06a04a17;
}

.column-history--item.selected > div {
    font-weight: 500;
}

.column-history--details {
    overflow: auto;
}

.column-history--divider {
    width: 1px;
    background-color: var(--grey);
    margin: 0 10px;
}
`);

export { ColumnProfilingHistory };
