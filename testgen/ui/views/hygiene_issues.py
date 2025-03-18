import typing
from functools import partial
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
from testgen.commands.run_rollup_scores import run_profile_rollup_scoring_queries
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import FILE_DATA_TYPE, download_dialog, zip_multi_file_data
from testgen.ui.navigation.page import Page
from testgen.ui.pdf.hygiene_issue_report import create_report
from testgen.ui.services import project_service, user_session_service
from testgen.ui.services.hygiene_issues_service import get_source_data as get_source_data_uncached
from testgen.ui.session import session
from testgen.ui.views.dialogs.profiling_results_dialog import view_profiling_button
from testgen.utils import friendly_score


class HygieneIssuesPage(Page):
    path = "profiling-runs:hygiene"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "run_id" in session.current_page_args or "profiling-runs",
    ]

    def render(
        self,
        run_id: str,
        issue_class: str | None = None,
        issue_type: str | None = None,
        table_name: str | None = None,
        column_name: str | None = None,
        **_kwargs,
    ) -> None:
        run_df = profiling_queries.get_run_by_id(run_id)
        if run_df.empty:
            self.router.navigate_with_warning(
                f"Profiling run with ID '{run_id}' does not exist. Redirecting to list of Profiling Runs ...",
                "profiling-runs",
            )
            return

        run_date = date_service.get_timezoned_timestamp(st.session_state, run_df["profiling_starttime"])
        project_service.set_current_project(run_df["project_code"])

        testgen.page_header(
            "Hygiene Issues",
            "view-hygiene-issues",
            breadcrumbs=[
                { "label": "Profiling Runs", "path": "profiling-runs", "params": { "project_code": run_df["project_code"] } },
                { "label": f"{run_df['table_groups_name']} | {run_date}" },
            ],
        )

        others_summary_column, pii_summary_column, score_column, actions_column = st.columns([.25, .25, .2, .3], vertical_alignment="bottom")
        (liklihood_filter_column, issue_type_filter_column, table_filter_column, column_filter_column, sort_column, export_button_column) = (
            st.columns([.15, .25, .2, .2, .1, .1], vertical_alignment="bottom")
        )
        testgen.flex_row_end(actions_column)
        testgen.flex_row_end(export_button_column)

        with liklihood_filter_column:
            issue_class = testgen.select(
                options=["Definite", "Likely", "Possible", "Potential PII"],
                default_value=issue_class,
                required=False,
                bind_to_query="issue_class",
                label="Issue Class",
            )

        with issue_type_filter_column:
            issue_type_options = get_issue_types()
            issue_type_id = testgen.select(
                options=issue_type_options,
                default_value=None if issue_class == "Potential PII" else issue_type,
                value_column="id",
                display_column="anomaly_name",
                required=False,
                bind_to_query="issue_type",
                label="Issue Type",
                disabled=issue_class == "Potential PII",
            )

        run_columns_df = get_profiling_run_columns(run_id)
        with table_filter_column:
            table_name = testgen.select(
                options=list(run_columns_df["table_name"].unique()),
                default_value=table_name,
                bind_to_query="table_name",
                label="Table Name",
            )

        with column_filter_column:
            column_options = list(run_columns_df.loc[run_columns_df["table_name"] == table_name]["column_name"].unique())
            column_name = testgen.select(
                options=column_options,
                value_column="column_name",
                default_value=column_name,
                bind_to_query="column_name",
                label="Column Name",
                disabled=not table_name,
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
        df_pa = get_profiling_anomalies(run_id, issue_class, issue_type_id, table_name, column_name, sorting_columns)

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
                    height=20,
                    width=400,
                )

            anomalies_pii_summary = [summary for summary in summaries if summary.get("type") == "PII"]
            if anomalies_pii_summary:
                with pii_summary_column:
                    testgen.summary_bar(
                        items=anomalies_pii_summary,
                        label="Potential PII",
                        height=20,
                        width=400,
                    )

            with score_column:
                render_score(run_df["project_code"], run_id)

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
                df_pa,
                lst_show_columns,
                int_height=400,
                do_multi_select=do_multi_select,
                bind_to_query_name="selected",
                bind_to_query_prop="id",
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
                col1, col2 = st.columns([0.8, 0.2])
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
                    view_profiling_button(
                        selected_row["column_name"], selected_row["table_name"], selected_row["table_groups_id"]
                    )

                    if st.button(
                        ":material/visibility: Source Data", help="View current source data for highlighted issue", use_container_width=True
                    ):
                        source_data_dialog(selected_row)
                    if st.button(
                            ":material/download: Issue Report",
                            use_container_width=True,
                            help="Generate a PDF report for each selected issue",
                    ):
                        dialog_title = "Download Issue Report"
                        if len(selected) == 1:
                            download_dialog(
                                dialog_title=dialog_title,
                                file_content_func=get_report_file_data,
                                args=(selected[0],),
                            )
                        else:
                            zip_func = zip_multi_file_data(
                                "testgen_hygiene_issue_reports.zip",
                                get_report_file_data,
                                [(arg,) for arg in selected],
                            )
                            download_dialog(dialog_title=dialog_title, file_content_func=zip_func)

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

            if user_session_service.user_can_disposition():
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
            "[Help on Hygiene Issues](https://docs.datakitchen.io/article/dataops-testgen-help/data-hygiene-issues)"
        )

@st.fragment
def render_score(project_code: str, run_id: str):
    run_df = profiling_queries.get_run_by_id(run_id)
    testgen.flex_row_center()
    with st.container():
        testgen.caption("Score", "text-align: center;")
        testgen.text(
            friendly_score(run_df["dq_score_profiling"]) or "--",
            "font-size: 28px;",
        )

    with st.container():
        testgen.whitespace(0.6)
        testgen.button(
            type_="icon",
            style="color: var(--secondary-text-color);",
            icon="autorenew",
            icon_size=22,
            tooltip=f"Recalculate scores for run {'and table group' if run_df["is_latest_run"] else ''}",
            on_click=partial(
                refresh_score,
                project_code,
                run_id,
                run_df["table_groups_id"] if run_df["is_latest_run"] else None,
            ),
        )


def refresh_score(project_code: str, run_id: str, table_group_id: str | None) -> None:
    run_profile_rollup_scoring_queries(project_code, run_id, table_group_id)
    st.cache_data.clear()


@st.cache_data(show_spinner="False")
def get_profiling_run_columns(profiling_run_id: str) -> pd.DataFrame:
    schema: str = st.session_state["dbschema"]
    sql = f"""
    SELECT table_name, column_name
    FROM {schema}.profile_anomaly_results
    WHERE profile_run_id = '{profiling_run_id}'
    ORDER BY table_name, column_name;
    """
    return db.retrieve_data(sql)


@st.cache_data(show_spinner="Retrieving Data")
def get_profiling_anomalies(
    profile_run_id: str,
    likelihood: str | None,
    issue_type_id: str | None,
    table_name: str | None,
    column_name: str | None,
    sorting_columns: list[str] | None,
):
    schema: str = st.session_state["dbschema"]
    criteria = ""
    order_by = ""

    if likelihood:
        criteria += f" AND t.issue_likelihood = '{likelihood}'"
    if issue_type_id:
        criteria += f" AND t.id = '{issue_type_id}'"
    if table_name:
        criteria += f" AND r.table_name = '{table_name}'"
    if column_name:
        criteria += f" AND r.column_name = '{column_name}'"

    if sorting_columns:
        order_by = "ORDER BY " + (", ".join(" ".join(col) for col in sorting_columns))

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
                   r.anomaly_id, r.table_groups_id::VARCHAR, r.id::VARCHAR, p.profiling_starttime, r.profile_run_id::VARCHAR,
                   tg.table_groups_name
              FROM {schema}.profile_anomaly_results r
            INNER JOIN {schema}.profile_anomaly_types t
               ON r.anomaly_id = t.id
            INNER JOIN {schema}.profiling_runs p
                ON r.profile_run_id = p.id
            INNER JOIN {schema}.table_groups tg
                ON r.table_groups_id = tg.id
             WHERE r.profile_run_id = '{profile_run_id}'
               {criteria}
            {order_by}
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
def get_source_data(hi_data):
    return get_source_data_uncached(hi_data)


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
        bad_data_status, bad_data_msg, _, df_bad = get_source_data(selected_row)
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

def get_report_file_data(update_progress, tr_data) -> FILE_DATA_TYPE:
    hi_id = tr_data["id"][:8]
    profiling_time = pd.Timestamp(tr_data["profiling_starttime"]).strftime("%Y%m%d_%H%M%S")
    file_name = f"testgen_hygiene_issue_report_{hi_id}_{profiling_time}.pdf"

    with BytesIO() as buffer:
        create_report(buffer, tr_data)
        update_progress(1.0)
        buffer.seek(0)
        return file_name, "application/pdf", buffer.read()
