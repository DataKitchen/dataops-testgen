import streamlit as st

import testgen.ui.services.query_service as query_service


@st.cache_data(show_spinner=False)
def get_projects():
    str_schema = st.session_state["dbschema"]
    return query_service.run_project_lookup_query(str_schema)
