import json
import typing
from builtins import float
from pathlib import Path
from time import sleep

import pandas as pd
import streamlit as st
from pandas.api.types import is_datetime64_any_dtype
from st_aggrid import AgGrid, ColumnsAutoSizeMode, DataReturnMode, GridOptionsBuilder, GridUpdateMode, JsCode

from testgen.ui.components import widgets as testgen
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
    width: <<WIDTH>>;
    background-color: var(--dk-text-value-background);
    text-align: left;
    font-family: 'Courier New', monospace;
    padding-left: 10px;
    padding-right: 10px;
    box-sizing: border-box;
    overflow-wrap: break-word;
  }
  .dk-num-value {
    display: <<BLOCK>>;
    width: <<WIDTH>>;
    background-color: var(--dk-text-value-background);
    text-align: right;
    font-family: 'Courier New', monospace;
    padding-left: 10px;
    padding-right: 10px;
    box-sizing: border-box;
  }
</style>
"""
    str_data_width = "100%" if int_data_width == 0 else f"{int_data_width}px"
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
    columns: list[str],
    column_headers: list[str] | None = None,
    id_column: str | None = None,
    selection_mode: typing.Literal["single", "multiple", "disabled"] = "single",
    page_size: int = 500,
    reset_pagination: bool = False,
    bind_to_query: bool = False,
    render_highlights: bool = True,
    key: str = "aggrid",
) -> tuple[list[dict], dict]:
    """
    :param selection_mode: one of single, multiple or disabled. defaults
        to single.
    :param bind_to_query: whether to bind the selected row and page to
        query params.
    :param key: Streamlit cache key for the grid. required when binding
        selection to query.
    """
    if selection_mode != "disabled" and not id_column:
        raise ValueError("id_column is required when using 'single' or 'multiple' selection mode")

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
        style.borderColor = 'var(--ag-odd-row-background-color)';
        style.backgroundColor = "mistyrose";
        style.fontWeight = 'bolder';
        style.display = 'flex';
        style.alignItems = 'center';
        style.justifyContent = 'center';
        return style;
    } else if (params.value === 'Warning') {
        style.color = 'black';
        style.borderColor = 'var(--ag-odd-row-background-color)';
        style.backgroundColor = "seashell";
        style.display = 'flex';
        style.alignItems = 'center';
        style.justifyContent = 'center';
        return style;
    }  else if (params.value === 'Passed') {
        style.color = 'black';
        style.borderColor = 'var(--ag-odd-row-background-color)';
        style.backgroundColor = "honeydew";
        style.display = 'flex';
        style.alignItems = 'center';
        style.justifyContent = 'center';
        return style;
    }  else if (params.value === 'Log') {
        style.color = 'black';
        style.borderColor = 'var(--ag-odd-row-background-color)';
        style.backgroundColor = "#2196F3";
        style.display = 'flex';
        style.alignItems = 'center';
        style.justifyContent = 'center';
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

    page_changed = st.session_state.get(f"{key}_page_change", False)
    if page_changed:
        st.session_state[f"{key}_page_change"] = False

    grid_container = st.container()
    selected_column, paginator_column = st.columns([.5, .5])
    with paginator_column:
        def on_page_change():
            # Ignore the on_change event fired during paginator initialization
            if st.session_state.get(f"{key}_paginator_loaded", False):
                st.session_state[f"{key}_page_change"] = True
            else:
                st.session_state[f"{key}_paginator_loaded"] = True

        page_index = testgen.paginator(
            count=len(df),
            page_size=page_size,
            page_index=0 if reset_pagination else None,
            bind_to_query="page" if bind_to_query else None,
            on_change=on_page_change,
            key=f"{key}_paginator",
        )
        # Prevent flickering data when filters are changed (which triggers 2 reruns - one from filter and another from paginator)
        page_index = 0 if reset_pagination else page_index
        paginated_df = df.iloc[page_size * page_index : page_size * (page_index + 1)]

    dct_col_to_header = dict(zip(columns, column_headers, strict=True)) if column_headers else None

    gb = GridOptionsBuilder.from_dataframe(paginated_df)

    pre_selected_rows: typing.Any = {}
    if selection_mode == "single" and bind_to_query:
        bound_value = st.query_params.get("selected")
        bound_items = paginated_df[paginated_df[id_column] == bound_value]
        if len(bound_items) > 0:
            # https://github.com/PablocFonseca/streamlit-aggrid/issues/207#issuecomment-1793039564
            pre_selected_rows = {str(bound_value): True}
        else:
            if data_changed and st.query_params.get("selected"):
                rendering_counter += 1
            Router().set_query_params({"selected": None})

    selection = set()
    if selection_mode == "multiple":
        selection = st.session_state.get(f"{key}_multiselection", set())
        pre_selected_rows = {str(item): True for item in selection}

    gb.configure_selection(
        selection_mode=selection_mode,
        use_checkbox=selection_mode == "multiple",
        pre_selected_rows=pre_selected_rows,
    )

    if id_column:
        gb.configure_grid_options(getRowId=JsCode(f"function(row) {{ return row.data['{id_column}'] }}"))

    all_columns = list(paginated_df.columns)

    for column in all_columns:
        # Define common kwargs for all columns:  NOTE THAT FIRST COLUMN HOLDS CHECKBOX AND SHOULD BE SHOWN!
        str_header = dct_col_to_header.get(column) if dct_col_to_header else None
        common_kwargs = {
            "field": column,
            "header_name": str_header if str_header else ut_prettify_header(column),
            "hide": column not in columns,
            "headerCheckboxSelection": selection_mode == "multiple" and column == columns[0],
            "headerCheckboxSelectionFilteredOnly": selection_mode == "multiple" and column == columns[0],
            "sortable": False,
            "filter": False,
        }
        highlight_kwargs = {
            "cellStyle": cellstyle_jscode,
            "cellClassRules": {
                "status-tag": JsCode(
                    "function(params) { return ['Failed', 'Error', 'Warning', 'Passed', 'Log'].includes(params.value); }",
                ),
            },
        }

        # Check if the column is a date-time column
        if is_datetime64_any_dtype(paginated_df[column]):
            if (paginated_df[column].dt.time == pd.Timestamp("00:00:00").time()).all():
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

    # Render Grid:  custom_css fixes spacing bug and tightens empty space at top of grid
    with grid_container:
        grid_options = gb.build()
        grid_data = AgGrid(
            paginated_df.copy(),
            gridOptions=grid_options,
            theme="balham",
            enable_enterprise_modules=False,
            allow_unsafe_jscode=True,
            update_mode=GridUpdateMode.NO_UPDATE,
            update_on=["selectionChanged"],
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
            height=400,
            custom_css={
                "#gridToolBar": {
                    "padding-bottom": "0px !important",
                },
                ".ag-row-hover .ag-cell.status-tag": {
                    "border-color": "var(--ag-row-hover-color) !important",
                },
                ".ag-row-selected .ag-cell.status-tag": {
                    "border-color": "var(--ag-selected-row-background-color) !important",
                },
            },
            key=f"{key}_{page_index}_{selection_mode}_{rendering_counter}",
            reload_data=data_changed,
        )

    st.session_state[f"{key}_counter"] = rendering_counter
    st.session_state[f"{key}_dataframe"] = df

    if selection_mode != "disabled":
        selected_rows = grid_data["selected_rows"]
        # During page change, there are 2 reruns and the first one does not return the selected rows
        # So we ignore that run to prevent flickering the selected count
        if not page_changed:
            selection.difference_update(paginated_df[id_column].to_list())
            selection.update([row[id_column] for row in selected_rows])
            st.session_state[f"{key}_multiselection"] = selection

        if selection:    
            # We need to get the data from the original dataframe
            # Otherwise changes to the dataframe (e.g., editing the current selection) do not get reflected in the returned rows
            # Adding "modelUpdated" to AgGrid(update_on=...) does not work
            # because it causes unnecessary reruns that cause dialogs to close abruptly
            selected_df = df[df[id_column].isin(selection)]
            selected_data = json.loads(selected_df.to_json(orient="records"))
            
            selected_id, selected_item = None, None
            if selected_rows:
                selected_id = selected_rows[len(selected_rows) - 1][id_column]
                selected_item = next((item for item in selected_data if item[id_column] == selected_id), None)
            if bind_to_query:
                Router().set_query_params({"selected": selected_id})

            if selection_mode == "multiple" and (count := len(selected_data)):
                with selected_column:
                    testgen.caption(f"{count} item{'s' if count != 1 else ''} selected")

            return selected_data, selected_item
    
    return None, None
