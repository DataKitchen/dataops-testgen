/**
 * @typedef ProjectSummary
 * @type {object}
 * @property {string} project_code
 * @property {number} connection_count
 * @property {string} default_connection_id
 * @property {number} table_group_count
 * @property {number} profiling_run_count
 * @property {number} test_suite_count
 * @property {number} test_definition_count
 * @property {number} test_run_count
 * @property {bool} can_export_to_observability
 * 
 * @typedef TestSuiteSummary
 * @type {object}
 * @property {string} id
 * @property {string} project_code
 * @property {string} test_suite
 * @property {string} connection_name
 * @property {string} table_groups_id
 * @property {string} table_groups_name
 * @property {string} test_suite_description
 * @property {bool} export_to_observability
 * @property {number} test_ct
 * @property {string} last_complete_profile_run_id
 * @property {string} latest_run_id
 * @property {string} latest_run_start
 * @property {number} last_run_test_ct
 * @property {number} last_run_passed_ct
 * @property {number} last_run_warning_ct
 * @property {number} last_run_failed_ct
 * @property {number} last_run_error_ct
 * @property {number} last_run_dismissed_ct
 */
