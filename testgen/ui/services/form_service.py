import streamlit as st


def reset_post_updates(str_message=None, as_toast=False, style="success"):
    if str_message:
        if as_toast:
            st.toast(str_message)
        elif style in ("error", "warning", "info", "success"):
            getattr(st, style)(str_message)
        else:
            st.success(str_message)
