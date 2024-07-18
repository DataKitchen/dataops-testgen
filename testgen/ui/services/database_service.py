from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text

from testgen.common.credentials import (
    get_tg_db,
    get_tg_host,
    get_tg_password,
    get_tg_port,
    get_tg_schema,
    get_tg_username,
)
from testgen.common.database.database_service import get_flavor_service
from testgen.common.encrypt import DecryptText

"""
 Shared database access and utility functions
"""


def get_schema():
    return get_tg_schema()


def _start_engine():
    # TestGen database
    dbhost = get_tg_host()
    dbport = get_tg_port()
    dbname = get_tg_db()
    # User Information
    dbuser = get_tg_username()
    dbpw = get_tg_password()

    conn_str = "postgresql://" + dbuser + ":" + quote_plus(dbpw) + "@" + dbhost + ":" + dbport + "/" + dbname
    return create_engine(conn_str)


def _make_connection():
    engine = _start_engine()
    return engine


def make_header_db_friendly(str_header):
    return str_header.replace(" ", "_").lower()


def make_value_db_friendly(value):
    if value is None or pd.isna(value):
        newval = "NULL"
    else:
        newval = str(value) if isinstance(value, int | float) else f"'{value}'"
    return newval


def retrieve_data(str_sql):
    tg_engine = _start_engine()
    # Retrieve data from Postgres
    return pd.read_sql_query(str_sql, tg_engine)


def retrieve_data_list(str_sql):
    tg_engine = _start_engine()
    # Retrieve data from Postgres
    with tg_engine.connect() as con:
        return con.execute(text(str_sql)).fetchall()


def retrieve_single_result(str_sql):
    tg_engine = _start_engine()
    with tg_engine.connect() as con:
        lstResult = con.execute(text(str_sql)).fetchone()
        if lstResult:
            return lstResult[0]


def execute_sql(str_sql):
    if str_sql > "":
        tg_engine = _start_engine()
        tg_engine.execute(text(str_sql))


def execute_sql_raw(str_sql):
    # For special cases where SQLAlchemy can't handle query syntax
    if str_sql > "":
        tg_engine = _start_engine()
        con = tg_engine.raw_connection()
        with con.cursor() as cur:
            cur.execute(str_sql)
        con.commit()


def _get_df_edits(df_original: pd.DataFrame, df_edited: pd.DataFrame, lst_id_columns: list) -> tuple:
    # Rows in df_edited that exist in df_original but have had any column changed
    #  based on composite ID columns

    # Merge the two dataframes based on the composite ID columns
    merged_df = df_edited.merge(df_original, on=lst_id_columns, how="outer", indicator=True, suffixes=("", "_original"))
    # Filter the merged dataframe to only keep rows that are changed
    # Step 1: Filter rows that exist in both dataframes
    both_rows = merged_df[merged_df["_merge"] == "both"]

    # Step 2: Identify changed rows
    def has_changes(row):
        for col in df_original.columns:
            # Skip the ID columns
            if col in lst_id_columns:
                continue
            if row[col] != row[col + "_original"]:
                return True
        return False

    changed_rows_mask = both_rows.apply(has_changes, axis=1)

    # Step 3: Combine the filters
    changed_rows = both_rows[changed_rows_mask]

    # All rows in df_edited that are newly created and don't exist in df_original
    new_rows = merged_df[merged_df["_merge"] == "left_only"].drop(
        columns=["_merge"] + [col + "_original" for col in df_original.columns if col not in lst_id_columns]
    )

    # All rows in df_original that have been deleted from df_edited
    deleted_rows = merged_df[merged_df["_merge"] == "right_only"][df_original.columns]

    return changed_rows, new_rows, deleted_rows


def _gen_df_update_sql(
    changed_rows: pd.DataFrame, table_name: str, lst_id_columns: list, no_update_columns: list
) -> list:
    # Generate a list of SQL UPDATE statements based on the changed rows.

    # Extract the original column names by removing the "_original" suffix
    original_columns = [col.replace("_original", "") for col in changed_rows.columns if col.endswith("_original")]
    # Drop columns we aren't updating from list
    update_columns = [col for col in original_columns if col not in no_update_columns]

    # Generate SQL UPDATE statements
    sql_statements = []
    for _, row in changed_rows.iterrows():
        set_statements = []
        for col in update_columns:
            # If the value is different from the original value
            if row[col] != row[col + "_original"]:
                value = make_value_db_friendly(row[col])
                set_statements.append(f"{col} = {value}")

        # Handle composite keys for the WHERE clause
        where_statements = []
        for col in lst_id_columns:
            value = make_value_db_friendly(row[col])
            # value = f"'{row[col]}'" if isinstance(row[col], str) else row[col]
            where_statements.append(f"{col} = {value}")

        update_statement = f"UPDATE {get_schema()}.{table_name} SET {', '.join(set_statements)} WHERE {' AND '.join(where_statements)};"
        sql_statements.append(update_statement)

    return sql_statements


def _gen_df_delete_sql(deleted_rows: pd.DataFrame, table_name: str, lst_id_columns: list) -> list:
    # Generate a list of SQL DELETE statements based on the deleted rows.

    # Generate SQL DELETE statements
    sql_statements = []
    for _, row in deleted_rows.iterrows():
        # Handle composite keys for the WHERE clause
        where_statements = []
        for col in lst_id_columns:
            value = make_value_db_friendly(row[col])
            # value = f"'{row[col]}'" if isinstance(row[col], str) else row[col]
            where_statements.append(f"{col} = {value}")

        delete_statement = f"DELETE FROM {get_schema()}.{table_name} WHERE {' AND '.join(where_statements)};"
        sql_statements.append(delete_statement)

    return sql_statements


def _gen_insert_sql(
    new_rows: pd.DataFrame,
    table_name: str,
    lst_id_columns: list,
    no_update_columns: list,
    dct_hard_default_columns: dict,
) -> str:
    # Generate a SQL INSERT statement for the new rows, ensuring strings are properly quoted.

    # Remove the id column as it will be generated by the server
    if lst_id_columns:
        new_rows = new_rows.drop(columns=lst_id_columns)
    if no_update_columns:
        # Remove columns we aren't updating
        new_rows = new_rows.drop(columns=no_update_columns)
    if dct_hard_default_columns:
        # Add and default all columns
        new_rows = new_rows.assign(**dct_hard_default_columns)

    # Generate column names and values for the INSERT statement
    columns = ", ".join(new_rows.columns)

    # Ensure strings are quoted
    values = []
    for _, row in new_rows.iterrows():
        row_values = []
        for val in row:
            row_values.append(make_value_db_friendly(val))
            # if isinstance(val, str):
            #     row_values.append(f"'{val}'")
            # else:
            #     row_values.append(str(val))
        values.append(f"({', '.join(row_values)})")

    if values:
        values_str = ", ".join(values)
        # Construct the SQL INSERT statement
        sql_statement = f"INSERT INTO {get_schema()}.{table_name} ({columns}) VALUES {values_str};"
        return sql_statement


def apply_df_edits(df_original, df_edited, str_table, lst_id_columns, no_update_columns, dct_hard_default_columns):
    booStatus = False
    df_changed, df_new, df_deleted = _get_df_edits(df_original, df_edited, lst_id_columns)

    # Generate SQL UPDATE statements
    lst_update_SQL = _gen_df_update_sql(df_changed, str_table, lst_id_columns, no_update_columns)
    if lst_update_SQL:
        for str_sql in lst_update_SQL:
            execute_sql(str_sql)
            booStatus = True
    # Generate SQL DELETE statements
    lst_delete_SQL = _gen_df_delete_sql(df_deleted, str_table, lst_id_columns)
    if lst_delete_SQL:
        for str_sql in lst_delete_SQL:
            execute_sql(str_sql)
            booStatus = True
    # Generate SQL INSERT statements
    str_insert_sql = _gen_insert_sql(df_new, str_table, lst_id_columns, no_update_columns, dct_hard_default_columns)
    if str_insert_sql:
        execute_sql(str_insert_sql)
        booStatus = True

    return booStatus


def _start_target_db_engine(flavor, host, port, db_name, user, password, url, connect_by_url, connect_by_key, private_key, private_key_passphrase):
    connection_params = {
        "flavor": flavor if flavor != "redshift" else "postgresql",
        "user": user,
        "host": host,
        "port": port,
        "dbname": db_name,
        "url": url,
        "connect_by_url": connect_by_url,
        "connect_by_key": connect_by_key,
        "private_key": private_key,
        "private_key_passphrase": private_key_passphrase,
        "dbschema": None,
    }
    flavor_service = get_flavor_service(flavor)
    flavor_service.init(connection_params)
    connection_string = flavor_service.get_connection_string(password)
    connect_args = {"connect_timeout": 3600}
    connect_args.update(flavor_service.get_connect_args())
    return create_engine(connection_string, connect_args=connect_args)


def retrieve_target_db_data(flavor, host, port, db_name, user, password, url, connect_by_url, connect_by_key, private_key, private_key_passphrase, sql_query, decrypt=False):
    if decrypt:
        password = DecryptText(password)
    db_engine = _start_target_db_engine(flavor, host, port, db_name, user, password, url, connect_by_url, connect_by_key, private_key, private_key_passphrase)
    with db_engine.connect() as connection:
        query_result = connection.execute(text(sql_query))
        return query_result.fetchall()


def retrieve_target_db_df(flavor, host, port, db_name, user, password, sql_query, url, connect_by_url, connect_by_key, private_key, private_key_passphrase):
    if password:
        password = DecryptText(password)
    db_engine = _start_target_db_engine(flavor, host, port, db_name, user, password, url, connect_by_url, connect_by_key, private_key, private_key_passphrase)
    return pd.read_sql_query(text(sql_query), db_engine)
