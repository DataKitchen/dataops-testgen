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
):
    """Wrapping a dialog and a download button together to allow generating the file contents only when needed."""

    def _dialog_content():

        with st.container(height=70, border=False):
            p_bar = st.progress(0.0, progress_bar_msg)

        with st.container(height=55, border=False):
            _, button_col, _ = st.columns([.3, .4, .3])

        def _get_progress_gen():
            while True:
                progress = yield
                p_bar.progress(progress, progress_bar_msg)

        file_name, file_type, file_content = file_content_func(_get_progress_gen(), *args)

        p_bar.progress(1.0, "Done!")

        with button_col:
            st.download_button(
                label=":material/download: Download",
                data=file_content,
                file_name=file_name,
                mime=file_type,
                use_container_width=True,
            )

    return st.dialog(title=dialog_title, width="small")(_dialog_content)()
