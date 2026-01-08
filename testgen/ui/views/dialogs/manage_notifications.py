import logging
from functools import wraps
from itertools import count
from typing import Any
from uuid import UUID

import streamlit as st

from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import NotificationSettings, NotificationSettingsValidationError
from testgen.common.models.settings import PersistedSetting
from testgen.ui.components import widgets
from testgen.ui.session import session, temp_value

LOG = logging.getLogger("testgen")


class NotificationSettingsDialogBase:

    title: str = "Manage Email Notifications"

    def __init__(self,
             ns_class: type[NotificationSettings],
             ns_attrs: dict[str, Any] | None = None,
             component_props: dict[str, Any] | None = None,
         ):
        self.ns_class = ns_class
        self.ns_attrs = ns_attrs or {}
        self.component_props = component_props or {}
        self.get_result, self.set_result = temp_value("notification_settings_dialog:result")
        self._result_idx = iter(count())

    def open(self) -> None:
        return st.dialog(title=self.title)(self.render)()

    @staticmethod
    def event_handler(*, success_message=None, error_message="Something went wrong."):

        def decorator(method):

            @wraps(method)
            def wrapper(self, *args, **kwargs):
                try:
                    with_database_session(method)(self, *args, **kwargs)
                except NotificationSettingsValidationError as e:
                    success = False
                    message = str(e)
                except Exception:
                    LOG.exception("Action %s failed with:", method.__name__)
                    success = False
                    message = error_message
                else:
                    success = True
                    message = success_message

                # The ever-changing "idx" is useful to force refreshing the component
                self.set_result({"success": success, "message": message, "idx": next(self._result_idx)})
                st.rerun(scope="fragment")

            return wrapper
        return decorator

    @event_handler(success_message="Notification deleted")
    def on_delete_item(self, item):
        if ns := self.ns_class.get(item["id"]):
            ns.delete()

    def _update_item(self, item_id: UUID | str, item_data: dict[str, Any]):
        ns = self.ns_class.get(item_id)
        for key, value in item_data.items():
            if key != "id" and value != getattr(ns, key):
                setattr(ns, key, value)
        ns.save()

    def _item_to_model_attrs(self, item: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _model_to_item_attrs(self, model: NotificationSettings) -> dict[str, Any]:
        raise NotImplementedError

    @event_handler(success_message="Notification added")
    def on_add_item(self, item):
        attrs = self._item_to_model_attrs(item)
        self.ns_class.create(**self.ns_attrs, recipients=item["recipients"], **attrs)

    @event_handler(success_message="Notification updated")
    def on_update_item(self, item):
        self._update_item(item["id"], {"recipients": item["recipients"], **self._item_to_model_attrs(item)})

    @event_handler()
    def on_pause_item(self, item):
        self._update_item(item["id"], {"enabled": False})

    @event_handler()
    def on_resume_item(self, item):
        self._update_item(item["id"], {"enabled": True})

    def _get_component_props(self) -> dict[str, Any]:
        raise NotImplementedError

    @with_database_session
    def render(self) -> None:
        user_can_edit = session.auth.user_has_permission("edit")
        result = self.get_result()

        ns_json_list = []
        select_col = [  # noqa: RUF015
            attr
            for attr in ("score_definition_id", "test_suite_id", "table_group_id", "project_code")
            if attr in self.ns_attrs
        ][0]
        for ns in self.ns_class.select(**{select_col: self.ns_attrs[select_col]}):
            ns_json = {
                "id": str(ns.id),
                "enabled": ns.enabled,
                "recipients": ns.recipients,
                **self._model_to_item_attrs(ns),
            }
            ns_json_list.append(ns_json)

        widgets.css_class("m-dialog")
        widgets.testgen_component(
            "notification_settings",
            props={
                "smtp_configured": PersistedSetting.get("SMTP_CONFIGURED"),
                "items": ns_json_list,
                "event": self.ns_class.__mapper_args__["polymorphic_identity"].value,
                "permissions": {"can_edit": user_can_edit},
                "result": result,
                "scope_options": [],
                "scope_label": None,
                **self.component_props,
                **self._get_component_props(),
            },
            event_handlers={
                "AddNotification": self.on_add_item,
                "UpdateNotification": self.on_update_item,
                "DeleteNotification": self.on_delete_item,
                "PauseNotification": self.on_pause_item,
                "ResumeNotification": self.on_resume_item,
            },
        )
