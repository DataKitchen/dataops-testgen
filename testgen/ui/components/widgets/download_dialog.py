import tempfile
from collections.abc import Callable, Iterable
from io import BytesIO
from typing import TypedDict
from zipfile import ZipFile

import pandas as pd
import streamlit as st

from testgen.common import date_service

PROGRESS_UPDATE_TYPE = Callable[[float], None]

FILE_DATA_TYPE = tuple[str, str, str | bytes]


class ExcelColumnOptions(TypedDict):
    header: str
    wrap: bool


def get_excel_file_data(
    data: pd.DataFrame,
    title: str,
    details: dict[str, str] | None = None,
    columns: dict[str, ExcelColumnOptions] | None = None,
    update_progress: PROGRESS_UPDATE_TYPE | None = None,
) -> FILE_DATA_TYPE:
    if not columns:
        columns = { col: {} for col in data.columns }

    filtered_data = data[columns.keys()]
    start_row = 4 + len(details or {})

    with BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            # Data
            filtered_data.to_excel(writer, index=False, sheet_name="Sheet1", startrow=start_row)

            workbook = writer.book
            worksheet = writer.sheets["Sheet1"]
            worksheet.set_column(0, 1000, None, workbook.add_format({"valign": "top"}))
            worksheet.autofit()

            # Title
            worksheet.write(
                "A2",
                title,
                workbook.add_format({"bold": True, "size": 14}),
            )

            details_key_format = workbook.add_format({"size": 9})
            details_value_format = workbook.add_format({"italic": True, "size": 9})
            
            # Timestamp
            worksheet.write("A3", "Exported on", details_key_format)
            worksheet.write("B3", date_service.get_timezoned_now(st.session_state), details_value_format)

            # Details
            if details:
                for index, (key, value) in enumerate(details.items()):
                    worksheet.write(f"A{4 + index}", key, details_key_format)
                    worksheet.write(f"B{4 + index}", value, details_value_format)

            # Headers + table style
            (max_row, max_col) = filtered_data.shape
            headers = [
                {"header": options.get("header", key.replace("_", " ").capitalize())}
                for key, options in columns.items()
            ]
            worksheet.add_table(
                start_row,
                0,
                max_row + start_row,
                max_col - 1,
                {"columns": headers, "style": "Table Style Medium 16"},
            )

            # Wrap columns
            wrap_format = workbook.add_format({"text_wrap": True, "valign": "top"})
            for index, options in enumerate(columns.values()):
                if options.get("wrap"):
                    worksheet.set_column(index, index, 60, wrap_format)

        if update_progress:
            update_progress(1.0)      
        buffer.seek(0)
        return f"{title}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer.getvalue()


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
