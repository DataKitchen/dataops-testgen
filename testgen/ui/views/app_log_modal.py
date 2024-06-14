import logging
import os
import re
from datetime import date, datetime

import streamlit as st

import testgen.common.logs as logs
import testgen.ui.services.form_service as fm
from testgen.common import display_service
from testgen.ui.components import widgets as testgen

LOG = logging.getLogger("testgen")


# Read the log file
@st.cache_data
def _read_log(file_path):
    try:
        with open(file_path) as file:
            log_data = file.readlines()
        return log_data  # NOQA TRY300

    except Exception:
        st.warning(f"Log file  is unavailable: {file_path}")
        LOG.debug(f"Log viewer can't read log file {file_path}")


# Function to filter log data by date
def _filter_by_date(log_data, start_date, end_date):
    filtered_data = []
    for line in log_data:
        # Assuming the log line starts with a date in the format 'YYYY-MM-DD'
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", line)
        if match:
            log_date = datetime.strptime(match.group(1), "%Y-%m-%d")
            if start_date <= log_date <= end_date:
                filtered_data.append(line)
    return filtered_data


# Function to search text in log data
def _search_text(log_data, search_query):
    return [line for line in log_data if search_query in line]


def view_log_file(button_container):
    log_file_modal = testgen.Modal(title=None, key="dk-view-log-modal", max_width=1100)

    with button_container:
        if st.button(
            "Troubleshooting　→", help="Open and review TestGen Log files", use_container_width=True
        ):
            log_file_modal.open()

    if log_file_modal.is_open():
        with log_file_modal.container():
            fm.render_modal_header("TestGen App Log", None, "Review/Troubleshoot daily log files")

            _, file_out_path = display_service.get_in_out_paths()

            col1, col2, col3 = st.columns([33, 33, 33])
            log_date = col1.date_input("Log Date", value=datetime.today())

            log_file_location = logs.get_log_full_path()

            if log_date != date.today():
                log_file_location += log_date.strftime(".%Y-%m-%d")

            log_file_name = os.path.basename(log_file_location)

            log_data = _read_log(log_file_location)

            search_query = col2.text_input("Filter by Text")
            if search_query:
                show_data = _search_text(log_data, search_query)
            else:
                show_data = log_data

            # Refresh button
            col3.write(" \n ")
            if col3.button("Refresh"):
                # Clear cache to refresh the log data
                st.cache_data.clear()

            if log_data:
                st.markdown(f"**Log File:** {log_file_name}")
                # TOO SLOW: st.code(body=''.join(show_data), language="log", line_numbers=True)
                st.text_area("Log Data", value="".join(show_data), height=400)

                # Download button
                st.download_button("Download", data="".join(show_data), file_name=log_file_name)
