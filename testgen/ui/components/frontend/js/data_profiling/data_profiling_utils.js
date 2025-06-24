/**
 * @typedef HygieneIssue
 * @type {object}
 * @property {string} column_name
 * @property {string} anomaly_name
 * @property {'Definite' | 'Likely' | 'Possible' | 'Potential PII'} issue_likelihood
 * @property {string} detail
 * @property {'High' | 'Moderate'} pii_risk
 *
 * @typedef TestIssue
 * @type {object}
 * @property {string} id
 * @property {string} column_name
 * @property {string} test_name
 * @property {'Failed' | 'Warning' | 'Error' } result_status
 * @property {string} result_message
 * @property {string} test_suite
 * @property {string} test_run_id
 * @property {number} test_run_date
 * 
 * @typedef TestSuite
 * @type {object}
 * @property {string} id
 * @property {string} name
 * @property {string} test_count
 *
 * @typedef Column
 * @type {object}
 * @property {string} id
 * @property {'column'} type
 * @property {string} column_name
 * @property {string} table_name
 * @property {string} schema_name
 * @property {string} table_group_id
 * @property {string} connection_id
 * @property {string} project_code
 * * Characteristics
 * @property {'A' | 'B' | 'D' | 'N' | 'T' | 'X'} general_type
 * @property {string} column_type
 * @property {string} functional_data_type
 * @property {string} datatype_suggestion
 * @property {number?} add_date
 * @property {number?} last_mod_date
 * @property {number?} drop_date
 * * Column Tags
 * @property {string?} description
 * @property {boolean?} critical_data_element
 * @property {string?} data_source
 * @property {string?} source_system
 * @property {string?} source_process
 * @property {string?} business_domain
 * @property {string?} stakeholder_group
 * @property {string?} transform_level
 * @property {string?} aggregation_level
 * @property {string?} data_product
 * * Table Tags
 * @property {boolean?} table_critical_data_element
 * @property {string?} table_data_source
 * @property {string?} table_source_system
 * @property {string?} table_source_process
 * @property {string?} table_business_domain
 * @property {string?} table_stakeholder_group
 * @property {string?} table_transform_level
 * @property {string?} table_aggregation_level
 * @property {string?} table_data_product
 * * Table Group Tags
 * @property {string} table_group_data_source
 * @property {string} table_group_source_system
 * @property {string} table_group_source_process
 * @property {string} table_group_business_domain
 * @property {string} table_group_stakeholder_group
 * @property {string} table_group_transform_level
 * @property {string} table_group_data_product
 * * Profile & Test Runs
 * @property {string?} profile_run_id
 * @property {number?} profile_run_date
 * @property {boolean?} is_latest_profile
 * @property {number?} has_test_runs
 * * Scores
 * @property {string?} dq_score
 * @property {string?} dq_score_profiling
 * @property {string?} dq_score_testing
 * * Value Counts
 * @property {number} record_ct
 * @property {number} value_ct
 * @property {number} distinct_value_ct
 * @property {number} null_value_ct
 * @property {number} zero_value_ct
 * * Alpha
 * @property {number} zero_length_ct
 * @property {number} filled_value_ct
 * @property {number} mixed_case_ct
 * @property {number} lower_case_ct
 * @property {number} upper_case_ct
 * @property {number} non_alpha_ct
 * @property {number} includes_digit_ct
 * @property {number} numeric_ct
 * @property {number} date_ct
 * @property {number} quoted_value_ct
 * @property {number} lead_space_ct
 * @property {number} embedded_space_ct
 * @property {number} avg_embedded_spaces
 * @property {number} min_length
 * @property {number} max_length
 * @property {number} avg_length
 * @property {string} min_text
 * @property {string} max_text
 * @property {number} distinct_std_value_ct
 * @property {number} distinct_pattern_ct
 * @property {'STREET_ADDR' | 'STATE_USA' | 'PHONE_USA' | 'EMAIL' | 'ZIP_USA' | 'FILE_NAME' | 'CREDIT_CARD' | 'DELIMITED_DATA' | 'SSN'} std_pattern_match
 * @property {string} top_freq_values
 * @property {string} top_patterns
 * * Numeric
 * @property {number} min_value
 * @property {number} min_value_over_0
 * @property {number} max_value
 * @property {number} avg_value
 * @property {number} stdev_value
 * @property {number} percentile_25
 * @property {number} percentile_50
 * @property {number} percentile_75
 * * Date
 * @property {number} min_date
 * @property {number} max_date
 * @property {number} before_1yr_date_ct
 * @property {number} before_5yr_date_ct
 * @property {number} before_20yr_date_ct
 * @property {number} within_1yr_date_ct
 * @property {number} within_1mo_date_ct
 * @property {number} future_date_ct
 * * Boolean
 * @property {number} boolean_true_ct
 * * Issues
 * @property {HygieneIssue[]?} hygiene_issues
 * @property {TestIssue[]?} test_issues
 * * Test Suites
 * @property {TestSuite[]?} test_suites
 *
 * @typedef Table
 * @type {object}
 * @property {string} id
 * @property {'table'} type
 * @property {string} table_name
 * @property {string} schema_name
 * @property {string} table_group_id
 * @property {string} connection_id
 * @property {string} project_code
 * * Characteristics
 * @property {string} functional_table_type
 * @property {number} record_ct
 * @property {number} column_ct
 * @property {number} data_point_ct
 * @property {number} add_date
 * @property {number} last_refresh_date
 * @property {number} drop_date
 * * Table Tags
 * @property {string} description
 * @property {boolean} critical_data_element
 * @property {string} data_source
 * @property {string} source_system
 * @property {string} source_process
 * @property {string} business_domain
 * @property {string} stakeholder_group
 * @property {string} transform_level
 * @property {string} aggregation_level
 * @property {string} data_product
 * * Table Group Tags
 * @property {string} table_group_data_source
 * @property {string} table_group_source_system
 * @property {string} table_group_source_process
 * @property {string} table_group_business_domain
 * @property {string} table_group_stakeholder_group
 * @property {string} table_group_transform_level
 * @property {string} table_group_data_product
 * * Profile & Test Runs
 * @property {string} profile_run_id
 * @property {number} profile_run_date
 * @property {boolean} is_latest_profile
 * @property {number} has_test_runs
 * * Scores
 * @property {string} dq_score
 * @property {string} dq_score_profiling
 * @property {string} dq_score_testing
 * * Issues
 * @property {HygieneIssue[]?} hygiene_issues
 * @property {TestIssue[]?} test_issues
 * * Test Suites
 * @property {TestSuite[]?} test_suites
 */
import van from '../van.min.js';
import { Link } from '../components/link.js';
import { formatTimestamp } from '../display_utils.js';

const { span, b } = van.tags;

const TABLE_ICON = { icon: 'table' };
const COLUMN_ICONS = {
    A: { icon: 'abc', iconSize: 24 },
    B: { icon: 'toggle_off' },
    D: { icon: 'calendar_clock' },
    N: { icon: '123', iconSize: 24 },
    T: { icon: 'calendar_clock' },
    X: { icon: 'question_mark', iconSize: 18 },
};
const BOOLEAN_TYPE = 'Boolean';

const getColumnIcon = (/** @type Column */ column) => {
    const type = column.functional_data_type === BOOLEAN_TYPE ? 'B' : (column.general_type || 'X');
    return COLUMN_ICONS[type];
};

/**
 * @typedef Properties
 * @type {object}
 * @property {boolean?} noLinks
 */
const LatestProfilingTime = (/** @type Properties */ props, /** @type Table | Column */ item) => {
    let text = [
        'as of latest profiling run on ',
        props.noLinks ? b(formatTimestamp(item.profile_run_date)) : null,
    ];
    let link = Link({
        href: 'profiling-runs:results',
        params: {
            run_id: item.profile_run_id,
            table_name: item.table_name,
            column_name: item.column_name,
        },
        open_new: true,
        label: formatTimestamp(item.profile_run_date),
    });
    if (!item.profile_run_id) {
        if (item.drop_date) {
            text = 'No profiling results for table group';
            link = null;
        } else {
            text = 'No profiling results yet for table group.';
            link = Link({
                href: 'table-groups',
                params: { project_code: item.project_code, connection_id: item.connection_id },
                open_new: true,
                label: 'Go to Table Groups',
                right_icon: 'chevron_right',
            });
        }
    }
    return span(
        { class: 'flex-row fx-gap-1 fx-justify-content-flex-end text-secondary' },
        '* ',
        text,
        props.noLinks ? null : link,
    );
}

export { TABLE_ICON, getColumnIcon, LatestProfilingTime };
