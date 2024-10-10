import tempfile
from collections.abc import Callable, Generator, Iterable
from zipfile import ZipFile

import streamlit as st


def zip_multi_file_data(
    zip_file_name: str,
    file_data_func: Callable[[Generator, ...], tuple[str, str, str|bytes]],
    args_list: list[Iterable],
):

    def _file_content_func(progress_gen, *args):

        progress = 0.0
        step = 1.0 / len(args_list)

        def _file_gen():
            while True:
                f_progress = yield
                progress_gen.send(progress + step / f_progress)

        with tempfile.NamedTemporaryFile() as zip_file:
            with ZipFile(zip_file.name, "w") as zip_writer:
                progress_gen.send(None)
                for args in args_list:
                    file_name, _, file_data = file_data_func(_file_gen(), *args)
                    zip_writer.writestr(file_name, file_data)
                    progress += step
            zip_content = zip_file.read()

        return zip_file_name, "application/zip", zip_content

    return _file_content_func


def download_dialog(
    dialog_title: str,
    file_content_func: Callable[[Generator, ...], tuple[str, str, str|bytes]],
    args: Iterable = (),
    progress_bar_msg: str = "Generating file...",
    key: str = "download_dialog",
):
    """Wrapping a dialog and a download button together to allow generating the file contents only when needed."""

    file_ready_key = f"{key}:file_ready"

    def _dialog_content():

        with st.container(height=70, border=False):
            p_bar = st.progress(0.0, progress_bar_msg)

        with st.container(height=55, border=False):
            _, button_col = st.columns([.8, .2])

        # The goal of this `file_ready` state is to prevent the file to be generated again after the user clicks
        # the download button. Streamlit's way to close a dialog is to hit st.rerun(), which we should call when
        # we get True from the download button being pushed, however it has to be rendered again for that, which
        # means the file will be generated again. To avoid that, we simply call st.rerun() BEFORE generating the
        # file, based on this session state. The drawback is that the dialog will unexpectedly close once by the
        # next time it is opened after being closed by the user before "Download" is clicked.
        if st.session_state.get(file_ready_key):
            del st.session_state[file_ready_key]
            st.rerun()

        def _get_progress_gen():
            while True:
                progress = yield
                p_bar.progress(progress, progress_bar_msg)

        file_name, file_type, file_content = file_content_func(_get_progress_gen(), *args)

        p_bar.progress(1.0, "File ready for download.")
        st.session_state[file_ready_key] = True

        with button_col:
            st.download_button(
                label=":material/download: Download",
                data=file_content,
                file_name=file_name,
                mime=file_type,
                use_container_width=True,
            )

    return st.dialog(title=dialog_title, width="small")(_dialog_content)()
