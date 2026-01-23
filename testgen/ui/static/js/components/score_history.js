/**
 * @typedef ScoreHistoryEntry
 * @type {object}
 * @property {number} score
 * @property {('score'|'cde_score')} category
 * @property {string} time
 */
import van from '../van.min.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { colorMap } from '../display_utils.js';
import { LineChart } from './line_chart.js'; 

const { div, span, strong } = van.tags;

const TRANSLATIONS = {
    score: 'Total Score',
    cde_score: 'CDE Score',
};

/**
 * Render the scorecard history as line charts for the enabled scores.
 * 
 * @param {Object} props 
 * @param  {...ScoreHistoryEntry} entries
 * @returns {HTMLElment}
 */
const ScoreHistory = (props, ...entries) => {
    loadStylesheet('score-trend', stylesheet);

    const lineColors = {
        [TRANSLATIONS.score]: colorMap.teal,
        [TRANSLATIONS.cde_score]: colorMap.purpleLight,
        default: colorMap.grey,
    };

    return div(
        { ...props, class: `tg-score-trend flex-row ${props?.class ?? ''}`, 'data-testid': 'score-trend' },
        LineChart(
            {
                width: 600,
                height: 200,
                tooltipOffsetX: -100,
                tooltipOffsetY: 10,
                xMinSpanBetweenTicks: 3 * 24 * 60 * 60 * 1000,
                yMinSpanBetweenTicks: 5,
                getters: {
                    x: (/** @type {ScoreHistoryEntry} */ entry) => Date.parse(entry.time),
                    y: (/** @type {ScoreHistoryEntry} */ entry) => Number(entry.score),
                },
                formatters: {
                    x: (value) => new Intl.DateTimeFormat("en-US", {month: 'short', day: 'numeric'}).format(value),
                    y: (value) => String(Math.trunc(value)),
                },
                lineDiscriminator: (/** @type {ScoreHistoryEntry} */ entry) => TRANSLATIONS[entry.category],
                lineColor: (lineId) => lineColors[lineId] ?? lineColors.default,
                onShowPointTooltip: (point, _) => {
                    return div(
                        { class: 'flex-column fx-align-flex-start fx-justify-flex-start'},
                        strong(TRANSLATIONS[point.category]),
                        span(point.score),
                        span(Intl.DateTimeFormat("en-US", {dateStyle: 'long', timeStyle: 'long'}).format(Date.parse(point.time))),
                    );
                },
                onRefreshClicked: getValue(props.showRefresh) ? () => emitEvent('RecalculateHistory', { payload: getValue(props.score).id }) : undefined,
            },
            ...entries,
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-score-trend {
    width: fit-content;
    box-sizing: border-box;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin-bottom: unset !important;
    background-color: var(--dk-card-background);
}
`);

export { ScoreHistory };
