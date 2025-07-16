import typing
from functools import partial
from io import BytesIO

import pandas as pd
import streamlit as st

import testgen.ui.queries.profiling_queries as profiling_queries
import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.query_service as dq
from testgen.commands.run_rollup_scores import run_profile_rollup_scoring_queries
from testgen.common import date_service
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import get_current_session
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
    zip_multi_file_data,
)
from testgen.ui.components.widgets.page import css_class, flex_row_end
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
        lambda: "run_id" in st.query_params or "profiling-runs",
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
        project_service.set_sidebar_project(run_df["project_code"])

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
            st.columns([.15, .2, .2, .2, .1, .15], vertical_alignment="bottom")
        )
        testgen.flex_row_end(actions_column)
        testgen.flex_row_end(export_button_column)

        with liklihood_filter_column:
            issue_class = testgen.select(
                options=["Definite", "Likely", "Possible", "Potential PII"],
                default_value=issue_class,
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
                accept_new_options=True,
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

        with st.container():
            with st.spinner("Loading data ..."):
                # Get hygiene issue list
                df_pa = get_profiling_anomalies(run_id, issue_class, issue_type_id, table_name, column_name, sorting_columns)

                # Retrieve disposition action (cache refreshed)
                df_action = get_anomaly_disposition(run_id)

                # Update action from disposition df
                action_map = df_action.set_index("id")["action"].to_dict()
                df_pa["action"] = df_pa["id"].map(action_map).fillna(df_pa["action"])

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

        popover_container = export_button_column.empty()

        def open_download_dialog(data: pd.DataFrame | None = None) -> None:
            # Hack to programmatically close popover: https://github.com/streamlit/streamlit/issues/8265#issuecomment-3001655849
            with popover_container.container():
                flex_row_end()
                st.button(label="Export", icon=":material/download:", disabled=True)

            download_dialog(
                dialog_title="Download Excel Report",
                file_content_func=get_excel_report_data,
                args=(run_df["table_groups_name"], run_date, run_id, data),
            )

        with popover_container.container(key="tg--export-popover"):
            flex_row_end()
            with st.popover(label="Export", icon=":material/download:", help="Download hygiene issues to Excel"):
                css_class("tg--export-wrapper")
                st.button(label="All issues", type="tertiary", on_click=open_download_dialog)
                st.button(label="Filtered issues", type="tertiary", on_click=partial(open_download_dialog, df_pa))
                if selected:
                    st.button(label="Selected issues", type="tertiary", on_click=partial(open_download_dialog, pd.DataFrame(selected)))

        if not df_pa.empty:
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
                        MixpanelService().send_event(
                            "view-source-data",
                            page=self.path,
                            issue_type=selected_row["anomaly_name"],
                        )
                        source_data_dialog(selected_row)
                    if st.button(
                            ":material/download: Issue Report",
                            use_container_width=True,
                            help="Generate a PDF report for each selected issue",
                    ):
                        MixpanelService().send_event(
                            "download-issue-report",
                            page=self.path,
                            issue_count=len(selected),
                        )
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


@st.cache_data(show_spinner=False)
def get_profiling_run_columns(profiling_run_id: str) -> pd.DataFrame:
    schema: str = st.session_state["dbschema"]
    sql = f"""
    SELECT table_name, column_name
    FROM {schema}.profile_anomaly_results
    WHERE profile_run_id = '{profiling_run_id}'
    ORDER BY table_name, column_name;
    """
    return db.retrieve_data(sql)


@st.cache_data(show_spinner=False)
def get_profiling_anomalies(
    profile_run_id: str,
    likelihood: str | None = None,
    issue_type_id: str | None = None,
    table_name: str | None = None,
    column_name: str | None = None,
    sorting_columns: list[str] | None = None,
):
    db_session = get_current_session()
    criteria = ""
    order_by = ""
    params = {"profile_run_id": profile_run_id}

    if likelihood:
        criteria += " AND t.issue_likelihood = :likelihood"
        params["likelihood"] = likelihood
    if issue_type_id:
        criteria += " AND t.id = :issue_type_id"
        params["issue_type_id"] = issue_type_id
    if table_name:
        criteria += " AND r.table_name = :table_name"
        params["table_name"] = table_name
    if column_name:
        criteria += " AND r.column_name ILIKE :column_name"
        params["column_name"] = column_name

    if sorting_columns:
        order_by = "ORDER BY " + (", ".join(" ".join(col) for col in sorting_columns))

    # Define the query -- first visible column must be first, because will hold the multi-select box
    str_sql = f"""
    SELECT
        r.table_name,
        r.column_name,
        r.schema_name,
        r.column_type,
        t.anomaly_name,
        t.issue_likelihood,
        r.disposition,
        null as action,
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
        t.anomaly_description,
        r.detail,
        t.suggested_action,
        r.anomaly_id,
        r.table_groups_id::VARCHAR,
        r.id::VARCHAR,
        p.profiling_starttime,
        r.profile_run_id::VARCHAR,
        tg.table_groups_name,

        -- These are used in the PDF report
        dcc.functional_data_type,
        dcc.description as column_description,
        COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
        COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
        COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
        COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
        COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
        COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
        COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
        COALESCE(dcc.aggregation_level, dtc.aggregation_level) as aggregation_level,
        COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product

    FROM profile_anomaly_results r
    INNER JOIN profile_anomaly_types t
        ON r.anomaly_id = t.id
    INNER JOIN profiling_runs p
        ON r.profile_run_id = p.id
    INNER JOIN table_groups tg
        ON r.table_groups_id = tg.id
    LEFT JOIN data_column_chars dcc
        ON (tg.id = dcc.table_groups_id
        AND  r.schema_name = dcc.schema_name
        AND  r.table_name = dcc.table_name
        AND  r.column_name = dcc.column_name)
    LEFT JOIN data_table_chars dtc
        ON dcc.table_id = dtc.table_id
    WHERE r.profile_run_id = :profile_run_id
        {criteria}
    {order_by}
    """

    results = db_session.execute(str_sql, params=params)
    columns = [column.name for column in results.cursor.description]

    df = pd.DataFrame(list(results), columns=columns)
    dct_replace = {"Confirmed": "✓", "Dismissed": "✘", "Inactive": "🔇"}
    df["action"] = df["disposition"].replace(dct_replace)

    return df


@st.cache_data(show_spinner=False)
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


def get_excel_report_data(
    update_progress: PROGRESS_UPDATE_TYPE,
    table_group: str,
    run_date: str,
    run_id: str,
    data: pd.DataFrame | None = None,
) -> FILE_DATA_TYPE:
    if data is None:
        data = get_profiling_anomalies(run_id)

    columns = {
        "schema_name": {"header": "Schema"},
        "table_name": {"header": "Table"},
        "column_name": {"header": "Column"},
        "anomaly_name": {"header": "Issue name"},
        "issue_likelihood": {"header": "Likelihood"},
        "anomaly_description": {"header": "Description", "wrap": True},
        "action": {},
        "detail": {},
        "suggested_action": {"wrap": True},
    }
    return get_excel_file_data(
        data,
        "Hygiene Issues",
        details={"Table group": table_group, "Profiling run date": run_date},
        columns=columns,
        update_progress=update_progress,
    )


@st.cache_data(show_spinner=False)
def get_source_data(hi_data, limit):
    return get_source_data_uncached(hi_data, limit)


@st.dialog(title="Source Data")
def source_data_dialog(selected_row):
    st.markdown(f"#### {selected_row['anomaly_name']}")
    st.caption(selected_row["anomaly_description"])
    fm.show_prompt(f"Column: {selected_row['column_name']}, Table: {selected_row['table_name']}")

    # Show the detail line
    fm.render_html_list(selected_row, ["detail"], None, 700, ["Hygiene Issue Detail"])

    with st.spinner("Retrieving source data..."):
        bad_data_status, bad_data_msg, _, df_bad = get_source_data(selected_row, limit=500)
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
        df_bad.fillna("<null>", inplace=True)
        if len(df_bad) == 500:
            testgen.caption("* Top 500 records displayed", "text-align: right;")
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
