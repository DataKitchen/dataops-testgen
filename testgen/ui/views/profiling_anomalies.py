import typing

import plotly.express as px
import streamlit as st

import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
import testgen.ui.services.toolbar_service as tb
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.session import session
from testgen.ui.views.profiling_modal import view_profiling_button


class ProfilingAnomaliesPage(Page):
    path = "profiling:hygiene"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]

    def render(self) -> None:
        export_container = fm.render_page_header(
            "Hygiene Issues",
            "https://docs.datakitchen.io/article/dataops-testgen-help/profile-anomalies",
            lst_breadcrumbs=[
                {"label": "Overview", "path": "overview"},
                {"label": "Data Profiling", "path": "profiling"},
                {"label": "Hygiene Issues", "path": None},
            ],
        )

        if "project" not in st.session_state:
            st.write("Select a Project from the Overview page.")
        else:
            str_project = st.session_state["project"]

            # Setup Toolbar
            tool_bar = tb.ToolBar(3, 1, 4, None)

            # Look for drill-down from another page
            # No need to clear -- will be sent every time page is accessed
            str_drill_tg = st.session_state.get("drill_profile_tg")
            str_drill_prun = st.session_state.get("drill_profile_run")

            with tool_bar.long_slots[0]:
                # Table Groups selection
                df_tg = get_db_table_group_choices(str_project)
                str_drill_tg_name = (
                    df_tg[df_tg["id"] == str_drill_tg]["table_groups_name"].values[0] if str_drill_tg else None
                )
                str_table_groups_id = fm.render_select(
                    "Table Group", df_tg, "table_groups_name", "id", str_default=str_drill_tg_name, boo_disabled=True
                )

            str_profile_run_id = str_drill_prun

            with tool_bar.long_slots[1]:
                # Likelihood selection - optional filter
                lst_status_options = ["All Likelihoods", "Definite", "Likely", "Possible", "Potential PII"]
                str_likelihood = st.selectbox("Issue Class", lst_status_options)

            with tool_bar.short_slots[0]:
                str_help = "Toggle on to perform actions on multiple Hygiene Issues"
                do_multi_select = st.toggle("Multi-Select", help=str_help)

            if str_table_groups_id:
                # Get hygiene issue list
                df_pa = get_profiling_anomalies(str_profile_run_id, str_likelihood)

                # Retrieve disposition action (cache refreshed)
                df_action = get_anomaly_disposition(str_profile_run_id)
                # Update action from disposition df
                action_map = df_action.set_index("id")["action"].to_dict()
                df_pa["action"] = df_pa["id"].map(action_map).fillna(df_pa["action"])

                if not df_pa.empty:
                    # Display summary bar
                    anomalies_summary = get_profiling_anomaly_summary(str_profile_run_id)
                    testgen.summary_bar(items=anomalies_summary, key="test_results", height=40, width=800)
                    # write_frequency_graph(df_pa)
                    
                    lst_show_columns = [
                        "table_name",
                        "column_name",
                        "issue_likelihood",
                        "action",
                        "anomaly_name",
                        "detail",
                    ]
                    # TODO: Can we reintegrate percents below:
                    # tool_bar.set_prompt(
                    #     f"Hygiene Issues Found:  {df_sum.at[0, 'issue_ct']} issues in {df_sum.at[0, 'column_ct']} columns, {df_sum.at[0, 'table_ct']} tables in schema {df_pa.loc[0, 'schema_name']}"
                    # )
                    # Show main grid and retrieve selections
                    selected = fm.render_grid_select(
                        df_pa, lst_show_columns, int_height=400, do_multi_select=do_multi_select
                    )

                    with export_container:
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
                            str_profile_run_id=str_profile_run_id
                        )
                        with v_col2:
                            if st.button(
                                ":green[Source Data →]", help="Review current source data for highlighted issue", use_container_width=True
                            ):
                                source_data_dialog(selected_row)

                    # Need to render toolbar buttons after grid, so selection status is maintained
                    if tool_bar.button_slots[0].button(
                        "✓", help="Confirm this issue as relevant for this run", disabled=not selected
                    ):
                        fm.reset_post_updates(
                            do_disposition_update(selected, "Confirmed"),
                            as_toast=True,
                            clear_cache=True,
                            lst_cached_functions=[get_anomaly_disposition, get_profiling_anomaly_summary],
                        )
                    if tool_bar.button_slots[1].button(
                        "✘", help="Dismiss this issue as not relevant for this run", disabled=not selected
                    ):
                        fm.reset_post_updates(
                            do_disposition_update(selected, "Dismissed"),
                            as_toast=True,
                            clear_cache=True,
                            lst_cached_functions=[get_anomaly_disposition, get_profiling_anomaly_summary],
                        )
                    if tool_bar.button_slots[2].button(
                        "🔇", help="Mute this test to deactivate it for future runs", disabled=not selected
                    ):
                        fm.reset_post_updates(
                            do_disposition_update(selected, "Inactive"),
                            as_toast=True,
                            clear_cache=True,
                            lst_cached_functions=[get_anomaly_disposition, get_profiling_anomaly_summary],
                        )
                    if tool_bar.button_slots[3].button("↩︎", help="Clear action", disabled=not selected):
                        fm.reset_post_updates(
                            do_disposition_update(selected, "No Decision"),
                            as_toast=True,
                            clear_cache=True,
                            lst_cached_functions=[get_anomaly_disposition, get_profiling_anomaly_summary],
                        )
                else:
                    tool_bar.set_prompt("No Hygiene Issues Found")

            # Help Links
            st.markdown(
                "[Help on Hygiene Issues](https://docs.datakitchen.io/article/dataops-testgen-help/profile-anomalies)"
            )

            # with st.sidebar:
            #     st.divider()


@st.cache_data(show_spinner=False)
def get_db_table_group_choices(str_project_code):
    str_schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(str_schema, str_project_code)


@st.cache_data(show_spinner="Retrieving Data")
def get_profiling_anomalies(str_profile_run_id, str_likelihood):
    str_schema = st.session_state["dbschema"]
    if str_likelihood == "All Likelihoods":
        str_criteria = " AND t.issue_likelihood <> 'Potential PII'"
    else:
        str_criteria = f" AND t.issue_likelihood = '{str_likelihood}'"
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
                   END as likelihood_explanation,
                   t.anomaly_description, r.detail, t.suggested_action,
                   r.anomaly_id, r.table_groups_id::VARCHAR, r.id::VARCHAR, p.profiling_starttime
              FROM {str_schema}.profile_anomaly_results r
            INNER JOIN {str_schema}.profile_anomaly_types t
               ON r.anomaly_id = t.id
            INNER JOIN {str_schema}.profiling_runs p
                ON r.profile_run_id = p.id
             WHERE r.profile_run_id = '{str_profile_run_id}'
               {str_criteria}
            ORDER BY r.schema_name, r.table_name, r.column_name;
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
def get_profiling_anomaly_summary(str_profile_run_id):
    str_schema = st.session_state["dbschema"]
    # Define the query
    str_sql = f"""
            SELECT schema_name,
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
                                  IN ('Dismissed', 'Inactive') THEN 1 ELSE 0 END) as dismissed_ct
              FROM {str_schema}.profile_anomaly_results s
            LEFT JOIN {str_schema}.profile_anomaly_types t
              ON (s.anomaly_id = t.id)
             WHERE s.profile_run_id = '{str_profile_run_id}'
            GROUP BY schema_name;
    """
    df = db.retrieve_data(str_sql)

    return [
        { "label": "Definite", "value": int(df.at[0, "definite_ct"]), "color": "red" },
        { "label": "Likely", "value": int(df.at[0, "likely_ct"]), "color": "orange" },
        { "label": "Possible", "value": int(df.at[0, "possible_ct"]), "color": "yellow" },
        { "label": "Dismissed", "value": int(df.at[0, "dismissed_ct"]), "color": "grey" },
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
