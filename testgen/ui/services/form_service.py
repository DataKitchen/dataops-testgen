import json
import typing
from builtins import float
from pathlib import Path
from time import sleep

import pandas as pd
import streamlit as st
from pandas.api.types import is_datetime64_any_dtype
from st_aggrid import AgGrid, ColumnsAutoSizeMode, DataReturnMode, GridOptionsBuilder, GridUpdateMode, JsCode

from testgen.ui.navigation.router import Router

"""
Shared rendering of UI elements
"""

logo_file = (Path(__file__).parent.parent / "assets/dk_logo.svg").as_posix()
help_icon = (Path(__file__).parent.parent / "assets/question_mark.png").as_posix()


def render_refresh_button(button_container):
    with button_container:
        do_refresh = st.button(":material/refresh:", help="Refresh page data", use_container_width=False)
        if do_refresh:
            reset_post_updates("Refreshing page", True, True)


def show_prompt(str_prompt=None):
    if str_prompt:
        st.markdown(f":blue[{str_prompt}]")


def show_subheader(str_text=None):
    if str_text:
        st.subheader(f":green[{str_text}]")


def _show_section_header(str_section_header=None):
    if str_section_header:
        st.markdown(f":green[**{str_section_header}**]")


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

    df = df.copy()
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
            
            # We need to get the data from the original dataframe
            # Otherwise changes to the dataframe (e.g., editing the current selection) do not get reflected in the returned rows
            # Adding "modelUpdated" to AgGrid(update_on=...) does not work
            # because it causes unnecessary reruns that cause dialogs to close abruptly
            selected_props = [row[bind_to_query_prop] for row in selected_rows]
            selected_df = df[df[bind_to_query_prop].isin(selected_props)]
            selected_rows = json.loads(selected_df.to_json(orient="records"))

        return selected_rows
