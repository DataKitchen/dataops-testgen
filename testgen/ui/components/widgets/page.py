import logging
import os
import typing
from datetime import date

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

import testgen.common.logs as logs
from testgen import settings
from testgen.common import version_service
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session

LOG = logging.getLogger("testgen")
UPGRADE_URL = "https://docs.datakitchen.io/testgen/administer/upgrade-testgen/"
APP_LOGS_DIALOG_KEY = "app_logs:dialog"


class Breadcrumb(typing.TypedDict):
    path: str | None
    params: dict
    label: str


def page_header(
    title: str,
    help_topic: str | None = None,
    breadcrumbs: list["Breadcrumb"] | None = None,
):
    with st.container():
        no_flex_gap()
        title_column, links_column = st.columns([0.75, 0.25], vertical_alignment="bottom")

        with title_column:
            no_flex_gap()
            st.html(f'<h3 class="tg-header">{title}</h3>')
            if breadcrumbs:
                from testgen.ui.components.widgets import breadcrumbs_widget
                breadcrumbs_widget(key="breadcrumbs", data={"breadcrumbs": breadcrumbs})

        with links_column:
            help_menu(help_topic)

        st.html('<hr size="3" class="tg-header--line">')

    # Render app logs dialog widget (outside the header container)
    logs_data = st.session_state.get(APP_LOGS_DIALOG_KEY)
    if logs_data:
        from testgen.ui.components import widgets as testgen
        testgen.application_logs_widget(
            key="application_logs",
            data={"logs_data": logs_data},
            on_LogsDialogClosed_change=_on_logs_dialog_closed,
            on_DateChanged_change=_on_logs_date_changed,
            on_Refresh_change=_on_logs_refresh,
        )


def _read_log_data(log_date_str: str | None = None) -> dict:
    log_file_location = logs.get_log_full_path()
    today_str = date.today().isoformat()
    log_date = log_date_str or today_str

    if log_date != today_str:
        log_file_location += f".{log_date}"

    log_file_name = os.path.basename(log_file_location)

    try:
        with open(log_file_location) as file:
            log_content = file.read()
    except Exception:
        LOG.debug("Log viewer can't read log file %s", log_file_location)
        log_content = ""

    return {
        "log_content": log_content,
        "log_file_name": log_file_name,
        "date": log_date,
    }


def _on_logs_dialog_closed(*_) -> None:
    st.session_state.pop(APP_LOGS_DIALOG_KEY, None)


def _on_logs_date_changed(date_string: str) -> None:
    st.session_state[APP_LOGS_DIALOG_KEY] = _read_log_data(date_string)


def _on_logs_refresh(*_) -> None:
    current_data = st.session_state.get(APP_LOGS_DIALOG_KEY, {})
    st.session_state[APP_LOGS_DIALOG_KEY] = _read_log_data(current_data.get("date"))


def help_menu(help_topic: str | None = None) -> None:
    with st.container(key="tg-header--help"):
        version = version_service.get_version()
        if version.latest != version.current:
            st.page_link(UPGRADE_URL, label=f":small[:red[New version available! {version.latest}]]")

        help_container = st.empty()

        # Hack to programmatically close popover: https://github.com/streamlit/streamlit/issues/8265#issuecomment-3001655849
        def close_help(rerun: bool = False) -> None:
            with help_container.container(key="tg-header--help-dummy"):
                flex_row_end()
                st.markdown("Help :material/keyboard_arrow_down:")
            if rerun:
                safe_rerun()

        def open_app_logs():
            close_help()
            st.session_state[APP_LOGS_DIALOG_KEY] = _read_log_data()

        with help_container.container():
            flex_row_end()
            with st.popover("Help"):
                css_class("tg-header--help-wrapper")
                from testgen.ui.components.widgets import help_menu_widget
                help_menu_widget(
                    key="help_menu",
                    data={
                        "help_topic": help_topic,
                        "support_email": settings.SUPPORT_EMAIL,
                        "version": version.__dict__,
                        "permissions": {
                            "can_edit": session.auth.user_has_permission("edit"),
                        },
                    },
                    on_AppLogsClicked_change=lambda _: open_app_logs(),
                    on_ExternalLinkClicked_change=lambda _: close_help(rerun=True),
                )


def whitespace(size: float, unit: str = "rem", container: DeltaGenerator | None = None):
    _apply_html(f'<div style="height: {size}{unit};"></div>', container)


def divider(margin_top: int = 0, margin_bottom: int = 0, container: DeltaGenerator | None = None):
    _apply_html(f'<hr style="margin: {margin_top}px 0 {margin_bottom}px;">', container)


def text(text: str, styles: str = "", container: DeltaGenerator | None = None):
    _apply_html(f'<p class="text" style="{styles}">{text}</p>', container)


def caption(text: str, styles: str = "", container: DeltaGenerator | None = None):
    _apply_html(f'<p class="caption" style="{styles}">{text}</p>', container)


def css_class(css_classes: str, container: DeltaGenerator | None = None):
    _apply_html(f'<i class="{css_classes}"></i>', container)


def flex_row_start(container: DeltaGenerator | None = None):
    _apply_html('<i class="flex-row flex-start"></i>', container)


def flex_row_end(container: DeltaGenerator | None = None, wrap: bool = False):
    _apply_html(f'<i class="flex-row flex-end {"flex-wrap" if wrap else ""}"></i>', container)


def flex_row_center(container: DeltaGenerator | None = None):
    _apply_html('<i class="flex-row flex-center"></i>', container)


def no_flex_gap(container: DeltaGenerator | None = None):
    _apply_html('<i class="no-flex-gap"></i>', container)


def _apply_html(html: str, container: DeltaGenerator | None = None):
    if container:
        container.html(html)
    else:
        st.html(html)
