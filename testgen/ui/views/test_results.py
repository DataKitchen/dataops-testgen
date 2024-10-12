import typing
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
from testgen.common import ConcatColumnList, date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.services import authentication_service, project_service
from testgen.ui.services.string_service import empty_if_null
from testgen.ui.session import session
from testgen.ui.views.profiling_modal import view_profiling_button
from testgen.ui.views.test_definitions import show_test_form_by_id

ALWAYS_SPIN = False


class TestResultsPage(Page):
    path = "test-runs:results"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: "run_id" in session.current_page_args or "test-runs",
    ]

    def render(self, run_id: str, status: str | None = None, test_type: str | None = None, **_kwargs) -> None:
        run_parentage = get_drill_test_run(run_id)
        if not run_parentage:
            self.router.navigate_with_warning(
                f"Test run with ID '{run_id}' does not exist. Redirecting to list of Test Runs ...",
                "test-runs",
            )

        run_date, test_suite_name, project_code = run_parentage
        run_date = date_service.get_timezoned_timestamp(st.session_state, run_date)
        project_service.set_current_project(project_code)

        testgen.page_header(
            "Test Results",
            "https://docs.datakitchen.io/article/dataops-testgen-help/test-results",
            breadcrumbs=[
                { "label": "Test Runs", "path": "test-runs", "params": { "project_code": project_code } },
                { "label": f"{test_suite_name} | {run_date}" },
            ],
        )

        # Display summary bar
        tests_summary = get_test_result_summary(run_id)
        testgen.summary_bar(items=tests_summary, height=40, width=800)

        # Setup Toolbar
        status_filter_column, test_type_filter_column, sort_column, actions_column, export_button_column = st.columns(
            [.2, .2, .08, .4, .12], vertical_alignment="bottom"
        )
        testgen.flex_row_end(actions_column)
        testgen.flex_row_end(export_button_column)

        with status_filter_column:
            status_options = [
                "Failed + Warning",
                "Failed",
                "Warning",
                "Passed",
            ]
            status = testgen.toolbar_select(
                options=status_options,
                default_value=status or "Failed + Warning",
                required=False,
                bind_to_query="status",
                label="Result Status",
            )

        with test_type_filter_column:
            test_type = testgen.toolbar_select(
                options=get_test_types(),
                value_column="test_type",
                display_column="test_name_short",
                default_value=test_type,
                required=False,
                bind_to_query="test_type",
                label="Test Type",
            )

        with sort_column:
            sortable_columns = (
                ("Table Name", "r.table_name"),
                ("Columns/Focus", "r.column_names"),
                ("Test Type", "r.test_type"),
                ("UOM", "tt.measure_uom"),
                ("Result Measure", "result_measure"),
                ("Status", "result_status"),
                ("Action", "r.disposition"),
            )
            default = [(sortable_columns[i][1], "ASC") for i in (0, 1, 2)]
            sorting_columns = testgen.sorting_selector(sortable_columns, default)

        with actions_column:
            str_help = "Toggle on to perform actions on multiple results"
            do_multi_select = st.toggle("Multi-Select", help=str_help)

        match status:
            case "Failed + Warning":
                status = "'Failed','Warning'"
            case "Failed":
                status = "'Failed'"
            case "Warning":
                status = "'Warning'"
            case "Passed":
                status = "'Passed'"

        # Display main grid and retrieve selection
        selected = show_result_detail(
            run_id, status, test_type, sorting_columns, do_multi_select, export_button_column
        )

        # Need to render toolbar buttons after grid, so selection status is maintained
        disable_dispo = True if not selected or status == "'Passed'" else False

        affected_cached_functions = [get_test_disposition]
        if "r.disposition" in dict(sorting_columns):
            affected_cached_functions.append(get_test_results)

        disposition_actions = [
            { "icon": "✓", "help": "Confirm this issue as relevant for this run", "status": "Confirmed" },
            { "icon": "✘", "help": "Dismiss this issue as not relevant for this run", "status": "Dismissed" },
            { "icon": "🔇", "help": "Mute this test to deactivate it for future runs", "status": "Inactive" },
            { "icon": "↩︎", "help": "Clear action", "status": "No Decision" },
        ]

        for action in disposition_actions:
            action["button"] = actions_column.button(action["icon"], help=action["help"], disabled=disable_dispo)

        # This has to be done as a second loop - otherwise, the rest of the buttons after the clicked one are not displayed briefly while refreshing
        for action in disposition_actions:
            if action["button"]:
                fm.reset_post_updates(
                    do_disposition_update(selected, action["status"]),
                    as_toast=True,
                    clear_cache=True,
                    lst_cached_functions=affected_cached_functions,
                )

        # Help Links
        st.markdown(
            "[Help on Test Types](https://docs.datakitchen.io/article/dataops-testgen-help/testgen-test-types)"
        )


@st.cache_data(show_spinner=ALWAYS_SPIN)
def get_drill_test_run(test_run_id: str) -> tuple[pd.Timestamp, str, str] | None:
    schema: str = st.session_state["dbschema"]
    sql = f"""
           SELECT tr.test_starttime as test_date,
                  ts.test_suite,
                  ts.project_code
             FROM {schema}.test_runs tr
       INNER JOIN {schema}.test_suites ts ON tr.test_suite_id = ts.id
            WHERE tr.id = '{test_run_id}'::UUID;
    """
    df = db.retrieve_data(sql)
    if not df.empty:
        return df.at[0, "test_date"], df.at[0, "test_suite"], df.at[0, "project_code"]


@st.cache_data(show_spinner=False)
def get_test_types():
    schema = st.session_state["dbschema"]
    df = db.retrieve_data(f"SELECT test_type, test_name_short FROM {schema}.test_types")
    return df


@st.cache_data(show_spinner="Retrieving Results")
def get_test_results(str_run_id, str_sel_test_status, test_type_id, sorting_columns):
    schema = st.session_state["dbschema"]
    return get_test_results_uncached(schema, str_run_id, str_sel_test_status, test_type_id, sorting_columns)


def get_test_results_uncached(str_schema, str_run_id, str_sel_test_status, test_type_id=None, sorting_columns=None):
    # First visible row first, so multi-select checkbox will render
    str_order_by = "ORDER BY " + (", ".join(" ".join(col) for col in sorting_columns)) if sorting_columns else ""
    test_type_clause = f"AND r.test_type = '{test_type_id}'" if test_type_id else ""
    status_clause = f" AND r.result_status IN ({str_sel_test_status})" if str_sel_test_status else ""
    str_sql = f"""
            WITH run_results
               AS (SELECT *
                     FROM {str_schema}.test_results r
                    WHERE
                      r.test_run_id = '{str_run_id}'
                      {status_clause}
                      {test_type_clause}
                    )
            SELECT r.table_name,
                   p.project_name, ts.test_suite, tg.table_groups_name, cn.connection_name, cn.project_host, cn.sql_flavor,
                   tt.dq_dimension, tt.test_scope,
                   r.schema_name, r.column_names, r.test_time::DATE as test_date, r.test_type, tt.id as test_type_id,
                   tt.test_name_short, tt.test_name_long, r.test_description, tt.measure_uom, tt.measure_uom_description,
                   c.test_operator, r.threshold_value::NUMERIC(16, 5), r.result_measure::NUMERIC(16, 5), r.result_status,
                   CASE
                     WHEN r.result_code <> 1 THEN r.disposition
                        ELSE 'Passed'
                   END as disposition,
                   NULL::VARCHAR(1) as action,
                   r.input_parameters, r.result_message, CASE WHEN result_code <> 1 THEN r.severity END as severity,
                   r.result_code as passed_ct,
                   (1 - r.result_code)::INTEGER as exception_ct,
                   CASE
                     WHEN result_status = 'Warning'
                      AND result_message NOT ILIKE 'Inactivated%%' THEN 1
                   END::INTEGER as warning_ct,
                   CASE
                     WHEN result_status = 'Failed'
                      AND result_message NOT ILIKE 'Inactivated%%' THEN 1
                   END::INTEGER as failed_ct,
                   CASE
                     WHEN result_message ILIKE 'Inactivated%%' THEN 1
                   END as execution_error_ct,
                   p.project_code, r.table_groups_id::VARCHAR,
                   r.id::VARCHAR as test_result_id, r.test_run_id::VARCHAR,
                   c.id::VARCHAR as connection_id, r.test_suite_id::VARCHAR,
                   r.test_definition_id::VARCHAR as test_definition_id_runtime,
                   CASE
                     WHEN r.auto_gen = TRUE THEN d.id
                                            ELSE r.test_definition_id
                   END::VARCHAR as test_definition_id_current,
                   r.auto_gen
              FROM run_results r
            INNER JOIN {str_schema}.test_types tt
               ON (r.test_type = tt.test_type)
            LEFT JOIN {str_schema}.test_definitions rd
              ON (r.test_definition_id = rd.id)
            LEFT JOIN {str_schema}.test_definitions d
               ON (r.test_suite_id = d.test_suite_id
              AND  r.table_name = d.table_name
              AND  r.column_names = COALESCE(d.column_name, 'N/A')
              AND  r.test_type = d.test_type
              AND  r.auto_gen = TRUE
              AND  d.last_auto_gen_date IS NOT NULL)
            INNER JOIN {str_schema}.test_suites ts
               ON r.test_suite_id = ts.id
            INNER JOIN {str_schema}.projects p
               ON (ts.project_code = p.project_code)
            INNER JOIN {str_schema}.table_groups tg
               ON (ts.table_groups_id = tg.id)
            INNER JOIN {str_schema}.connections cn
               ON (tg.connection_id = cn.connection_id)
            LEFT JOIN {str_schema}.cat_test_conditions c
               ON (cn.sql_flavor = c.sql_flavor
              AND  r.test_type = c.test_type)
            {str_order_by} ;
    """
    df = db.retrieve_data(str_sql)

    # Clean Up
    df["test_date"] = pd.to_datetime(df["test_date"])

    return df


@st.cache_data(show_spinner="Retrieving Status")
def get_test_disposition(str_run_id):
    str_schema = st.session_state["dbschema"]
    str_sql = f"""
        SELECT id::VARCHAR, disposition
          FROM {str_schema}.test_results
         WHERE test_run_id = '{str_run_id}';
    """

    df = db.retrieve_data(str_sql)

    dct_replace = {"Confirmed": "✓", "Dismissed": "✘", "Inactive": "🔇", "Passed": ""}
    df["action"] = df["disposition"].replace(dct_replace)

    return df[["id", "action"]]


@st.cache_data(show_spinner=ALWAYS_SPIN)
def get_test_result_summary(run_id):
    schema = st.session_state["dbschema"]
    sql = f"""
    SELECT SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Passed' THEN 1
                ELSE 0
            END
        ) as passed_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Warning' THEN 1
                ELSE 0
            END
        ) as warning_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Failed' THEN 1
                ELSE 0
            END
        ) as failed_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                AND test_results.result_status = 'Error' THEN 1
                ELSE 0
            END
        ) as error_ct,
        SUM(
            CASE
                WHEN COALESCE(test_results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                ELSE 0
            END
        ) as dismissed_ct
    FROM {schema}.test_runs
        LEFT JOIN {schema}.test_results ON (
            test_runs.id = test_results.test_run_id
        )
    WHERE test_runs.id = '{run_id}'::UUID;
    """
    df = db.retrieve_data(sql)

    return [
        { "label": "Passed", "value": int(df.at[0, "passed_ct"]), "color": "green" },
        { "label": "Warning", "value": int(df.at[0, "warning_ct"]), "color": "yellow" },
        { "label": "Failed", "value": int(df.at[0, "failed_ct"]), "color": "red" },
        { "label": "Error", "value": int(df.at[0, "error_ct"]), "color": "brown" },
        { "label": "Dismissed", "value": int(df.at[0, "dismissed_ct"]), "color": "grey" },
    ]


@st.cache_data(show_spinner=ALWAYS_SPIN)
def get_test_result_history(str_test_type, str_test_suite_id, str_table_name, str_column_names,
                            str_test_definition_id, auto_gen):
    str_schema = st.session_state["dbschema"]

    if auto_gen:
        str_where = f"""
            WHERE test_suite_id = '{str_test_suite_id}'
              AND table_name = '{str_table_name}'
              AND column_names = '{str_column_names}'
              AND test_type = '{str_test_type}'
              AND auto_gen = TRUE
        """
    else:
        str_where = f"""
            WHERE test_definition_id_runtime = '{str_test_definition_id}'
        """

    str_sql = f"""
           SELECT test_date, test_type,
                  test_name_short, test_name_long, measure_uom, test_operator,
                  threshold_value::NUMERIC, result_measure, result_status
             FROM {str_schema}.v_test_results {str_where}
           ORDER BY test_date DESC;
    """

    df = db.retrieve_data(str_sql)
    # Clean Up
    df["test_date"] = pd.to_datetime(df["test_date"])

    return df


@st.cache_data(show_spinner=ALWAYS_SPIN)
def get_test_definition(str_test_def_id):
    str_schema = st.session_state["dbschema"]
    return get_test_definition_uncached(str_schema, str_test_def_id)


def get_test_definition_uncached(str_schema, str_test_def_id):
    str_sql = f"""
           SELECT d.id::VARCHAR, tt.test_name_short as test_name, tt.test_name_long as full_name,
                  tt.test_description as description, tt.usage_notes,
                  d.column_name,
                  d.baseline_value, d.baseline_ct, d.baseline_avg, d.baseline_sd, d.threshold_value,
                  d.subset_condition, d.groupby_names, d.having_condition, d.match_schema_name,
                  d.match_table_name, d.match_column_names, d.match_subset_condition,
                  d.match_groupby_names, d.match_having_condition,
                  d.window_date_column, d.window_days::VARCHAR as window_days,
                  d.custom_query,
                  d.severity, tt.default_severity,
                  d.test_active, d.lock_refresh, d.last_manual_update
             FROM {str_schema}.test_definitions d
           INNER JOIN {str_schema}.test_types tt
              ON (d.test_type = tt.test_type)
            WHERE d.id = '{str_test_def_id}';
    """
    return db.retrieve_data(str_sql)


@st.cache_data(show_spinner=False)
def do_source_data_lookup(selected_row):
    schema = st.session_state["dbschema"]
    return do_source_data_lookup_uncached(schema, selected_row)


def do_source_data_lookup_uncached(str_schema, selected_row, sql_only=False):
    # Define the query
    str_sql = f"""
            SELECT t.lookup_query, tg.table_group_schema, c.project_qc_schema,
                   c.sql_flavor, c.project_host, c.project_port, c.project_db, c.project_user, c.project_pw_encrypted,
                   c.url, c.connect_by_url,
                   c.connect_by_key, c.private_key, c.private_key_passphrase
              FROM {str_schema}.target_data_lookups t
            INNER JOIN {str_schema}.table_groups tg
               ON ('{selected_row["table_groups_id"]}'::UUID = tg.id)
            INNER JOIN {str_schema}.connections c
               ON (tg.connection_id = c.connection_id)
               AND (t.sql_flavor = c.sql_flavor)
             WHERE t.error_type = 'Test Results'
               AND t.test_id = '{selected_row["test_type_id"]}'
               AND t.lookup_query > '';
    """

    def replace_parms(df_test, str_query):
        if df_test.empty:
            raise ValueError("This test definition is no longer present.")

        str_query = str_query.replace("{TARGET_SCHEMA}", empty_if_null(lst_query[0]["table_group_schema"]))
        str_query = str_query.replace("{TABLE_NAME}", empty_if_null(selected_row["table_name"]))
        str_query = str_query.replace("{COLUMN_NAME}", empty_if_null(selected_row["column_names"]))
        str_query = str_query.replace("{DATA_QC_SCHEMA}", empty_if_null(lst_query[0]["project_qc_schema"]))
        str_query = str_query.replace("{TEST_DATE}", str(empty_if_null(selected_row["test_date"])))

        str_query = str_query.replace("{CUSTOM_QUERY}", empty_if_null(df_test.at[0, "custom_query"]))
        str_query = str_query.replace("{BASELINE_VALUE}", empty_if_null(df_test.at[0, "baseline_value"]))
        str_query = str_query.replace("{BASELINE_CT}", empty_if_null(df_test.at[0, "baseline_ct"]))
        str_query = str_query.replace("{BASELINE_AVG}", empty_if_null(df_test.at[0, "baseline_avg"]))
        str_query = str_query.replace("{BASELINE_SD}", empty_if_null(df_test.at[0, "baseline_sd"]))
        str_query = str_query.replace("{THRESHOLD_VALUE}", empty_if_null(df_test.at[0, "threshold_value"]))

        str_substitute = empty_if_null(df_test.at[0, "subset_condition"])
        str_substitute = "1=1" if str_substitute == "" else str_substitute
        str_query = str_query.replace("{SUBSET_CONDITION}", str_substitute)

        str_query = str_query.replace("{GROUPBY_NAMES}", empty_if_null(df_test.at[0, "groupby_names"]))
        str_query = str_query.replace("{HAVING_CONDITION}", empty_if_null(df_test.at[0, "having_condition"]))
        str_query = str_query.replace("{MATCH_SCHEMA_NAME}", empty_if_null(df_test.at[0, "match_schema_name"]))
        str_query = str_query.replace("{MATCH_TABLE_NAME}", empty_if_null(df_test.at[0, "match_table_name"]))
        str_query = str_query.replace("{MATCH_COLUMN_NAMES}", empty_if_null(df_test.at[0, "match_column_names"]))

        str_substitute = empty_if_null(df_test.at[0, "match_subset_condition"])
        str_substitute = "1=1" if str_substitute == "" else str_substitute
        str_query = str_query.replace("{MATCH_SUBSET_CONDITION}", str_substitute)

        str_query = str_query.replace("{MATCH_GROUPBY_NAMES}", empty_if_null(df_test.at[0, "match_groupby_names"]))
        str_query = str_query.replace("{MATCH_HAVING_CONDITION}", empty_if_null(df_test.at[0, "match_having_condition"]))
        str_query = str_query.replace("{COLUMN_NAME_NO_QUOTES}", empty_if_null(selected_row["column_names"]))

        str_query = str_query.replace("{WINDOW_DATE_COLUMN}", empty_if_null(df_test.at[0, "window_date_column"]))
        str_query = str_query.replace("{WINDOW_DAYS}", empty_if_null(df_test.at[0, "window_days"]))

        str_substitute = ConcatColumnList(selected_row["column_names"], "<NULL>")
        str_query = str_query.replace("{CONCAT_COLUMNS}", str_substitute)
        str_substitute = ConcatColumnList(df_test.at[0, "match_groupby_names"], "<NULL>")
        str_query = str_query.replace("{CONCAT_MATCH_GROUPBY}", str_substitute)

        if str_query is None or str_query == "":
            raise ValueError("Lookup query is not defined for this Test Type.")
        return str_query

    try:
        # Retrieve SQL for customer lookup
        lst_query = db.retrieve_data_list(str_sql)

        if sql_only:
            return lst_query, replace_parms, None

        # Retrieve and return data as df
        if lst_query:
            df_test = get_test_definition(selected_row["test_definition_id_current"])

            str_sql = replace_parms(df_test, lst_query[0]["lookup_query"])
            df = db.retrieve_target_db_df(
                lst_query[0]["sql_flavor"],
                lst_query[0]["project_host"],
                lst_query[0]["project_port"],
                lst_query[0]["project_db"],
                lst_query[0]["project_user"],
                lst_query[0]["project_pw_encrypted"],
                str_sql,
                lst_query[0]["url"],
                lst_query[0]["connect_by_url"],
                lst_query[0]["connect_by_key"],
                lst_query[0]["private_key"],
                lst_query[0]["private_key_passphrase"],
            )
            if df.empty:
                return "ND", "Data that violates Test criteria is not present in the current dataset.", None
            else:
                return "OK", None, df
        else:
            return "NA", "A source data lookup for this Test is not available.", None

    except Exception as e:
        return "ERR", f"Source data lookup query caused an error:\n\n{e.args[0]}\n\n{str_sql}", None


@st.cache_data(show_spinner=False)
def do_source_data_lookup_custom(selected_row):
    str_schema = st.session_state["dbschema"]
    # Define the query
    str_sql = f"""
            SELECT d.custom_query as lookup_query, tg.table_group_schema, c.project_qc_schema,
                   c.sql_flavor, c.project_host, c.project_port, c.project_db, c.project_user, c.project_pw_encrypted,
                   c.url, c.connect_by_url, c.connect_by_key, c.private_key, c.private_key_passphrase
              FROM {str_schema}.test_definitions d
            INNER JOIN {str_schema}.table_groups tg
               ON ('{selected_row["table_groups_id"]}'::UUID = tg.id)
            INNER JOIN {str_schema}.connections c
               ON (tg.connection_id = c.connection_id)
             WHERE d.id = '{selected_row["test_definition_id_current"]}';
    """

    try:
        # Retrieve SQL for customer lookup
        lst_query = db.retrieve_data_list(str_sql)

        # Retrieve and return data as df
        if lst_query:
            str_sql = lst_query[0]["lookup_query"]
            str_sql = str_sql.replace("{DATA_SCHEMA}", empty_if_null(lst_query[0]["table_group_schema"]))
            df = db.retrieve_target_db_df(
                lst_query[0]["sql_flavor"],
                lst_query[0]["project_host"],
                lst_query[0]["project_port"],
                lst_query[0]["project_db"],
                lst_query[0]["project_user"],
                lst_query[0]["project_pw_encrypted"],
                str_sql,
                lst_query[0]["url"],
                lst_query[0]["connect_by_url"],
                lst_query[0]["connect_by_key"],
                lst_query[0]["private_key"],
                lst_query[0]["private_key_passphrase"],
            )
            if df.empty:
                return "ND", "Data that violates Test criteria is not present in the current dataset.", None
            else:
                return "OK", None, df
        else:
            return "NA", "A source data lookup for this Test is not available.", None

    except Exception as e:
        return "ERR", f"Source data lookup query caused an error:\n\n{e.args[0]}\n\n{str_sql}", None


def show_test_def_detail(str_test_def_id):
    df = get_test_definition(str_test_def_id)

    specs = []
    if not df.empty:
        # Get First Row
        row = df.iloc[0]

        specs.append(
            fm.FieldSpec(
                "Usage Notes",
                "usage_notes",
                fm.FormWidget.text_area,
                row["usage_notes"],
                read_only=True,
                text_multi_lines=7,
            )
        )
        specs.append(
            fm.FieldSpec(
                "Threshold Value",
                "threshold_value",
                fm.FormWidget.number_input,
                float(row["threshold_value"]) if row["threshold_value"] else None,
                required=True,
            )
        )

        default_severity_choice = f"Test Default ({row['default_severity']})"

        spec = fm.FieldSpec("Test Result Urgency", "severity", fm.FormWidget.radio, row["severity"], required=True)
        spec.lst_option_text = [default_severity_choice, "Warning", "Fail", "Log"]
        spec.lst_option_values = [None, "Warning", "Fail", "Ignore"]
        spec.show_horizontal = True
        specs.append(spec)

        spec = fm.FieldSpec(
            "Perform Test in Future Runs", "test_active", fm.FormWidget.radio, row["test_active"], required=True
        )
        spec.lst_option_text = ["Yes", "No"]
        spec.lst_option_values = ["Y", "N"]
        spec.show_horizontal = True
        specs.append(spec)

        spec = fm.FieldSpec(
            "Lock from Refresh", "lock_refresh", fm.FormWidget.radio, row["lock_refresh"], required=True
        )
        spec.lst_option_text = ["Unlocked", "Locked"]
        spec.lst_option_values = ["N", "Y"]
        spec.show_horizontal = True
        specs.append(spec)

        specs.append(fm.FieldSpec("", "id", form_widget=fm.FormWidget.hidden, int_key=1, init_val=row["id"]))

        specs.append(
            fm.FieldSpec(
                "Last Manual Update",
                "last_manual_update",
                fm.FormWidget.date_input,
                row["last_manual_update"],
                date.today().strftime("%Y-%m-%d hh:mm:ss"),
                read_only=True,
            )
        )
        fm.render_form_by_field_specs(
            None,
            "test_definitions",
            specs,
            boo_display_only=True,
        )


def show_result_detail(str_run_id, str_sel_test_status, test_type_id, sorting_columns, do_multi_select, export_container):
    # Retrieve test results (always cached, action as null)
    df = get_test_results(str_run_id, str_sel_test_status, test_type_id, sorting_columns)
    # Retrieve disposition action (cache refreshed)
    df_action = get_test_disposition(str_run_id)
    # Update action from disposition df
    action_map = df_action.set_index("id")["action"].to_dict()
    df["action"] = df["test_result_id"].map(action_map).fillna(df["action"])

    lst_show_columns = [
        "table_name",
        "column_names",
        "test_name_short",
        "result_measure",
        "measure_uom",
        "result_status",
        "action",
    ]

    lst_show_headers = [
        "Table Name",
        "Columns/Focus",
        "Test Type",
        "Result Measure",
        "UOM",
        "Status",
        "Action",
    ]

    selected_rows = fm.render_grid_select(
        df, lst_show_columns, do_multi_select=do_multi_select, show_column_headers=lst_show_headers
    )

    with export_container:
        lst_export_columns = [
            "schema_name",
            "table_name",
            "column_names",
            "test_name_short",
            "test_description",
            "dq_dimension",
            "measure_uom",
            "measure_uom_description",
            "threshold_value",
            "severity",
            "result_measure",
            "result_status",
            "result_message",
            "action",
        ]
        lst_wrap_colunns = ["test_description"]
        lst_export_headers = [
            "Schema Name",
            "Table Name",
            "Columns/Focus",
            "Test Type",
            "Test Description",
            "DQ Dimension",
            "UOM",
            "UOM Description",
            "Threshold Value",
            "Severity",
            "Result Measure",
            "Status",
            "Message",
            "Action",
        ]
        fm.render_excel_export(
            df, lst_export_columns, "Test Results", "{TIMESTAMP}", lst_wrap_colunns, lst_export_headers
        )

    # Display history and detail for selected row
    if not selected_rows:
        st.markdown(":orange[Select a record to see more information.]")
    else:
        selected_row = selected_rows[len(selected_rows) - 1]
        dfh = get_test_result_history(
            selected_row["test_type"],
            selected_row["test_suite_id"],
            selected_row["table_name"],
            selected_row["column_names"],
            selected_row["test_definition_id_runtime"],
            selected_row["auto_gen"]
        )
        show_hist_columns = ["test_date", "threshold_value", "result_measure", "result_status"]

        time_columns = ["test_date"]
        date_service.accommodate_dataframe_to_timezone(dfh, st.session_state, time_columns)

        pg_col1, pg_col2 = st.columns([0.5, 0.5])

        with pg_col2:
            v_col1, v_col2, v_col3 = st.columns([0.33, 0.33, 0.33])
        if authentication_service.current_user_has_edit_role():
            view_edit_test(v_col1, selected_row["test_definition_id_current"])
        if selected_row["test_scope"] == "column":
            view_profiling_button(
                v_col2, selected_row["table_name"], selected_row["column_names"],
                str_table_groups_id=selected_row["table_groups_id"]
            )
        view_bad_data(v_col3, selected_row)

        with pg_col1:
            fm.show_subheader(selected_row["test_name_short"])
            st.markdown(f"###### {selected_row['test_description']}")
            st.caption(empty_if_null(selected_row["measure_uom_description"]))
            fm.render_grid_select(dfh, show_hist_columns)
        with pg_col2:
            ut_tab1, ut_tab2 = st.tabs(["History", "Test Definition"])
            with ut_tab1:
                if dfh.empty:
                    st.write("Test history not available.")
                else:
                    write_history_graph(dfh)
            with ut_tab2:
                show_test_def_detail(selected_row["test_definition_id_current"])
        return selected_rows


def write_history_graph(dfh):
    y_min = min(dfh["result_measure"].min(), dfh["threshold_value"].min())
    y_max = max(dfh["result_measure"].max(), dfh["threshold_value"].max())
    str_uom = dfh.at[0, "measure_uom"]

    fig = px.line(
        dfh,
        x="test_date",
        y="result_measure",
        title=None,
        labels={"test_date": "Test Date", "result_measure": str_uom},
        line_shape="linear",
    )

    # Add dots at every observation
    fig.add_scatter(x=dfh["test_date"], y=dfh["result_measure"], mode="markers", name="Observations")

    if all(dfh["test_operator"].isin(["<", "<="])):
        # Add shaded region below: exception if under threshold
        fig.add_trace(
            go.Scatter(
                x=dfh["test_date"],
                y=dfh["threshold_value"],
                fill="tozeroy",
                fillcolor="rgba(255,182,193,0.5)",
                line_color="rgba(255,182,193,0.5)",
                mode="none",
                name="Threshold",
            )
        )
    elif all(dfh["test_operator"].isin([">", ">="])):
        # Add shaded region above: exception if over threshold
        fig.add_trace(
            go.Scatter(
                x=dfh["test_date"],
                y=[max(dfh["threshold_value"]) * 1.1] * len(dfh["test_date"]),  # some value above the maximum threshold
                mode="lines",
                line={"width": 0},  # making this line invisible
                showlegend=False,
            )
        )

        # Now, fill between this auxiliary line and the threshold line
        fig.add_trace(
            go.Scatter(
                x=dfh["test_date"],
                y=dfh["threshold_value"],
                fill="tonexty",
                fillcolor="rgba(255,182,193,0.5)",
                line_color="rgba(255,182,193,0.5)",
                mode="none",
                name="Threshold",
            )
        )
    elif all(dfh["test_operator"].isin(["=", "<>"])):
        # Show line instead of shaded region: pink/exception if equal, green/exception if not equal
        str_line_color = "rgba(255,182,193,0.5)" if all(dfh["test_operator"]) == "=" else "rgba(144, 238, 144, 1)"
        fig.add_trace(
            go.Scatter(
                x=dfh["test_date"],
                y=dfh["threshold_value"],
                line_color=str_line_color,
                mode="lines",  # only lines, no markers
                line={"width": 5},
                name="Threshold",
            )
        )
    # Update the Y-Axis to start from the minimum value

    if y_min > 0 and y_max - y_min < 0.1 * y_max:
        fig.update_layout(yaxis={"range": [y_min, y_max]})

    fig.update_layout(legend={"x": 0.5, "y": 1.1, "xanchor": "center", "yanchor": "top", "orientation": "h"})
    fig.update_layout(width=500, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")

    st.plotly_chart(fig)


def do_disposition_update(selected, str_new_status):
    str_result = None
    if selected:
        if len(selected) > 1:
            str_which = f"of {len(selected)} results to {str_new_status}"
        elif len(selected) == 1:
            str_which = f"of one result to {str_new_status}"

        str_schema = st.session_state["dbschema"]
        if not dq.update_result_disposition(selected, str_schema, str_new_status):
            str_result = f":red[**The update {str_which} did not succeed.**]"

    return str_result


def view_bad_data(button_container, selected_row):
    with button_container:
        if st.button(
            "Source Data →", help="Review current source data for highlighted result", use_container_width=True
        ):
            source_data_dialog(selected_row)


@st.dialog(title="Source Data")
def source_data_dialog(selected_row):
    st.markdown(f"#### {selected_row['test_name_short']}")
    st.caption(selected_row["test_description"])
    fm.show_prompt(f"Column: {selected_row['column_names']}, Table: {selected_row['table_name']}")

    # Show detail
    fm.render_html_list(
        selected_row, ["input_parameters", "result_message"], None, 700, ["Test Parameters", "Result Detail"]
    )

    with st.spinner("Retrieving source data..."):
        if selected_row["test_type"] == "CUSTOM":
            bad_data_status, bad_data_msg, df_bad = do_source_data_lookup_custom(selected_row)
        else:
            bad_data_status, bad_data_msg, df_bad = do_source_data_lookup(selected_row)
    if bad_data_status in {"ND", "NA"}:
        st.info(bad_data_msg)
    elif bad_data_status == "ERR":
        st.error(bad_data_msg)
    elif df_bad is None:
        st.error("An unknown error was encountered.")
    else:
        if bad_data_msg:
            st.info(bad_data_msg)
        # Pretify the dataframe
        df_bad.columns = [col.replace("_", " ").title() for col in df_bad.columns]
        df_bad.fillna("[NULL]", inplace=True)
        # Display the dataframe
        st.dataframe(df_bad, height=500, width=1050, hide_index=True)


def view_edit_test(button_container, test_definition_id):
    with button_container:
        if st.button("🖊️ Edit Test", help="Edit the Test Definition", use_container_width=True):
            show_test_form_by_id(test_definition_id)
