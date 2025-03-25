import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
from testgen.ui.components import widgets as testgen


@st.dialog(title="Data Preview")
def data_preview_dialog(
    table_group_id: str,
    schema_name: str,
    table_name: str,
    column_name: str | None = None,
) -> None:
    testgen.css_class("s-dialog" if column_name else "xl-dialog")

    testgen.caption(
        f"Table > Column: <b>{table_name} > {column_name}</b>"
        if column_name else
        f"Table: <b>{table_name}</b>"
    )

    data = get_preview_data(table_group_id, schema_name, table_name, column_name)

    if data.empty:
        st.warning("The preview data could not be loaded.")
    else:
        st.dataframe(
            data,
            width=520 if column_name else None,
            height=700,
        )


@st.cache_data(show_spinner="Loading data ...")
def get_preview_data(
    table_group_id: str,
    schema_name: str,
    table_name: str,
    column_name: str | None = None,
) -> pd.DataFrame:
    tg_schema = st.session_state["dbschema"]
    connection_query=f"""
    SELECT
        c.sql_flavor,
        c.project_host,
        c.project_port,
        c.project_db,
        c.project_user,
        c.project_pw_encrypted,
        c.url,
        c.connect_by_url,
        c.connect_by_key,
        c.private_key,
        c.private_key_passphrase,
        c.http_path
    FROM {tg_schema}.table_groups tg
        INNER JOIN {tg_schema}.connections c ON (
            tg.connection_id = c.connection_id
        )
    WHERE tg.id = '{table_group_id}';
    """
    connection_df = db.retrieve_data(connection_query).iloc[0]

    if not connection_df.empty:
        query = f"""
        SELECT
            {column_name or "*"}
        FROM {schema_name}.{table_name}
        LIMIT 100
        """

        df = db.retrieve_target_db_df(
            connection_df["sql_flavor"],
            connection_df["project_host"],
            connection_df["project_port"],
            connection_df["project_db"],
            connection_df["project_user"],
            connection_df["project_pw_encrypted"],
            query,
            connection_df["url"],
            connection_df["connect_by_url"],
            connection_df["connect_by_key"],
            connection_df["private_key"],
            connection_df["private_key_passphrase"],
            connection_df["http_path"],
        )
        df.index = df.index + 1
        return df
    else:
        return pd.DataFrame()
