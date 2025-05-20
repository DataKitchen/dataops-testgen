import typing
from builtins import float
from enum import Enum
from pathlib import Path
from time import sleep

import pandas as pd
import streamlit as st
from pandas.api.types import is_datetime64_any_dtype
from st_aggrid import AgGrid, ColumnsAutoSizeMode, DataReturnMode, GridOptionsBuilder, GridUpdateMode, JsCode
from streamlit_extras.no_default_selectbox import selectbox

import testgen.ui.services.database_service as db
from testgen.ui.navigation.router import Router

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
                else st.form_submit_button("Save Changes")
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
        st.html(str_markdown)
        st.divider()


def render_grid_select(
    df: pd.DataFrame,
    show_columns,
    str_prompt=None,
    int_height=400,
    do_multi_select: bool | None = None,
    selection_mode: typing.Literal["single", "multiple", "disabled"] = "single",
    show_column_headers=None,
    render_highlights=True,
    bind_to_query_name: str | None = None,
    bind_to_query_prop: str | None = None,
    key: str = "aggrid",
):
    """
    :param do_multi_select: DEPRECATED. boolean to choose between single
        or multiple selection.
    :param selection_mode: one of single, multiple or disabled. defaults
        to single.
    :param bind_to_query_name: name of the query param where to bind the
        selected row.
    :param bind_to_query_prop: name of the property of the selected row
        which value will be set in the query param.
    :param key: Streamlit cache key for the grid. required when binding
        selection to query.
    """

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
    data_changed: bool = True
    rendering_counter = st.session_state.get(f"{key}_counter") or 0
    previous_dataframe = st.session_state.get(f"{key}_dataframe")

    if previous_dataframe is not None:
        data_changed = not df.equals(previous_dataframe)

    dct_col_to_header = dict(zip(show_columns, show_column_headers, strict=True)) if show_column_headers else None

    gb = GridOptionsBuilder.from_dataframe(df)
    selection_mode_ = selection_mode
    if do_multi_select is not None:
        selection_mode_ = "multiple" if do_multi_select else "single"

    pre_selected_rows: typing.Any = {}
    if bind_to_query_name and bind_to_query_prop:
        bound_value = st.query_params.get(bind_to_query_name)
        bound_items = df[df[bind_to_query_prop] == bound_value]
        if len(bound_items) > 0:
            # https://github.com/PablocFonseca/streamlit-aggrid/issues/207#issuecomment-1793039564
            pre_selected_rows = {str(bound_items.iloc[0][bind_to_query_prop]): True}
        else:
            if data_changed and st.query_params.get(bind_to_query_name):
                rendering_counter += 1
            Router().set_query_params({bind_to_query_name: None})

    gb.configure_selection(
        selection_mode=selection_mode_,
        use_checkbox=selection_mode_ == "multiple",
        pre_selected_rows=pre_selected_rows,
    )

    if bind_to_query_prop:
        gb.configure_grid_options(getRowId=JsCode(f"""function(row) {{ return row.data['{bind_to_query_prop}'] }}"""))

    all_columns = list(df.columns)

    for column in all_columns:
        # Define common kwargs for all columns:  NOTE THAT FIRST COLUMN HOLDS CHECKBOX AND SHOULD BE SHOWN!
        str_header = dct_col_to_header.get(column) if dct_col_to_header else None
        common_kwargs = {
            "field": column,
            "header_name": str_header if str_header else ut_prettify_header(column),
            "hide": column not in show_columns,
            "headerCheckboxSelection": selection_mode_ == "multiple" and column == show_columns[0],
            "headerCheckboxSelectionFilteredOnly": selection_mode_ == "multiple" and column == show_columns[0],
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
        update_mode=GridUpdateMode.NO_UPDATE,
        update_on=["selectionChanged"],
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
        height=int_height,
        custom_css={
            "#gridToolBar": {
                "padding-bottom": "0px !important",
            }
        },
        key=f"{key}_{selection_mode_}_{rendering_counter}",
        reload_data=data_changed,
    )

    st.session_state[f"{key}_counter"] = rendering_counter
    st.session_state[f"{key}_dataframe"] = df

    selected_rows = grid_data["selected_rows"]
    if len(selected_rows) > 0:
        if bind_to_query_name and bind_to_query_prop:
            Router().set_query_params({bind_to_query_name: selected_rows[0][bind_to_query_prop]})
        return selected_rows
