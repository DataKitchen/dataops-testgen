import tempfile
from collections.abc import Callable, Iterable
from zipfile import ZipFile

import streamlit as st

PROGRESS_UPDATE_TYPE = Callable[[float], None]

FILE_DATA_TYPE = tuple[str, str, str|bytes]

def zip_multi_file_data(
    zip_file_name: str,
    file_data_func: Callable[[PROGRESS_UPDATE_TYPE, ...], FILE_DATA_TYPE],
    args_list: list[Iterable],
) -> Callable[[PROGRESS_UPDATE_TYPE, ...], FILE_DATA_TYPE]:

    def _file_content_func(update_main_progress, *args):

        progress = 0.0
        step = 1.0 / len(args_list)

        def _update_progress(f_progress):
            update_main_progress(progress + step * f_progress)

        with tempfile.NamedTemporaryFile() as zip_file:
            with ZipFile(zip_file.name, "w") as zip_writer:
                for args in args_list:
                    file_name, _, file_data = file_data_func(_update_progress, *args)
                    zip_writer.writestr(file_name, file_data)
                    progress += step
            zip_content = zip_file.read()

        return zip_file_name, "application/zip", zip_content

    return _file_content_func


def download_dialog(
    dialog_title: str,
    file_content_func: Callable[[PROGRESS_UPDATE_TYPE, ...], FILE_DATA_TYPE],
    args: Iterable = (),
    progress_bar_msg: str = "Generating file...",
):
    """Wrapping a dialog and a download button together to allow generating the file contents only when needed."""

    def _dialog_content():

        with st.container(height=70, border=False):
            p_bar = st.progress(0.0, progress_bar_msg)

        with st.container(height=55, border=False):
            _, button_col = st.columns([.8, .2])

        def _update_progress(progress: float):
            p_bar.progress(progress, progress_bar_msg)

        file_name, file_type, file_content = file_content_func(_update_progress, *args)

        p_bar.progress(1.0, "File ready for download.")

        @st.fragment
        def render_button():
            if st.download_button(
                label=":material/download: Download",
                data=file_content,
                file_name=file_name,
                mime=file_type,
                use_container_width=True,
            ):
                st.rerun()

        with button_col:
            render_button()

    return st.dialog(title=dialog_title, width="small")(_dialog_content)()
