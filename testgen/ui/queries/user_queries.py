import streamlit as st

import testgen.ui.services.database_service as db
from testgen.common.encrypt import encrypt_ui_password


@st.cache_data(show_spinner=False)
def get_users():
    schema: str = st.session_state["dbschema"]
    sql = f"""SELECT
                    id::VARCHAR(50),
                    username, email, "name", "password", preauthorized, role
                FROM {schema}.auth_users"""
    return db.retrieve_data(sql)


def delete_users(user_ids):
    if user_ids is None or len(user_ids) == 0:
        raise ValueError("No user is specified.")

    schema: str = st.session_state["dbschema"]
    items = [f"'{item}'" for item in user_ids]
    sql = f"""DELETE FROM {schema}.auth_users WHERE id in ({",".join(items)})"""
    db.execute_sql(sql)
    st.cache_data.clear()


def add_user(user):
    schema: str = st.session_state["dbschema"]
    encrypted_password = encrypt_ui_password(user["password"])
    sql = f"""INSERT INTO {schema}.auth_users
    (username, email, name, password, role)
SELECT
    '{user["username"]}' as username,
    '{user["email"]}' as email,
    '{user["name"]}' as name,
    '{encrypted_password}' as password,
    '{user["role"]}' as role;"""
    db.execute_sql(sql)
    st.cache_data.clear()


def edit_user(user):
    schema: str = st.session_state["dbschema"]
    encrypted_password = encrypt_ui_password(user["password"])
    sql = f"""UPDATE {schema}.auth_users SET
        username = '{user["username"]}',
        email = '{user["email"]}',
        name = '{user["name"]}',
        password = '{encrypted_password}',
        role = '{user["role"]}'
    WHERE id  = '{user["user_id"]}';"""
    db.execute_sql(sql)
    st.cache_data.clear()
