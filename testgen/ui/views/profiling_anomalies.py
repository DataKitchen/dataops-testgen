import typing

import plotly.express as px
import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.services import project_service
from testgen.ui.session import session
from testgen.ui.views.profiling_modal import view_profiling_button


class ProfilingAnomaliesPage(Page):
    path = "profiling-runs:hygiene"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: "run_id" in session.current_page_args or "profiling-runs",
    ]

    def render(self, run_id: str, issue_class: str | None = None, issue_type: str | None = None, **_kwargs) -> None:
        run_parentage = profiling_queries.lookup_db_parentage_from_run(run_id)
        if not run_parentage:
            self.router.navigate_with_warning(
                f"Profiling run with ID '{run_id}' does not exist. Redirecting to list of Profiling Runs ...",
                "profiling-runs",
            )
            
        run_date, _table_group_id, table_group_name, project_code = run_parentage
        run_date = date_service.get_timezoned_timestamp(st.session_state, run_date)
        project_service.set_current_project(project_code)

        testgen.page_header(
            "Hygiene Issues",
            "https://docs.datakitchen.io/article/dataops-testgen-help/profile-anomalies",
            breadcrumbs=[
                { "label": "Profiling Runs", "path": "profiling-runs", "params": { "project_code": project_code } },
                { "label": f"{table_group_name} | {run_date}" },
            ],
        )

        others_summary_column, pii_summary_column, _ = st.columns([.3, .3, .4])
        (liklihood_filter_column, issue_type_filter_column, sort_column, actions_column, export_button_column) = (
            st.columns([.16, .34, .08, .32, .1], vertical_alignment="bottom")
        )
        testgen.flex_row_end(actions_column)
        testgen.flex_row_end(export_button_column)

        with liklihood_filter_column:
            issue_class = testgen.toolbar_select(
                options=["Definite", "Likely", "Possible", "Potential PII"],
                default_value=issue_class,
                required=False,
                bind_to_query="issue_class",
                label="Issue Class",
            )

        with issue_type_filter_column:
            issue_type_options = get_issue_types()
            issue_type_id = testgen.toolbar_select(
                options=issue_type_options,
                default_value=None if issue_class == "Potential PII" else issue_type,
                value_column="id",
                display_column="anomaly_name",
                required=False,
                bind_to_query="issue_type",
                label="Issue Type",
                disabled=issue_class == "Potential PII",
            )

        with sort_column:
            sortable_columns = (
                ("Table", "r.table_name"),
                ("Column", "r.column_name"),
                ("Anomaly", "t.anomaly_name"),
                ("Likelihood", "likelihood_order"),
                ("Action", "r.disposition"),
            )
            default = [(sortable_columns[i][1], "ASC") for i in (0, 1)]
            sorting_columns = testgen.sorting_selector(sortable_columns, default)

        with actions_column:
            str_help = "Toggle on to perform actions on multiple Hygiene Issues"
            do_multi_select = st.toggle("Multi-Select", help=str_help)


        # Get hygiene issue list
        df_pa = get_profiling_anomalies(run_id, issue_class, issue_type_id, sorting_columns)

        # Retrieve disposition action (cache refreshed)
        df_action = get_anomaly_disposition(run_id)
        # Update action from disposition df
        action_map = df_action.set_index("id")["action"].to_dict()
        df_pa["action"] = df_pa["id"].map(action_map).fillna(df_pa["action"])

        if not df_pa.empty:
            summaries = get_profiling_anomaly_summary(run_id)
            others_summary = [summary for summary in summaries if summary.get("type") != "PII"]
            with others_summary_column:
                testgen.summary_bar(
                    items=others_summary,
                    label="Hygiene Issues",
                    height=40,
                    width=400,
                )

            anomalies_pii_summary = [summary for summary in summaries if summary.get("type") == "PII"]
            if anomalies_pii_summary:
                with pii_summary_column:
                    testgen.summary_bar(
                        items=anomalies_pii_summary,
                        label="Potential PII",
                        height=40,
                        width=400,
                    )
            # write_frequency_graph(df_pa)

            lst_show_columns = [
                "table_name",
                "column_name",
                "issue_likelihood",
                "action",
                "anomaly_name",
                "detail",
            ]

            # Show main grid and retrieve selections
            selected = fm.render_grid_select(
                df_pa, lst_show_columns, int_height=400, do_multi_select=do_multi_select
            )

            with export_button_column:
                lst_export_columns = [
                    "schema_name",
                    "table_name",
                    "column_name",
                    "anomaly_name",
                    "issue_likelihood",
                    "anomaly_description",
                    "action",
                    "detail",
                    "suggested_action",
                ]
                lst_wrap_columns = ["anomaly_description", "suggested_action"]
                fm.render_excel_export(
                    df_pa, lst_export_columns, "Hygiene Screen", "{TIMESTAMP}", lst_wrap_columns
                )

            if selected:
                # Always show details for last selected row
                selected_row = selected[len(selected) - 1]
            else:
                selected_row = None

            # Display hygiene issue detail for selected row
            if not selected_row:
                st.markdown(":orange[Select a record to see more information.]")
            else:
                col1, col2 = st.columns([0.7, 0.3])
                with col1:
                    fm.render_html_list(
                        selected_row,
                        [
                            "anomaly_name",
                            "table_name",
                            "column_name",
                            "column_type",
                            "anomaly_description",
                            "detail",
                            "likelihood_explanation",
                            "suggested_action",
                        ],
                        "Hygiene Issue Detail",
                        int_data_width=700,
                    )
                with col2:
                    # _, v_col2 = st.columns([0.3, 0.7])
                    v_col1, v_col2 = st.columns([0.5, 0.5])
                view_profiling_button(
                    v_col1, selected_row["table_name"], selected_row["column_name"],
                    str_profile_run_id=run_id
                )
                with v_col2:
                    if st.button(
                        "Source Data →", help="Review current source data for highlighted issue", use_container_width=True
                    ):
                        source_data_dialog(selected_row)

            cached_functions = [get_anomaly_disposition, get_profiling_anomaly_summary]
            # Clear the list cache if the list is sorted by disposition/action
            if "r.disposition" in dict(sorting_columns):
                cached_functions.append(get_profiling_anomalies)

            disposition_actions = [
                { "icon": "✓", "help": "Confirm this issue as relevant for this run", "status": "Confirmed" },
                { "icon": "✘", "help": "Dismiss this issue as not relevant for this run", "status": "Dismissed" },
                { "icon": "🔇", "help": "Mute this test to deactivate it for future runs", "status": "Inactive" },
                { "icon": "↩︎", "help": "Clear action", "status": "No Decision" },
            ]

            # Need to render toolbar buttons after grid, so selection status is maintained
            for action in disposition_actions:
                action["button"] = actions_column.button(action["icon"], help=action["help"], disabled=not selected)

            # This has to be done as a second loop - otherwise, the rest of the buttons after the clicked one are not displayed briefly while refreshing
            for action in disposition_actions:
                if action["button"]:
                    fm.reset_post_updates(
                        do_disposition_update(selected, action["status"]),
                        as_toast=True,
                        clear_cache=True,
                        lst_cached_functions=cached_functions,
                    )
        else:
            st.markdown(":green[**No Hygiene Issues Found**]")

        # Help Links
        st.markdown(
            "[Help on Hygiene Issues](https://docs.datakitchen.io/article/dataops-testgen-help/profile-anomalies)"
        )


@st.cache_data(show_spinner=False)
def get_db_table_group_choices(str_project_code):
    str_schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(str_schema, str_project_code)


@st.cache_data(show_spinner="Retrieving Data")
def get_profiling_anomalies(str_profile_run_id, str_likelihood, issue_type_id, sorting_columns):
    str_schema = st.session_state["dbschema"]
    if str_likelihood is None:
        str_criteria = " AND t.issue_likelihood <> 'Potential PII'"
    else:
        str_criteria = f" AND t.issue_likelihood = '{str_likelihood}'"
    if sorting_columns:
        str_order_by = "ORDER BY " + (", ".join(" ".join(col) for col in sorting_columns))
    else:
        str_order_by = ""
    if issue_type_id:
        str_criteria += f" AND t.id = '{issue_type_id}'"
    # Define the query -- first visible column must be first, because will hold the multi-select box
    str_sql = f"""
            SELECT r.table_name, r.column_name, r.schema_name,
                   r.column_type,t.anomaly_name, t.issue_likelihood,
                   r.disposition, null as action,
                   CASE
                     WHEN t.issue_likelihood = 'Possible' THEN 'Possible: speculative test that often identifies problems'
                     WHEN t.issue_likelihood = 'Likely'   THEN 'Likely: typically indicates a data problem'
                     WHEN t.issue_likelihood = 'Definite'  THEN 'Definite: indicates a highly-likely data problem'
                     WHEN t.issue_likelihood = 'Potential PII'
                       THEN 'Potential PII: may require privacy policies, standards and procedures for access, storage and transmission.'
                   END AS likelihood_explanation,
                   CASE
                     WHEN t.issue_likelihood = 'Potential PII' THEN 1
                     WHEN t.issue_likelihood = 'Possible' THEN 2
                     WHEN t.issue_likelihood = 'Likely'   THEN 3
                     WHEN t.issue_likelihood = 'Definite'  THEN 4
                   END AS likelihood_order,
                   t.anomaly_description, r.detail, t.suggested_action,
                   r.anomaly_id, r.table_groups_id::VARCHAR, r.id::VARCHAR, p.profiling_starttime
              FROM {str_schema}.profile_anomaly_results r
            INNER JOIN {str_schema}.profile_anomaly_types t
               ON r.anomaly_id = t.id
            INNER JOIN {str_schema}.profiling_runs p
                ON r.profile_run_id = p.id
             WHERE r.profile_run_id = '{str_profile_run_id}'
               {str_criteria}
            {str_order_by}
    """
    # Retrieve data as df
    df = db.retrieve_data(str_sql)

    dct_replace = {"Confirmed": "✓", "Dismissed": "✘", "Inactive": "🔇"}
    df["action"] = df["disposition"].replace(dct_replace)

    return df


@st.cache_data(show_spinner="Retrieving Status")
def get_anomaly_disposition(str_profile_run_id):
    str_schema = st.session_state["dbschema"]
    str_sql = f"""
            SELECT id::VARCHAR, disposition
              FROM {str_schema}.profile_anomaly_results s
             WHERE s.profile_run_id = '{str_profile_run_id}';
    """
    # Retrieve data as df
    df = db.retrieve_data(str_sql)
    dct_replace = {"Confirmed": "✓", "Dismissed": "✘", "Inactive": "🔇", "Passed": ""}
    df["action"] = df["disposition"].replace(dct_replace)

    return df[["id", "action"]]


@st.cache_data(show_spinner=False)
def get_issue_types():
    schema = st.session_state["dbschema"]
    df = db.retrieve_data(f"SELECT id, anomaly_name FROM {schema}.profile_anomaly_types")
    return df


@st.cache_data(show_spinner=False)
def get_profiling_anomaly_summary(str_profile_run_id):
    str_schema = st.session_state["dbschema"]
    # Define the query
    str_sql = f"""
        SELECT
            schema_name,
            COUNT(DISTINCT s.table_name) as table_ct,
            COUNT(DISTINCT s.column_name) as column_ct,
            COUNT(*) as issue_ct,
            SUM(CASE WHEN COALESCE(s.disposition, 'Confirmed') = 'Confirmed'
                        AND t.issue_likelihood = 'Definite' THEN 1 ELSE 0 END) as definite_ct,
            SUM(CASE WHEN COALESCE(s.disposition, 'Confirmed') = 'Confirmed'
                        AND t.issue_likelihood = 'Likely' THEN 1 ELSE 0 END) as likely_ct,
            SUM(CASE WHEN COALESCE(s.disposition, 'Confirmed') = 'Confirmed'
                        AND t.issue_likelihood = 'Possible' THEN 1 ELSE 0 END) as possible_ct,
            SUM(CASE WHEN COALESCE(s.disposition, 'Confirmed')
                            IN ('Dismissed', 'Inactive')
                        AND t.issue_likelihood <> 'Potential PII' THEN 1 ELSE 0 END) as dismissed_ct,
            SUM(CASE WHEN COALESCE(s.disposition, 'Confirmed') = 'Confirmed' AND t.issue_likelihood = 'Potential PII' AND s.detail LIKE 'Risk: HIGH%%' THEN 1 ELSE 0 END) as pii_high_ct,
            SUM(CASE WHEN COALESCE(s.disposition, 'Confirmed') = 'Confirmed' AND t.issue_likelihood = 'Potential PII' AND s.detail LIKE 'Risk: MODERATE%%' THEN 1 ELSE 0 END) as pii_moderate_ct,
            SUM(CASE WHEN COALESCE(s.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') AND t.issue_likelihood = 'Potential PII' THEN 1 ELSE 0 END) as pii_dismissed_ct
        FROM {str_schema}.profile_anomaly_results s
        LEFT JOIN {str_schema}.profile_anomaly_types t ON (s.anomaly_id = t.id)
        WHERE s.profile_run_id = '{str_profile_run_id}'
        GROUP BY schema_name;
    """
    df = db.retrieve_data(str_sql)

    return [
        { "label": "Definite", "value": int(df.at[0, "definite_ct"]), "color": "red" },
        { "label": "Likely", "value": int(df.at[0, "likely_ct"]), "color": "orange" },
        { "label": "Possible", "value": int(df.at[0, "possible_ct"]), "color": "yellow" },
        { "label": "Dismissed", "value": int(df.at[0, "dismissed_ct"]), "color": "grey" },
        { "label": "High Risk", "value": int(df.at[0, "pii_high_ct"]), "color": "red", "type": "PII" },
        { "label": "Moderate Risk", "value": int(df.at[0, "pii_moderate_ct"]), "color": "orange", "type": "PII" },
        { "label": "Dismissed", "value": int(df.at[0, "pii_dismissed_ct"]), "color": "grey", "type": "PII" },
    ]


@st.cache_data(show_spinner=False)
def get_bad_data(selected_row):
    str_schema = st.session_state["dbschema"]
    # Define the query
    str_sql = f"""
            SELECT t.lookup_query, tg.table_group_schema, c.project_qc_schema,
                   c.sql_flavor, c.project_host, c.project_port, c.project_db, c.project_user, c.project_pw_encrypted,
                   c.url, c.connect_by_url, c.connect_by_key, c.private_key, c.private_key_passphrase
              FROM {str_schema}.target_data_lookups t
            INNER JOIN {str_schema}.table_groups tg
               ON ('{selected_row["table_groups_id"]}'::UUID = tg.id)
            INNER JOIN {str_schema}.connections c
               ON (tg.connection_id = c.connection_id)
                AND (t.sql_flavor = c.sql_flavor)
             WHERE t.error_type = 'Profile Anomaly'
               AND t.test_id = '{selected_row["anomaly_id"]}'
               AND t.lookup_query > '';
    """

    def get_lookup_query(test_id, detail_exp, column_names):
        if test_id in {"1019", "1020"}:
            start_index = detail_exp.find("Columns: ")
            if start_index == -1:
                columns = [col.strip() for col in column_names.split(",")]
            else:
                start_index += len("Columns: ")
                column_names_str = detail_exp[start_index:]
                columns = [col.strip() for col in column_names_str.split(",")]
            queries = [
                f"SELECT '{column}' AS column_name, MAX({column}) AS max_date_available FROM {{TARGET_SCHEMA}}.{{TABLE_NAME}}"
                for column in columns
            ]
            sql_query = " UNION ALL ".join(queries) + " ORDER BY max_date_available DESC;"
        else:
            sql_query = ""
        return sql_query

    def replace_parms(str_query):
        str_query = (
            get_lookup_query(selected_row["anomaly_id"], selected_row["detail"], selected_row["column_name"])
            if lst_query[0]["lookup_query"] == "created_in_ui"
            else lst_query[0]["lookup_query"]
        )
        str_query = str_query.replace("{TARGET_SCHEMA}", lst_query[0]["table_group_schema"])
        str_query = str_query.replace("{TABLE_NAME}", selected_row["table_name"])
        str_query = str_query.replace("{COLUMN_NAME}", selected_row["column_name"])
        str_query = str_query.replace("{DATA_QC_SCHEMA}", lst_query[0]["project_qc_schema"])
        str_query = str_query.replace("{DETAIL_EXPRESSION}", selected_row["detail"])
        str_query = str_query.replace("{PROFILE_RUN_DATE}", selected_row["profiling_starttime"])
        if str_query is None or str_query == "":
            raise ValueError("Lookup query is not defined for this Anomoly Type.")
        return str_query

    try:
        # Retrieve SQL for customer lookup
        lst_query = db.retrieve_data_list(str_sql)

        # Retrieve and return data as df
        if lst_query:
            str_sql = replace_parms(str_sql)
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
                return "ND", "Data that violates Hygiene Issue criteria is not present in the current dataset.", None
            else:
                return "OK", None, df
        else:
            return "NA", "A source data lookup for this Issue is not available.", None

    except Exception as e:
        return "ERR", f"Source data lookup query caused an error:\n\n{e.args[0]}", None


def write_frequency_graph(df_tests):
    # Count the frequency of each test_name
    df_count = df_tests["anomaly_name"].value_counts().reset_index()
    df_count.columns = ["anomaly_name", "frequency"]

    # Sort the DataFrame by frequency in ascending order for display
    df_count = df_count.sort_values(by="frequency", ascending=True)

    # Create a horizontal bar chart using Plotly Express
    fig = px.bar(df_count, x="frequency", y="anomaly_name", orientation="h", title="Issue Frequency")
    fig.update_layout(title_font={"color": "green"}, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    if len(df_count) <= 5:
        # fig.update_layout(bargap=0.9)
        fig.update_layout(height=300)

    st.plotly_chart(fig)


@st.dialog(title="Source Data")
def source_data_dialog(selected_row):
    st.markdown(f"#### {selected_row['anomaly_name']}")
    st.caption(selected_row["anomaly_description"])
    fm.show_prompt(f"Column: {selected_row['column_name']}, Table: {selected_row['table_name']}")

    # Show the detail line
    fm.render_html_list(selected_row, ["detail"], None, 700, ["Hygiene Issue Detail"])

    with st.spinner("Retrieving source data..."):
        bad_data_status, bad_data_msg, df_bad = get_bad_data(selected_row)
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


def do_disposition_update(selected, str_new_status):
    str_result = None
    if selected:
        if len(selected) > 1:
            str_which = f"of {len(selected)} issues to {str_new_status}"
        elif len(selected) == 1:
            str_which = f"of one issue to {str_new_status}"

        str_schema = st.session_state["dbschema"]
        if not dq.update_anomaly_disposition(selected, str_schema, str_new_status):
            str_result = f":red[**The update {str_which} did not succeed.**]"

    return str_result
