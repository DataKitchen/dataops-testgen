import logging
from functools import wraps
from itertools import count
from typing import Any
from uuid import UUID

import streamlit as st

from testgen.common.models import with_database_session
from testgen.common.models.notification_destinations import (
    NotificationDestination,
    WebhookDestination,
)
from testgen.common.models.notification_settings import NotificationSettings, NotificationSettingsValidationError
from testgen.common.models.settings import PersistedSetting
from testgen.ui.session import session

LOG = logging.getLogger("testgen")

RESULT_KEY = "notification_settings_dialog:result"


class NotificationSettingsDialogBase:

    title: str = "Manage Notifications"

    def __init__(self,
             ns_class: type[NotificationSettings],
             ns_attrs: dict[str, Any] | None = None,
             component_props: dict[str, Any] | None = None,
         ):
        self.ns_class = ns_class
        self.ns_attrs = ns_attrs or {}
        self.component_props = component_props or {}
        self._result_idx = iter(count())

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
                st.session_state[RESULT_KEY] = {"success": success, "message": message, "idx": next(self._result_idx)}

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
        addressing = self._addressing_kwargs(item)
        self.ns_class.create(**self.ns_attrs, **addressing, **attrs)

    @event_handler(success_message="Notification updated")
    def on_update_item(self, item):
        addressing = self._addressing_kwargs(item)
        # Both fields must be updated in the same save so validation sees a consistent
        # addressing state — switching from destination to inline leaves recipients
        # empty (or vice versa) briefly, and validation would reject that.
        update = {
            "recipients": addressing.get("recipients", []),
            "notification_destination_id": addressing.get("notification_destination_id"),
            **self._item_to_model_attrs(item),
        }
        self._update_item(item["id"], update)

    def _addressing_kwargs(self, item: dict[str, Any]) -> dict[str, Any]:
        """Return ``{"recipients": [...]}`` or ``{"notification_destination_id": UUID}`` from an item payload."""
        destination_id = item.get("notification_destination_id")
        if destination_id:
            return {"notification_destination_id": UUID(destination_id) if isinstance(destination_id, str) else destination_id}
        return {"recipients": item.get("recipients") or []}

    @event_handler()
    def on_pause_item(self, item):
        self._update_item(item["id"], {"enabled": False})

    @event_handler()
    def on_resume_item(self, item):
        self._update_item(item["id"], {"enabled": True})

    def _get_component_props(self) -> dict[str, Any]:
        raise NotImplementedError

    def _mark_duplicates(
        self,
        ns_json_list: list[dict[str, Any]],
        destination_names: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Mark rules that share ``(trigger, scope, target)``, where target is either
        one recipient address or a destination id. A destination-based rule is a duplicate
        of another rule pointing at the same destination for the same event/scope; an
        inline rule is a duplicate of another inline rule sharing any recipient address.
        A destination-based rule and an inline rule to the same recipients are NOT
        duplicates — they address the same recipients through different mechanisms.
        """
        rule_counts: dict[tuple, int] = {}
        rule_items: dict[tuple, list[dict]] = {}
        rule_labels: dict[tuple, str] = {}
        for item in ns_json_list:
            trigger = item.get("trigger")
            scope = item.get("scope")
            destination_id = item.get("notification_destination_id")
            if destination_id:
                rule = ("destination", destination_id, trigger, scope)
                rule_counts[rule] = rule_counts.get(rule, 0) + 1
                rule_items.setdefault(rule, []).append(item)
                rule_labels[rule] = destination_names.get(destination_id, destination_id)
            else:
                for recipient in item.get("recipients") or []:
                    rule = ("inline", recipient, trigger, scope)
                    rule_counts[rule] = rule_counts.get(rule, 0) + 1
                    rule_items.setdefault(rule, []).append(item)
                    rule_labels[rule] = recipient
        for rule, occurrence_count in rule_counts.items():
            if occurrence_count > 1:
                for item in rule_items[rule]:
                    item.setdefault("duplicates", []).append(rule_labels[rule])
        return ns_json_list

    @with_database_session
    def build_data(self) -> dict:
        user_can_edit = session.auth.user_has_permission("edit")
        user_can_administer = session.auth.user_has_permission("administer")
        result = st.session_state.get(RESULT_KEY)

        project_code = self.ns_attrs.get("project_code")
        destinations = NotificationDestination.list_for_project(project_code) if project_code else []
        destination_names = {str(d.id): d.name for d in destinations}
        # Only the fields the notification-settings dialog reads: id, name,
        # type, and (for webhooks) the sub-type so Slack/Teams render
        # distinctly. Shipping every destination's address list to any user
        # with ``edit`` would be an information leak.
        destination_options = []
        for d in destinations:
            entry = {
                "id": str(d.id),
                "name": d.name,
                "destination_type": d.destination_type,
            }
            if isinstance(d, WebhookDestination) and d.webhook_type is not None:
                entry["webhook_type"] = d.webhook_type.value
            destination_options.append(entry)

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
                "notification_destination_id": str(ns.notification_destination_id) if ns.notification_destination_id else None,
                **self._model_to_item_attrs(ns),
            }
            ns_json_list.append(ns_json)

        component_props = {
            **self.component_props,
            **(self._get_component_props()),
        }
        scope_options_labels = dict(component_props.get("scope_options", []))
        ns_json_list = sorted(
            self._mark_duplicates(ns_json_list, destination_names),
            key=lambda item: "0" if not item.get("scope") else scope_options_labels.get(item["scope"], "ZZZ"),
        )

        return {
            "title": self.title,
            "smtp_configured": PersistedSetting.get("SMTP_CONFIGURED"),
            "items": ns_json_list,
            "destinations": destination_options,
            "can_manage_destinations": user_can_administer,
            "project_settings_url": f"/settings?project_code={project_code}" if project_code else None,
            "event": self.ns_class.__mapper_args__["polymorphic_identity"].value,
            "permissions": {"can_edit": user_can_edit},
            "result": result,
            "scope_options": [],
            "scope_label": None,
            **component_props,
        }

    def clear_state(self) -> None:
        st.session_state.pop(RESULT_KEY, None)
