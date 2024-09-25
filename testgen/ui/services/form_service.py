# For render_logo
import base64
import typing
from builtins import float
from datetime import date, datetime, time
from enum import Enum
from io import BytesIO
from os.path import splitext
from pathlib import Path
from time import sleep

import pandas as pd
import streamlit as st
import validators
from pandas.api.types import is_datetime64_any_dtype
from st_aggrid import AgGrid, ColumnsAutoSizeMode, DataReturnMode, GridOptionsBuilder, GridUpdateMode, JsCode
from streamlit_extras.no_default_selectbox import selectbox

import testgen.common.date_service as date_service
import testgen.ui.services.authentication_service as authentication_service
import testgen.ui.services.database_service as db

"""
Shared rendering of UI elements
"""

logo_file = (Path(__file__).parent.parent / "assets/dk_logo.svg").as_posix()
help_icon = (Path(__file__).parent.parent / "assets/question_mark.png").as_posix()


class FormWidget(Enum):
    text_md = 1
    text_input = 2
    text_area = 3
    number_input = 4
    selectbox = 5
    date_input = 6
    radio = 7
    checkbox = 8
    multiselect = 9  # TODO: implement
    hidden = 99


class FieldSpec:
    field_label = None
    column_name = None
    widget = None
    value_original = None
    init_value = None
    display_only = False
    required = False
    key_order = 0

    # Entry Options
    max_chars = None
    num_min = None
    num_max = None
    text_multi_lines = 3

    # Selectbox Options
    df_options = None
    show_column_name = None
    return_column_name = None

    # Radio options
    lst_option_text: typing.ClassVar = []
    lst_option_values: typing.ClassVar = []
    show_horizontal = True

    value = None

    def __init__(
        self,
        str_label,
        str_column_name,
        form_widget,
        orig_val=None,
        init_val=None,
        read_only=False,
        required=False,
        int_key=0,
        max_chars=None,
        num_min=None,
        num_max=None,
        text_multi_lines=3,
    ):
        self.field_label = str_label
        self.column_name = str_column_name
        self.value_original = orig_val
        self.init_value = init_val if init_val else orig_val
        self.widget = form_widget
        self.display_only = read_only
        self.required = required
        self.key_order = int_key
        self.max_chars = max_chars
        self.num_min = num_min
        self.num_max = num_max
        self.text_multi_lines = text_multi_lines

    def set_select_choices(self, df_options, str_show_column_name, str_return_column_name):
        if self.widget in [FormWidget.selectbox, FormWidget.multiselect]:
            self.df_options = df_options
            self.show_column_name = str_show_column_name
            self.return_column_name = str_return_column_name
        else:
            raise ValueError(f"Can't set Select Choices for widget {self.widget}")

    def render_widget(self, boo_form_display_only=False):
        # if either form-level or field-level display-only is true, then widget is display-only
        boo_display_only = boo_form_display_only or self.display_only

        match self.widget:
            case FormWidget.text_md:
                st.markdown(f"**{self.field_label}**")
                st.markdown(self.init_value)

            case FormWidget.text_input:
                self.value = st.text_input(
                    label=self.field_label, value=self.init_value, disabled=boo_display_only, max_chars=self.max_chars
                )

            case FormWidget.text_area:
                box_height = 26 * self.text_multi_lines
                self.value = st.text_area(
                    label=self.field_label,
                    value=self.init_value,
                    disabled=boo_display_only,
                    max_chars=self.max_chars,
                    height=box_height,
                )

            case FormWidget.number_input:
                self.value = st.number_input(
                    label=self.field_label,
                    value=self.init_value,
                    min_value=self.num_min,
                    max_value=self.num_max,
                    disabled=boo_display_only,
                )

            case FormWidget.selectbox:
                self.value = render_select(
                    self.field_label,
                    self.df_options,
                    self.show_column_name,
                    not self.return_column_name,
                    self.required,
                    self.init_value,
                    self.display_only,
                )

            case FormWidget.date_input:
                self.value = render_select_date(self.field_label, boo_disabled=boo_display_only)

            case FormWidget.radio:
                # If no init_value, or if init_value is None (NULL), the first value will be selected by default
                self.value = render_radio(
                    self.field_label,
                    self.lst_option_text,
                    self.lst_option_values if self.lst_option_values else self.lst_option_text,
                    self.init_value,
                    boo_display_only,
                    self.show_horizontal,
                )

            case FormWidget.checkbox:
                self.value = render_checkbox(
                    self.field_label, self.lst_option_values, self.init_value, boo_display_only
                )

            case FormWidget.hidden:
                self.value = self.init_value

            case _:
                raise ValueError(f"Widget {self.widget} is not supported.")


@st.cache_data(show_spinner=False)
def _generate_excel_export(
    df_data, lst_export_columns, str_title=None, str_caption=None, lst_wrap_columns=None, lst_column_headers=None
):
    if lst_export_columns:
        # Filter the DataFrame to keep only the columns in lst_export_columns
        df_to_export = df_data[lst_export_columns]
    else:
        lst_export_columns = list(df_data.columns)
        df_to_export = df_data

    dct_col_to_header = dict(zip(lst_export_columns, lst_column_headers, strict=True)) if lst_column_headers else None

    if not str_title:
        str_title = "TestGen Data Export"
    start_row = 4 if str_caption else 3

    # Create a BytesIO buffer to hold the Excel file
    output = BytesIO()

    # Create a Pandas Excel writer using XlsxWriter as the engine
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        # Write the DataFrame to an Excel file, starting from the fourth row
        df_to_export.to_excel(writer, index=False, sheet_name="Sheet1", startrow=start_row)

        # Access the XlsxWriter workbook and worksheet objects from the dataframe
        workbook = writer.book
        worksheet = writer.sheets["Sheet1"]

        # Add table formatting
        (max_row, max_col) = df_to_export.shape
        if dct_col_to_header:
            column_settings = [{"header": dct_col_to_header[column]} for column in df_to_export.columns]
        else:
            column_settings = [{"header": column} for column in df_to_export.columns]
        worksheet.add_table(
            start_row,
            0,
            max_row + start_row,
            max_col - 1,
            {"columns": column_settings, "style": "Table Style Medium 16"},
        )

        # Define the format for wrapped text
        wrap_format = workbook.add_format(
            {
                "text_wrap": True,
                "valign": "top",  # Align to the top to better display wrapped text
            }
        )
        valign_format = workbook.add_format({"valign": "top"})

        # Autofit the worksheet (before adding title or settingwrapped column width)
        worksheet.set_column(0, 1000, None, valign_format)
        worksheet.autofit()

        # Set a fixed column width for wrapped columns and apply wrap format
        approx_width = 60
        for col_idx, column in enumerate(df_to_export[lst_export_columns].columns):
            if column in lst_wrap_columns:
                # Set column width and format for wrapping
                worksheet.set_column(col_idx, col_idx, approx_width, wrap_format)

        # Add a cell format for the title
        title_format = workbook.add_format({"bold": True, "size": 14})
        # Write the title in cell A2 with formatting
        worksheet.write("A2", str_title, title_format)

        if str_caption:
            str_caption = str_caption.replace("{TIMESTAMP}", date_service.get_timezoned_now(st.session_state))
            caption_format = workbook.add_format({"italic": True, "size": 9, "valign": "top"})
            worksheet.write("A3", str_caption, caption_format)

    # Rewind the buffer
    output.seek(0)

    # Return the Excel file
    return output.getvalue()


def render_excel_export(
    df, lst_export_columns, str_export_title=None, str_caption=None, lst_wrap_columns=None, lst_column_headers=None
):

    if st.button(label=":material/download: Export", help="Download to Excel"):
        download_excel(df, lst_export_columns, str_export_title, str_caption, lst_wrap_columns, lst_column_headers)


@st.dialog(title="Download to Excel")
def download_excel(
    df, lst_export_columns, str_export_title=None, str_caption=None, lst_wrap_columns=None, lst_column_headers=None
):
    st.write(f'**Are you sure you want to download "{str_export_title}.xlsx"?**')

    st.download_button(
        label="Download",
        data=_generate_excel_export(
            df, lst_export_columns, str_export_title, str_caption, lst_wrap_columns, lst_column_headers
        ),
        file_name=f"{str_export_title}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

def render_refresh_button(button_container):
    with button_container:
        do_refresh = st.button(":material/refresh:", help="Refresh page data", use_container_width=False)
        if do_refresh:
            reset_post_updates("Refreshing page", True, True)


def show_prompt(str_prompt=None):
    if str_prompt:
        st.markdown(f":blue[{str_prompt}]")


def show_header(str_header=None):
    if str_header:
        st.header(f":green[{str_header}]")


def show_subheader(str_text=None):
    if str_text:
        st.subheader(f":green[{str_text}]")


def _show_section_header(str_section_header=None):
    if str_section_header:
        st.markdown(f":green[**{str_section_header}**]")


def render_form_by_field_specs(
    str_form_name, str_table_name, lst_field_specs, str_text_display=None, boo_display_only=False, str_caption=None
):
    show_header(str_form_name)

    if str_text_display:
        layout_column_1, layout_column_2 = st.columns([0.7, 0.3])
    else:
        layout_column_1, layout_column_2 = st.columns([0.95, 0.05])

    if str_text_display:
        with layout_column_2:
            st.markdown(str_text_display)

    with layout_column_1:
        # Render form
        layout_container = st.container() if boo_display_only else st.form(str_form_name, clear_on_submit=True)
        with layout_container:
            if str_caption:
                st.caption(f":green[{str_caption}]")

            # Render all widgets
            for field in lst_field_specs:
                field.render_widget(boo_display_only)

            submit = (
                False
                if boo_display_only
                else st.form_submit_button("Save Changes", disabled=authentication_service.current_user_has_read_role())
            )

            if submit and not boo_display_only:
                # Process Results
                changes = []
                keys = []

                # Construct SQL UPDATE statement based on the changed values
                lst_field_specs_by_key = sorted(lst_field_specs, key=lambda x: x.key_order)
                for field in lst_field_specs_by_key:
                    if field.key_order > 0:
                        keys.append(f"{field.column_name} = '{field.value}'")
                    elif not field.display_only and field.value is None and field.value_original is not None:
                        changes.append(f"{field.column_name} = NULL")
                    elif not field.display_only and field.value != field.value_original:
                        changes.append(f"{field.column_name} = '{field.value}'")
                # If there are any changes, construct and run the SQL statement
                if changes:
                    str_schema = st.session_state["dbschema"]
                    str_sql = (
                        f"UPDATE {str_schema}.{str_table_name} SET {', '.join(changes)} WHERE {' AND '.join(keys)};"
                    )
                    db.execute_sql(str_sql)
                    reset_post_updates("Changes have been saved.")


def ut_prettify_header(str_header, expand=False):
    # First drop underscores and make title-case
    str_new = str_header.replace("_", " ").title()

    if expand:
        # Second, expand abbreviaqtions
        PRETTY_DICT = {
            " Ct": " Count",
            "Min ": "Minimum ",
            "Max ": "Maximum ",
            "Avg ": "Average ",
            "Std ": "Standard ",
        }
        for old, new in PRETTY_DICT.items():
            str_new = str_new.replace(old, new)

    return str_new


def reset_post_updates(str_message=None, as_toast=False, clear_cache=True, lst_cached_functions=None, style="success"):
    if str_message:
        if as_toast:
            st.toast(str_message)
        elif style in ("error", "warning", "info", "success"):
            getattr(st, style)(str_message)
        else:
            st.success(str_message)
        sleep(1.5)

    if clear_cache:
        if lst_cached_functions:
            for fcn in lst_cached_functions:
                fcn.clear()
        else:
            st.cache_data.clear()
    st.rerun()


def render_select(
    str_label, df_options, str_show_column, str_return_column, boo_required=True, str_default=None, boo_disabled=False
):
    # Assemble conditional arguments for selectbox
    kwargs = {"label": str_label, "options": df_options[str_show_column], "disabled": boo_disabled}
    if str_default:
        # Conditionally select index based on index of default value
        if str_default not in df_options[str_show_column].values:
            message = f"Label: {str_label} - Option: {str_default} not available. Click the refresh button."
            st.markdown(f":orange[{message}]")
        else:
            kwargs["index"] = int(df_options[df_options[str_show_column] == str_default].index[0])
    str_choice_name = st.selectbox(**kwargs) if boo_required else selectbox(**kwargs)
    # Assign return-value from selected show-value
    if str_choice_name:
        return df_options.loc[df_options[str_show_column] == str_choice_name, str_return_column].iloc[0]


def render_select_date(str_label, dt_min_date=None, dt_max_date=None, boo_disabled=False, dt_default=None):
    dt_select = st.date_input(
        label=str_label,
        value=dt_default,
        min_value=dt_min_date,
        max_value=dt_max_date,
        format="YYYY-MM-DD",
        disabled=boo_disabled,
    )
    return dt_select


def render_radio(
    str_label, lst_option_text, lst_option_values=None, init_value=None, boo_disabled=False, boo_horizontal=True
):
    if init_value:
        # Lookup index for init value
        i = next((i for i, x in enumerate(lst_option_values) if x == init_value), -1)
        i = i if i > 0 else 0
    else:
        # If no init_value, or if init_value is None (NULL), the first value will be selected by default
        i = 0
    str_choice_text = st.radio(
        str_label, options=lst_option_text, index=i, disabled=boo_disabled, horizontal=boo_horizontal
    )
    if lst_option_values:
        # Lookup choice -- get value
        i = next((i for i, x in enumerate(lst_option_text) if x == str_choice_text), -1)
        val_select = lst_option_values[i]
    else:
        val_select = str_choice_text

    return val_select


def render_checkbox(str_label, lst_true_false_values, boo_init_state=False, boo_disabled=False):
    boo_value = st.checkbox(str_label, boo_init_state, disabled=boo_disabled)
    return lst_true_false_values[0] if boo_value else lst_true_false_values[1]


def render_html_list(dct_row, lst_columns, str_section_header=None, int_data_width=300, lst_labels=None):
    # Renders sets of values as vertical markdown list

    if str_section_header:
        # Header
        _show_section_header(str_section_header)

    # Subtract the padding-left and right from the width
    if int_data_width > 0:
        int_data_width += -20

    str_block = "block" if int_data_width == 0 else "inline-block"

    str_markdown = """
<style>
  .dk-field-label {
    display: inline-block;
    width: 180px;
    vertical-align: top;
    font-weight: bold;
  }
  .dk-text-value {
    display: <<BLOCK>>;
    width: <<WIDTH>>px;
    background-color: var(--dk-text-value-background);
    text-align: left;
    font-family: 'Courier New', monospace;
    padding-left: 10px;
    padding-right: 10px;
    box-sizing: border-box;
  }
  .dk-num-value {
    display: <<BLOCK>>;
    width: <<WIDTH>>px;
    background-color: var(--dk-text-value-background);
    text-align: right;
    font-family: 'Courier New', monospace;
    padding-left: 10px;
    padding-right: 10px;
    box-sizing: border-box;
  }
</style>
"""
    str_data_width = "100%" if int_data_width == 0 else str(int_data_width)
    str_markdown = str_markdown.replace("<<WIDTH>>", str_data_width)
    str_markdown = str_markdown.replace("<<BLOCK>>", str_block)

    # Prep labels
    if not lst_labels:
        lst_labels = [ut_prettify_header(label, expand=True) for label in lst_columns]

    for col, label in zip(lst_columns, lst_labels, strict=True):
        str_use_class = "num" if type(dct_row[col]) is (int | float) else "text"
        str_markdown += f"""<div><span class="dk-field-label">{label}</span><span class="dk-{str_use_class}-value">{dct_row[col]!s}</span></div>"""

    with st.container():
        st.markdown(str_markdown, unsafe_allow_html=True)
        st.divider()


def render_markdown_list(dct_row, lst_columns, str_header=None):
    # Renders sets of values as vertical markdown list

    str_blank_line = "<br>"  # chr(10) + chr(10)

    if str_header:
        # Header with extra line
        str_markdown = f":green[**{str_header}**]" + str_blank_line
    else:
        str_markdown = ""

    for col in lst_columns:
        # Column:  Value with extra line
        str_markdown += f"**{ut_prettify_header(col)}**:&nbsp;&nbsp;`{dct_row[col]!s}`" + str_blank_line

    # Drop last blank line
    i = str_markdown.rfind(str_blank_line)
    if i != -1:
        str_markdown = str_markdown[:i]

    with st.container():
        st.markdown(str_markdown, unsafe_allow_html=True)
        st.divider()


def render_markdown_table(df, lst_columns):
    # Filter the DataFrame to include only the specified columns

    df_filtered = df[lst_columns]

    # Initialize markdown string
    md_str = ""
    # Add headers
    headers = "|".join([f" {ut_prettify_header(col)} " for col in lst_columns])
    md_str += f"|{headers}|\n"
    # Add alignment row
    alignments = []
    for col in lst_columns:
        if pd.api.types.is_numeric_dtype(df_filtered[col]):
            alignments.append("---:")
        else:
            alignments.append(":---")
    md_str += f"|{'|'.join(alignments)}|\n"

    # Add rows
    for _, row in df_filtered.iterrows():
        row_str = []
        for col in lst_columns:
            if pd.api.types.is_numeric_dtype(df_filtered[col]):
                row_str.append(f" {row[col]} ")
            else:
                row_str.append(f" {row[col]} ")
        md_str += f"|{'|'.join(row_str)}|\n"

    st.markdown(md_str)


def render_column_list(row_selected, lst_columns, str_prompt):
    with st.container():
        show_prompt(str_prompt)

        for column in lst_columns:
            column_type = type(row_selected[column])
            if column_type is str:
                st.text_input(label=ut_prettify_header(column), value=row_selected[column], disabled=True)
            elif column_type is (int | float):
                st.number_input(label=ut_prettify_header(column), value=row_selected[column], disabled=True)
            elif column_type is (date | datetime):
                st.date_input(label=ut_prettify_header(column), value=row_selected[column], disabled=True)
            elif column_type is time:
                st.time_input(label=ut_prettify_header(column), value=row_selected[column], disabled=True)
            else:
                st.text_input(label=ut_prettify_header(column), value=row_selected[column], disabled=True)


def render_grid_form(
    str_form_name,
    df_data,
    str_table_name,
    lst_key_columns,
    lst_show_columns,
    lst_disabled_columns,
    lst_no_update_columns,
    dct_hard_default_columns,
    dct_column_config,
    str_prompt=None,
):
    show_header(str_form_name)
    with st.form(str_form_name, clear_on_submit=True):
        show_prompt(str_prompt)
        df_edits = st.data_editor(
            df_data,
            column_order=lst_show_columns,
            column_config=dct_column_config,
            disabled=lst_disabled_columns,
            num_rows="dynamic",
            hide_index=True,
        )
        submit = st.form_submit_button("Save Changes", disabled=authentication_service.current_user_has_read_role())
        if submit:
            booStatus = db.apply_df_edits(
                df_data, df_edits, str_table_name, lst_key_columns, lst_no_update_columns, dct_hard_default_columns
            )
            if booStatus:
                reset_post_updates("Changes have been saved.")


def render_edit_form(
    str_form_name,
    row_selected,
    str_table_name,
    lst_show_columns,
    lst_key_columns,
    lst_disabled=None,
    str_text_display=None,
    submit_disabled=False,
    form_unique_key: str | None = None,
):
    show_header(str_form_name)

    layout_column_1 = st.empty()
    if str_text_display:
        layout_column_1, layout_column_2 = st.columns([0.7, 0.3])

    dct_mods = {}
    if not lst_disabled:
        lst_disabled = lst_key_columns
    # Retrieve data types
    row_selected.map(type)

    if str_text_display:
        with layout_column_2:
            st.markdown(str_text_display)

    with layout_column_1:
        with st.form(form_unique_key or str_form_name, clear_on_submit=True):
            for column, value in row_selected.items():
                if column in lst_show_columns:
                    column_type = type(value)
                    if column_type is str:
                        dct_mods[column] = st.text_input(
                            label=ut_prettify_header(column),
                            value=row_selected[column],
                            disabled=(column in lst_disabled),
                        )
                    elif column_type in (int, float):
                        dct_mods[column] = st.number_input(
                            label=ut_prettify_header(column),
                            value=row_selected[column],
                            disabled=(column in lst_disabled),
                        )
                    elif column_type in (date, datetime, datetime.date):
                        dct_mods[column] = st.date_input(
                            label=ut_prettify_header(column),
                            value=row_selected[column],
                            disabled=(column in lst_disabled),
                        )
                    elif column_type is time:
                        dct_mods[column] = st.time_input(
                            label=ut_prettify_header(column),
                            value=row_selected[column],
                            disabled=(column in lst_disabled),
                        )
                    else:
                        dct_mods[column] = st.text_input(
                            label=ut_prettify_header(column),
                            value=row_selected[column],
                            disabled=(column in lst_disabled),
                        )
                else:
                    # If Hidden, add directly to dct_mods for updates
                    dct_mods[column] = row_selected[column]
            edit_allowed = not submit_disabled and authentication_service.current_user_has_edit_role()
            submit = st.form_submit_button("Save Changes", disabled=not edit_allowed)

            if submit and edit_allowed:
                # Construct SQL UPDATE statement based on the changed columns
                changes = []
                keys = []
                for col, val in dct_mods.items():
                    if col in lst_key_columns:
                        keys.append(f"{col} = {db.make_value_db_friendly(val)}")
                    if val != row_selected[col]:
                        changes.append(f"{col} = {db.make_value_db_friendly(val)}")

                # If there are any changes, construct and run the SQL statement
                if changes:
                    str_schema = st.session_state["dbschema"]
                    str_sql = (
                        f"UPDATE {str_schema}.{str_table_name} SET {', '.join(changes)} WHERE {' AND '.join(keys)};"
                    )
                    db.execute_sql(str_sql)
                    reset_post_updates("Changes have been saved.")
            elif submit:
                reset_post_updates("The current user does not have permission to save changes.", style="warning")



def render_insert_form(
    str_form_name,
    lst_columns,
    str_table_name,
    dct_default_values=None,
    lst_hidden=None,
    lst_disabled=None,
    form_unique_key: str | None = None,
    on_cancel=None,
):
    show_header(str_form_name)
    dct_mods = {}

    with st.form(form_unique_key or str_form_name, clear_on_submit=True):
        for column in lst_columns:
            if column not in (lst_hidden or []):
                val = "" if column not in (dct_default_values or []) else dct_default_values[column]
                input_type_by_default_value = {
                    date: st.date_input,
                }
                is_disabled = column in (lst_disabled or [])
                input_type = input_type_by_default_value.get(type(val), st.text_input)

                dct_mods[column] = input_type(label=ut_prettify_header(column), value=val, disabled=is_disabled)
            else:
                dct_mods[column] = dct_default_values[column]

        _, col1, col2 = st.columns([0.7, 0.1, 0.2])
        with col2:
            submit = st.form_submit_button("Insert Record", use_container_width=True)
        if on_cancel:
            with col1:
                st.form_submit_button("Cancel", on_click=on_cancel, use_container_width=True)

        if submit:
            str_schema = st.session_state["dbschema"]
            # Construct SQL INSERT statement based on all columns
            insert_cols = []
            insert_vals = []
            for col, val in dct_mods.items():
                insert_cols.append(col)
                insert_vals.append(f"'{val}'")
            str_sql = f"INSERT INTO {str_schema}.{str_table_name} ({', '.join(insert_cols)}) VALUES ({', '.join(insert_vals)})"
            db.execute_sql(str_sql)
            reset_post_updates("New record created.")


def render_grid_select(
    df,
    show_columns,
    str_prompt=None,
    int_height=400,
    do_multi_select=False,
    show_column_headers=None,
    render_highlights=True,
):
    show_prompt(str_prompt)

    # Set grid formatting
    cellstyle_jscode = JsCode(
        """
function(params) {
    let style = {
        'text-align': 'center',
        'vertical-align': 'middle',
        'border': '2px solid',
        'borderRadius': '15px',
        'display': 'inline-block'
    };

    if (['Failed', 'Error'].includes(params.value)) {
        style.color = 'black';
        style.borderColor = 'mistyrose';
        style.backgroundColor = "mistyrose";
        style.fontWeight = 'bolder';
        return style;
    } else if (params.value === 'Warning') {
        style.color = 'black';
        style.borderColor = 'seashell';
        style.backgroundColor = "seashell";
        return style;
    }  else if (params.value === 'Passed') {
        style.color = 'black';
        style.borderColor = 'honeydew';
        style.backgroundColor = "honeydew";
        return style;
    }  else if (params.value === '✓') {
        return {
//          'color': 'green',
            'text-align' : 'center',
            'fontWeight' : 'bolder',
            'fontSize' : "1.2em",
            };
    }  else if (params.value === '✘') {
        return {
//          'color': 'red',
            'text-align' : 'center',
            'fontWeight' : 'bolder',
            'fontSize' : "1.2em",
            };
    }  else if (params.value === '🚫') {
        return {
            'text-align' : 'center',
            'fontWeight' : 'bolder',
            'fontSize' : "1.2em",
            };
    }  else if (params.value === '🔇') {
        return {
            'text-align' : 'center',
//          'fontWeight' : 'bolder',
            'fontSize' : "1.2em",
            };
}  else if (params.value === '⌀') {
        return {
            'color': 'gray',
            'text-align' : 'center',
            'fontWeight' : 'bolder',
            'fontSize' : "1.2em",
            }
    }
}
"""
    )

    dct_col_to_header = dict(zip(show_columns, show_column_headers, strict=True)) if show_column_headers else None

    gb = GridOptionsBuilder.from_dataframe(df)
    selection_mode = "multiple" if do_multi_select else "single"
    gb.configure_selection(selection_mode=selection_mode, use_checkbox=do_multi_select)

    all_columns = list(df.columns)

    for column in all_columns:
        # Define common kwargs for all columns:  NOTE THAT FIRST COLUMN HOLDS CHECKBOX AND SHOULD BE SHOWN!
        str_header = dct_col_to_header.get(column) if dct_col_to_header else None
        common_kwargs = {
            "field": column,
            "header_name": str_header if str_header else ut_prettify_header(column),
            "hide": column not in show_columns,
            "headerCheckboxSelection": do_multi_select and column == show_columns[0],
            "headerCheckboxSelectionFilteredOnly": do_multi_select and column == show_columns[0],
        }
        highlight_kwargs = {"cellStyle": cellstyle_jscode}

        # Check if the column is a date-time column
        if is_datetime64_any_dtype(df[column]):
            if (df[column].dt.time == pd.Timestamp("00:00:00").time()).all():
                format_string = "yyyy-MM-dd"
            else:
                format_string = "yyyy-MM-dd HH:mm"
            # Additional kwargs for date-time columns
            date_time_kwargs = {"type": ["customDateTimeFormat"], "custom_format_string": format_string}

            # Merge common and date-time specific kwargs
            all_kwargs = {**common_kwargs, **date_time_kwargs}
        else:
            if render_highlights == True:
                # Merge common and highlight-specific kwargs
                all_kwargs = {**common_kwargs, **highlight_kwargs}
            else:
                all_kwargs = common_kwargs

        # Apply configuration using kwargs
        gb.configure_column(**all_kwargs)

    grid_options = gb.build()

    # Render Grid:  custom_css fixes spacing bug and tightens empty space at top of grid
    grid_data = AgGrid(
        df,
        gridOptions=grid_options,
        theme="balham",
        enable_enterprise_modules=False,
        allow_unsafe_jscode=True,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
        height=int_height,
        custom_css={
            "#gridToolBar": {
                "padding-bottom": "0px !important",
            }
        },
    )

    if len(grid_data["selected_rows"]):
        return grid_data["selected_rows"]


def render_logo(logo_path: str = logo_file):
    st.markdown(
        f"""<img class="dk-logo-img" src="data:image/svg+xml;base64,{base64.b64encode(open(logo_path, "rb").read()).decode()}">""",
        unsafe_allow_html=True,
    )


def render_icon_link(target_url, width=20, height=20, icon_path=help_icon):
    # left, right = st.columns([0.5, 0.5])
    # with left:

    # Check if the icon_path is a URL or a local path
    if validators.url(icon_path):
        img_data = icon_path
    else:
        # If local path, convert the image to base64
        img_data = base64.b64encode(Path(icon_path).read_bytes()).decode()

    # Get the image extension
    img_format = splitext(icon_path)[-1].replace(".", "")

    base_html = f"""
        <a href="{target_url}" style="display: flex; justify-content: center; align-items: center; height: 100%;">
            <img src="{{}}" style="width:{width}px; height:{height}px;" />
        </a>
    """
    if validators.url(icon_path):
        html_code = base_html.format(img_data)
    else:
        html_code = base_html.format(f"data:image/{img_format};base64,{img_data}")

    st.markdown(html_code, unsafe_allow_html=True)


def render_icon_link_new(target_url, width=20, height=20, icon_path=help_icon):
    # FIXME:  Why doesn't this work?

    # Check if the icon_path is a URL or a local path
    if validators.url(icon_path):
        img_data = icon_path
    else:
        # If local path, convert the image to base64
        img_data = base64.b64encode(Path(icon_path).read_bytes()).decode()

    # Get the image extension
    img_format = splitext(icon_path)[-1].replace(".", "")

    if not validators.url(icon_path):
        img_data = f"data:image/{img_format};base64,{img_data}"

    html_code = f"""
    <a href="#" onclick="DKlowerRightPopup('{target_url}'); return false;">
        <img src="{img_data}" style="width:{width}px; height:{height}px;" />
    </a>
    <script>
        function DKlowerRightPopup(url) {{
            let win_width = 300;
            let win_height = 400;
            let offsetX = 20;
            let offsetY = 20;
            let left = screen.width - win_width - offsetX;
            let top = screen.height - win_height - offsetY;
            window.open(url, 'PopupWindow', `width=${{win_width}},height=${{win_height}},left=${{left}},top=${{top}},scrollbars=yes,resizable=yes`);
        }}
    </script>
"""

    st.markdown(html_code, unsafe_allow_html=True)
