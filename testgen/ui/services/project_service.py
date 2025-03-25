import streamlit as st

from testgen.ui.navigation.router import Router
from testgen.ui.queries import project_queries
from testgen.ui.services import database_service, query_service
from testgen.ui.session import session


@st.cache_data(show_spinner=False)
def get_projects():
    projects = project_queries.get_projects()
    projects = [
        {"code": project["project_code"], "name": project["project_name"]} for project in projects.to_dict("records")
    ]

    return projects


def set_current_project(project_code: str) -> None:
    session.project = project_code
    Router().set_query_params({ "project_code": project_code })


@st.cache_data(show_spinner=False)
def get_project_by_code(code: str):
    if not code:
        return None
    return query_service.get_project_by_code(session.dbschema, code)


def edit_project(project: dict):
    schema = st.session_state["dbschema"]
    query = f"""
    UPDATE {schema}.projects
    SET
        project_name = '{project["project_name"]}',
        observability_api_url = '{project["observability_api_url"]}',
        observability_api_key = '{project["observability_api_key"]}'
    WHERE id = '{project["id"]}';
    """
    database_service.execute_sql(query)
    st.cache_data.clear()
