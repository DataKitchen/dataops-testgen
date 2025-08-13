import pandas as pd
import streamlit as st

from testgen.common.models.connection import Connection
from testgen.ui.components import widgets as testgen
from testgen.ui.services.database_service import fetch_from_target_db
from testgen.utils import to_dataframe


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

    with st.spinner("Loading data ..."):
        data = get_preview_data(table_group_id, schema_name, table_name, column_name)

    if data.empty:
        st.warning("The preview data could not be loaded.")
    else:
        st.dataframe(
            data,
            width=520 if column_name else None,
            height=700,
        )


@st.cache_data(show_spinner=False)
def get_preview_data(
    table_group_id: str,
    schema_name: str,
    table_name: str,
    column_name: str | None = None,
) -> pd.DataFrame:
    connection = Connection.get_by_table_group(table_group_id)

    if connection:
        use_top = connection.sql_flavor == "mssql"
        query = f"""
        SELECT DISTINCT
            {"TOP 100" if use_top else ""}
            {column_name or "*"}
        FROM {schema_name}.{table_name}
        {"LIMIT 100" if not use_top else ""}
        """

        try:
            results = fetch_from_target_db(connection, query)
        except:
            return pd.DataFrame()
        else:
            df = to_dataframe(results)
            df.index = df.index + 1
            df.fillna("<null>", inplace=True)
            return df
    else:
        return pd.DataFrame()
