import pandas as pd
import streamlit as st

from testgen.common.database.database_service import get_flavor_service
from testgen.common.models.connection import Connection
from testgen.common.pii_masking import get_pii_columns, mask_source_data_pii
from testgen.ui.components import widgets as testgen
from testgen.ui.services.database_service import fetch_from_target_db
from testgen.ui.session import session
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

    if not data.empty and not session.auth.user_has_permission("view_pii"):
        pii_columns = get_pii_columns(table_group_id, schema_name, table_name)
        mask_source_data_pii(data, pii_columns)

    if data.empty:
        st.warning("The preview data could not be loaded.")
    else:
        st.dataframe(
            data,
            width=520 if column_name else "content",
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
        flavor_service = get_flavor_service(connection.sql_flavor)
        row_limiting = flavor_service.row_limiting_clause
        quote = flavor_service.quote_character
        query = f"""
        SELECT DISTINCT
            {"TOP 100" if row_limiting == "top" else ""}
            {f"{quote}{column_name}{quote}" if column_name else "*"}
        FROM {quote}{schema_name}{quote}.{quote}{table_name}{quote}
        {"LIMIT 100" if row_limiting == "limit" else ""}
        {"FETCH FIRST 100 ROWS ONLY" if row_limiting == "fetch" else ""}
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
