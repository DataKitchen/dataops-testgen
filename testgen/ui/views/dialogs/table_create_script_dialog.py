import streamlit as st

from testgen.ui.components import widgets as testgen


@st.dialog(title="Table CREATE Script with Suggested Data Types")
def table_create_script_dialog(table_name: str, data: list[dict]) -> None:
    testgen.caption(f"Table: <b>{table_name}</b>")
    st.code(generate_create_script(table_name, data), "sql")


def generate_create_script(table_name: str, data: list[dict]) -> str | None:
    table_data = [col for col in data if col["table_name"] == table_name]
    if not table_data:
        return None
    
    max_name = max(len(col["column_name"]) for col in table_data) + 3
    max_type = max(len(col["datatype_suggestion"] or "") for col in table_data) + 3

    col_defs = []
    for index, col in enumerate(table_data):
        comment = (
            f"-- WAS {col['column_type']}"
            if isinstance(col["column_type"], str)
            and isinstance(col["datatype_suggestion"], str)
            and col["column_type"].lower() != col["datatype_suggestion"].lower()
            else ""
        )
        col_type = col["datatype_suggestion"] or col["column_type"] or ""
        separator = " " if index == len(table_data) - 1 else ","
        col_defs.append(f"{col['column_name']:<{max_name}} {(col_type):<{max_type}}{separator}    {comment}")

    return f"""
CREATE TABLE {table_data[0]['schema_name']}.{table_data[0]['table_name']} (
    {"\n    ".join(col_defs)}
);"""
