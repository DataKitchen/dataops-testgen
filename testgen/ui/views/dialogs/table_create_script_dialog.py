def generate_create_script(table_name: str, data: list[dict]) -> str | None:
    table_data = [col for col in data if col["table_name"] == table_name]
    if not table_data:
        return None

    max_name = max(len(col["column_name"]) for col in table_data) + 3
    max_type = max(len(col["datatype_suggestion"] or "") for col in table_data) + 3

    col_defs = []
    for index, col in enumerate(table_data):
        comment = (
            f"-- WAS {col['db_data_type']}"
            if isinstance(col["db_data_type"], str)
            and isinstance(col["datatype_suggestion"], str)
            and col["db_data_type"].lower() != col["datatype_suggestion"].lower()
            else ""
        )
        col_type = col["datatype_suggestion"] or col["db_data_type"] or ""
        separator = " " if index == len(table_data) - 1 else ","
        col_defs.append(f"{col['column_name']:<{max_name}} {(col_type):<{max_type}}{separator}    {comment}")

    col_defs_joined = "\n    ".join(col_defs)
    return f"""
CREATE TABLE {table_data[0]['schema_name']}.{table_data[0]['table_name']} (
    {col_defs_joined}
);"""
