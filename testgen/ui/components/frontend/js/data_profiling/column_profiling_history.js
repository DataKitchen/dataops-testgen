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
import { Card } from '../components/card.js';

const { div, span } = van.tags;

const ColumnProfilingHistory = (/** @type Properties */ props) => {
    loadStylesheet('column-profiling-history', stylesheet);
    Streamlit.setFrameHeight(600);
    window.testgen.isPage = true;

    const selectedRunId = van.state(null);

    return div(
        { class: 'column-history flex-row fx-align-stretch' },
        () => div(
            { class: 'column-history--list' },
            getValue(props.profiling_runs).map(({ run_id, run_date }, index) => div(
                { 
                    class: () => `column-history--item clickable ${selectedRunId.val === run_id ? 'selected' : ''}`,
                    onclick: () => {
                        selectedRunId.val = run_id;
                        emitEvent('RunSelected', { payload: run_id });
                    },
                },
                div(formatTimestamp(run_date)),
                index === 0 ? span({ class: 'text-caption' }, 'Latest run') : null,
            )),
        ),
        span({class: 'column-history--divider'}),
        () => getValue(props.selected_item)
            ? div(
                { class: 'column-history--details' },
                ColumnDistributionCard({}, getValue(props.selected_item)),
            )
            : Card({
                class: 'column-history--empty',
                content: 'No data available for column in selected profiling run.',
            }),
    );
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.column-history {
    height: 100%;
}

.column-history--list {
    flex: 250px 0 1;
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
    flex: auto;
}

.column-history--divider {
    width: 1px;
    background-color: var(--grey);
    margin: 0 10px;
}

.column-history--empty {
    flex-grow: 1;
    display: flex;
    flex-flow: row;
    justify-content: center;
    align-items: center;
}
`);

export { ColumnProfilingHistory };
