import logging

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from testgen import settings
from testgen.common import version_service
from testgen.ui.components.widgets.breadcrumbs import Breadcrumb
from testgen.ui.components.widgets.breadcrumbs import breadcrumbs as tg_breadcrumbs
from testgen.ui.components.widgets.testgen_component import testgen_component
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session
from testgen.ui.views.dialogs.application_logs_dialog import application_logs_dialog

UPGRADE_URL = "https://docs.datakitchen.io/testgen/administer/upgrade-testgen/"


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
                tg_breadcrumbs(breadcrumbs=breadcrumbs)

        with links_column:
            help_menu(help_topic)

        st.html('<hr size="3" class="tg-header--line">')

    # Feedback widget (bottom-right)
    feedback_widget()


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
            application_logs_dialog()

        def open_feedback():
            close_help()
            st.session_state.feedback_visible = True

        with help_container.container():
            flex_row_end()
            with st.popover("Help"):
                css_class("tg-header--help-wrapper")
                testgen_component(
                    "help_menu",   
                    props={
                        "help_topic": help_topic,
                        "support_email": settings.SUPPORT_EMAIL,
                        "version": version.__dict__,
                        "permissions": {
                            "can_edit": session.auth.user_has_permission("edit"),
                        },
                    },
                    on_change_handlers={
                        "AppLogsClicked": lambda _: open_app_logs(),
                        "FeedbackClicked": lambda _: open_feedback(),
                    },
                    event_handlers={
                        "ExternalLinkClicked": lambda _: close_help(rerun=True),
                    },
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


LOG = logging.getLogger("testgen")


def feedback_widget():
    """Render the feedback popup widget in the bottom-right corner.

    Visibility is driven by two signals:
    - session.show_feedback_popup: set by router on session start (30-day eligibility gate)
    - st.session_state.feedback_visible: set when the user manually clicks "Give Feedback"

    Feedback submissions are sent to MixPanel and optionally to Slack via TG_SLACK_FEEDBACK_WEBHOOK.
    """
    visible = bool(session.show_feedback_popup) or bool(st.session_state.get("feedback_visible", False))

    def on_dismissed(_):
        session.show_feedback_popup = False
        st.session_state.feedback_visible = False

    def on_submitted(payload):
        if payload:
            try:
                from testgen.common.mixpanel_service import MixpanelService
                MixpanelService().send_event(
                    "feedback_submitted",
                    rating=int(payload.get("rating", 0)),
                    comment=payload.get("comment") or None,
                    email=payload.get("email") or None,
                )
            except Exception:
                LOG.exception("Error sending feedback to MixPanel")

            if settings.SLACK_FEEDBACK_WEBHOOK:
                try:
                    import requests
                    rating = payload.get("rating", "N/A")
                    comment = payload.get("comment") or ""
                    email = payload.get("email") or ""
                    lines = [f"*New TestGen Feedback* ⭐ {rating}/5"]
                    if comment:
                        lines.append(f"*Comment:* {comment}")
                    if email:
                        lines.append(f"*Email:* {email}")
                    response = requests.post(settings.SLACK_FEEDBACK_WEBHOOK, json={"text": "\n".join(lines)}, timeout=5)
                    LOG.info("Slack feedback webhook response: %s %s", response.status_code, response.text)
                except Exception:
                    LOG.exception("Error sending feedback to Slack")
            else:
                LOG.warning("Slack feedback webhook not configured (TG_SLACK_FEEDBACK_WEBHOOK is not set)")

        session.show_feedback_popup = False
        st.session_state.feedback_visible = False

    testgen_component(
        "feedback_widget",
        props={"visible": visible},
        on_change_handlers={
            "FeedbackDismissed": on_dismissed,
            "FeedbackSubmitted": on_submitted,
        },
    )

