/**
 * @typedef TableGroupStats
 * @type {object}
 * @property {string} id
 * @property {string} table_groups_name
 * @property {string} table_group_schema
 * @property {number} table_ct
 * @property {number} column_ct
 * @property {number} approx_record_ct
 * @property {number?} record_ct
 * @property {number} approx_data_point_ct
 * @property {number?} data_point_ct
 * 
 * @typedef Properties
 * @type {object}
 * @property {boolean?} hideApproxCaption
 * @property {boolean?} hideWarning
 * @property {string?} class
 */
import van from '../van.min.js';
import { formatNumber } from '../display_utils.js';
import { Alert } from '../components/alert.js';

const { div, span, strong } = van.tags;
const profilingWarningText = 'Profiling on large datasets could be time-consuming or resource-intensive, depending on your database configuration.';

/**
 * @param {Properties} props
 * @param {TableGroupStats} stats
 * @returns {HTMLElement}
 */
const TableGroupStats = (props, stats) => {
    const useApprox = stats.record_ct === null || stats.record_ct === undefined;
    const rowCount = useApprox ? stats.approx_record_ct : stats.record_ct;
    const dataPointCount = useApprox ? stats.approx_data_point_ct : stats.data_point_ct;
    const warning = !props.hideWarning ? WarningText(rowCount, dataPointCount) : null;

    return div(
        { class: `flex-column fx-gap-1 p-3 border border-radius-2 ${props.class ?? ''}` },
        span(
            span({ class: 'text-secondary' }, 'Schema: '),
            stats.table_group_schema,
        ),
        div(
            { class: 'flex-row' },
            div(
                { class: 'flex-column fx-gap-1', style: 'flex: 1 1 50%;' },
                span(
                    span({ class: 'text-secondary' }, 'Tables: '),
                    formatNumber(stats.table_ct),
                ),
                span(
                    span({ class: 'text-secondary' }, 'Columns: '),
                    formatNumber(stats.column_ct),
                ),
            ),
            div(
                { class: 'flex-column fx-gap-1', style: 'flex: 1 1 50%;' },
                span(
                    span({ class: 'text-secondary' }, 'Rows: '),
                    formatNumber(rowCount),
                    useApprox ? ' *' : '',
                ),
                span(
                    span({ class: 'text-secondary' }, 'Data points: '),
                    formatNumber(dataPointCount),
                    useApprox ? ' *' : '',
                ),
            ),
        ),
        useApprox && !props.hideApproxCaption
            ? span(
                { class: 'text-caption text-right mt-1' },
                '* Approximate counts based on server statistics',
            )
            : null,
        warning
            ? Alert({ type: 'warn', icon: 'warning', class: 'mt-2' }, warning)
            : null,
    );
};

/**
 * @param {number | null} rowCount
 * @param {number | null} dataPointCount
 * @returns {HTMLElement | null}
 */
const WarningText = (rowCount, dataPointCount) => {
    if (rowCount === null) { // Unknown counts
        return div(`WARNING: ${profilingWarningText}`);
    }

    const rowTier = getStatTier(rowCount);
    const dataPointTier = getStatTier(dataPointCount);

    if (rowTier || dataPointTier) {
        let category;
        if (rowTier && dataPointTier) {
            category = rowTier === dataPointTier
                ? [ strong(rowTier), ' of rows and data points' ]
                : [ strong(rowTier), ' of rows and ', strong(dataPointTier), ' of data points' ];
        } else {
            category = rowTier
                ? [ strong(rowTier), ' of rows' ]
                : [ strong(dataPointTier), ' of data points' ];
        }
        return div(
            div('WARNING: The table group has ', ...category, '.'),
            div({ class: 'mt-2' }, profilingWarningText),
        );
    }
    return null;
}

/**
 * @param {number | null} count
 * @returns {string | null}
 */
function getStatTier(/** @type number */ count) {
    if (count > 1000000000) {
        return 'billions';
    } else if (count > 1000000) {
        return 'millions';
    } else if (count > 100000) {
        return 'hundreds of thousands';
    }
    return null;
};

export { TableGroupStats };
