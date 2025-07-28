import pandas as pd
import streamlit as st

from testgen.ui.components import widgets as testgen


@st.dialog(title="Table CREATE Script with Suggested Data Types")
def table_create_script_dialog(table_name: str, data: pd.DataFrame) -> None:
    testgen.caption(
        f"Table: <b>{table_name}</b>"
    )
    st.code(generate_create_script(table_name, data), "sql")


def generate_create_script(table_name: str, data: pd.DataFrame) -> str:
    df = data[data["table_name"] == table_name][["schema_name", "table_name", "column_name", "column_type", "datatype_suggestion"]]
    df = df.copy().reset_index(drop=True)
    df.fillna("", inplace=True)

    df["comment"] = df.apply(
        lambda row: f"-- WAS {row['column_type']}"
        if isinstance(row["column_type"], str)
        and isinstance(row["datatype_suggestion"], str)
        and row["column_type"].lower() != row["datatype_suggestion"].lower()
        else "",
        axis=1,
    )
    max_len_name = df.apply(lambda row: len(row["column_name"]), axis=1).max() + 3
    max_len_type = df.apply(lambda row: len(row["datatype_suggestion"]), axis=1).max() + 3

    header = f"CREATE TABLE {df.at[0, 'schema_name']}.{df.at[0, 'table_name']} ( "
    col_defs = df.apply(
        lambda row: f"     {row['column_name']:<{max_len_name}} {row['datatype_suggestion']:<{max_len_type}},    {row['comment']}",
        axis=1,
    ).tolist()
    footer = ");"
    col_defs[-1] = col_defs[-1].replace(",    --", "    --")

    return "\n".join([header, *list(col_defs), footer])
