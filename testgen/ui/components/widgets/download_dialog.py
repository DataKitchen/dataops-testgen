from collections.abc import Callable
from typing import Any

import streamlit as st


def download_dialog(
    dialog_title: str,
    file_name: str,
    mime_type: str,
    file_content_func: Callable[[], Any],
):
    """Wrapping a dialog and a download button together to allow generating the file contents only when needed."""

    def _dialog_content():
        # Encapsulating the dialog content in a container just to force its height and avoid the dialog to
        # have its height changed when the button is rendered.
        with st.container(height=55, border=False):
            spinner_col, button_col, _ = st.columns([.3, .4, .3])

        with spinner_col:
            with st.spinner(text="Generating file..."):
                data = file_content_func()

        with button_col:
            st.download_button(
                label=":material/download: Download",
                data=data,
                file_name=file_name,
                mime=mime_type,
                use_container_width=True
            )

    return st.dialog(title=dialog_title, width="small")(_dialog_content)()
