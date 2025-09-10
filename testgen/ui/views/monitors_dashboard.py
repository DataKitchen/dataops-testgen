import datetime
import logging
import random
from typing import ClassVar, Literal

import streamlit as st

from testgen.common.models.table_group import TableGroup
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.session import session

PAGE_ICON = "apps_outage"
PAGE_TITLE = "Monitors"
LOG = logging.getLogger("testgen")


class MonitorsDashboardPage(Page):
    path = "monitors"
    can_activate: ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=0,
    )

    def render(
        self,
        project_code: str,
        table_group_id: str | None = None,
        table_name_filter: str | None = None,
        only_tables_with_anomalies: Literal["true", "false"] | None = None,
        sort_field: str | None = None,
        sort_order: str | None = None,
        items_per_page: str = "20",
        current_page: str = "0",
        **_kwargs,
    ) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "monitors-dashboard",
        )

        table_groups = TableGroup.select_minimal_where(TableGroup.project_code == project_code)

        _all_monitored_tables = [example_item(table_groups) for _ in range(100)]

        current_page = int(current_page)
        items_per_page = int(items_per_page)

        all_monitored_tables_filtered = [
            item for item in _all_monitored_tables
            if (not table_group_id or str(item["table_group_id"]) == table_group_id)
                and (not table_name_filter or table_name_filter.lower() in item["table_name"].lower())
                and (not only_tables_with_anomalies or only_tables_with_anomalies == "false" or (only_tables_with_anomalies == "true" and ((item["freshness_anomalies"] or 0) + (item["volume_anomalies"] or 0) + (item["schema_anomalies"] or 0) + (item["quality_drift_anomalies"] or 0)) > 0))
        ]
        all_monitored_tables_count = len(all_monitored_tables_filtered)
        page_start = current_page * items_per_page
        monitored_tables_page = all_monitored_tables_filtered[page_start:(page_start + items_per_page)]

        return testgen.testgen_component(
            "monitors_dashboard",
            props={
                "summary": {
                    "freshness_anomalies": 5,
                    "volume_anomalies": 0,
                    "schema_anomalies": 2,
                    "quality_drift_anomalies": 0,
                },
                "table_group_filter_options": [
                    {
                        "value": str(table_group.id),
                        "label": table_group.table_groups_name,
                        "selected": str(table_group_id) == str(table_group.id),
                    } for table_group in table_groups
                ],
                "monitors": {
                    "items": monitored_tables_page,
                    "current_page": current_page,
                    "items_per_page": items_per_page,
                    "total_count": all_monitored_tables_count,
                },
                "filters": {
                    "table_group_id": table_group_id,
                    "table_name_filter": table_name_filter,
                    "only_tables_with_anomalies": only_tables_with_anomalies,
                },
                "sort": {
                    "sort_field": sort_field,
                    "sort_order": sort_order,
                } if sort_field and sort_order else None,
            },
            on_change_handlers={
                "OpenMonitoringTrends": lambda payload: open_table_trends(**payload),
                "SetParamValues": lambda payload: set_param_values(payload),
            },
        )


def set_param_values(payload: dict) -> None:
    Router().set_query_params(payload)


def example_item(table_groups):
    table_states = ["modified", "deleted", "added"]
    return {
        "table_group_id": str(random.choice([table_group.id for table_group in table_groups])),
        "table_name": random.choice(["black_pearl_fittings", "elder_wand_suppliers", "phoenix_feathers"]),
        "table_state": random.choice(table_states),
        "freshness_anomalies": random.randint(0, 10),
        "volume_anomalies": random.randint(0, 5),
        "schema_anomalies": random.randint(0, 7),
        "quality_drift_anomalies": random.choice([random.randint(0, 3), None]),
        "latest_update": (
            datetime.datetime.now() - datetime.timedelta(days=random.randint(0, 7), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        ).astimezone(datetime.UTC).isoformat(),
        "row_count": random.randint(-2000, 2000),
    }


def open_table_trends(*, table_group_id: str, table_name: str, **_kwargs):
    def show_dialog():
        testgen.testgen_component(
            "table_monitoring_trends",
            props={
                "freshness_events": [
                    {"changed": True, "expected": True, "time": '2025-09-10T13:10:56.852Z'},
                    {"changed": True, "expected": False, "time": '2025-09-10T15:10:56.852Z'},
                    {"changed": False, "expected": True, "time": '2025-09-10T17:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-10T19:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-10T21:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-11T13:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-11T15:10:56.852Z'},
                    {"changed": False, "expected": False, "time": '2025-09-11T17:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-11T19:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-11T21:10:56.852Z'},
                    {"changed": False, "expected": True, "time": '2025-09-12T08:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-12T10:10:56.852Z'},
                    {"changed": False, "expected": False, "time": '2025-09-12T12:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-12T14:10:56.852Z'},
                    {"changed": False, "expected": True, "time": '2025-09-12T16:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-12T18:10:56.852Z'},
                    {"changed": False, "expected": True, "time": '2025-09-12T20:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-13T09:10:56.852Z'},
                    {"changed": False, "expected": True, "time": '2025-09-13T11:10:56.852Z'},
                    {"changed": True, "expected": True, "time": '2025-09-13T13:10:56.852Z'},
                ],
                "volume_events": [
                    { "value": 100000, "time": '2025-09-10T13:10:56.852Z'},
                    { "value": 110000, "time": '2025-09-10T15:10:56.852Z'},
                    { "value": 120000, "time": '2025-09-10T17:10:56.852Z'},
                    { "value": 115000, "time": '2025-09-10T19:10:56.852Z'},
                    { "value": 135000, "time": '2025-09-10T21:10:56.852Z'},
                    { "value": 135000, "time": '2025-09-11T13:10:56.852Z'},
                    { "value": 135000, "time": '2025-09-11T15:10:56.852Z'},
                    { "value": 135000, "time": '2025-09-11T17:10:56.852Z'},
                    { "value": 135000, "time": '2025-09-11T19:10:56.852Z'},
                    { "value": 135000, "time": '2025-09-11T21:10:56.852Z'},
                    { "value": 140000, "time": '2025-09-12T08:10:56.852Z'},
                    { "value": 140000, "time": '2025-09-12T10:10:56.852Z'},
                    { "value": 140000, "time": '2025-09-12T12:10:56.852Z'},
                    { "value": 125000, "time": '2025-09-12T14:10:56.852Z'},
                    { "value": 125000, "time": '2025-09-12T16:10:56.852Z'},
                    { "value": 125000, "time": '2025-09-12T18:10:56.852Z'},
                    { "value": 125000, "time": '2025-09-12T20:10:56.852Z'},
                    { "value": 125000, "time": '2025-09-13T09:10:56.852Z'},
                    { "value": 125000, "time": '2025-09-13T11:10:56.852Z'},
                    { "value": 300000, "time": '2025-09-13T13:10:56.852Z'},
                ],
                "schema_change_events": [
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-10T13:10:56.852Z'},
                    {"additions": 50, "deletions": 0, "modifications": 0, "time": '2025-09-10T15:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-10T17:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-10T19:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-10T21:10:56.852Z'},
                    {"additions": 20, "deletions": 0, "modifications": 0, "time": '2025-09-11T13:10:56.852Z'},
                    {"additions": 5, "deletions": 0, "modifications": 1, "time": '2025-09-11T15:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-11T17:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-11T19:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-11T21:10:56.852Z'},
                    {"additions": 100, "deletions": 20, "modifications": 5, "time": '2025-09-12T08:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-12T10:10:56.852Z'},
                    {"additions": 10, "deletions": 5, "modifications": 1, "time": '2025-09-12T12:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-12T14:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-12T16:10:56.852Z'},
                    {"additions": 0, "deletions": 10, "modifications": 0, "time": '2025-09-12T18:10:56.852Z'},
                    {"additions": 30, "deletions": 0, "modifications": 0, "time": '2025-09-12T20:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-13T09:10:56.852Z'},
                    {"additions": 0, "deletions": 0, "modifications": 0, "time": '2025-09-13T11:10:56.852Z'},
                    {"additions": 20, "deletions": 50, "modifications": 1, "time": '2025-09-13T13:10:56.852Z'},
                ],
                "line_charts": [
                    {
                        "label": "min_wand_price - Average",
                        "events": [
                            { "value": 700, "time": '2025-09-10T13:10:56.852Z'},
                            { "value": 700, "time": '2025-09-10T15:10:56.852Z'},
                            { "value": 700, "time": '2025-09-10T17:10:56.852Z'},
                            { "value": 700, "time": '2025-09-10T19:10:56.852Z'},
                            { "value": 700, "time": '2025-09-10T21:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T13:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T15:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T17:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T19:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T21:10:56.852Z'},
                            { "value": 700, "time": '2025-09-12T08:10:56.852Z'},
                            { "value": 700, "time": '2025-09-12T10:10:56.852Z'},
                            { "value": 800, "time": '2025-09-12T12:10:56.852Z'},
                            { "value": 900, "time": '2025-09-12T14:10:56.852Z'},
                            { "value": 1000, "time": '2025-09-12T16:10:56.852Z'},
                            { "value": 900, "time": '2025-09-12T18:10:56.852Z'},
                            { "value": 800, "time": '2025-09-12T20:10:56.852Z'},
                            { "value": 700, "time": '2025-09-13T09:10:56.852Z'},
                            { "value": 700, "time": '2025-09-13T11:10:56.852Z'},
                            { "value": 700, "time": '2025-09-13T13:10:56.852Z'},
                        ],
                    },
                    {
                        "label": "wand_size - Average",
                        "events": [
                            { "value": 700, "time": '2025-09-10T13:10:56.852Z'},
                            { "value": 700, "time": '2025-09-10T15:10:56.852Z'},
                            { "value": 700, "time": '2025-09-10T17:10:56.852Z'},
                            { "value": 700, "time": '2025-09-10T19:10:56.852Z'},
                            { "value": 700, "time": '2025-09-10T21:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T13:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T15:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T17:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T19:10:56.852Z'},
                            { "value": 700, "time": '2025-09-11T21:10:56.852Z'},
                            { "value": 700, "time": '2025-09-12T08:10:56.852Z'},
                            { "value": 700, "time": '2025-09-12T10:10:56.852Z'},
                            { "value": 800, "time": '2025-09-12T12:10:56.852Z'},
                            { "value": 900, "time": '2025-09-12T14:10:56.852Z'},
                            { "value": 1000, "time": '2025-09-12T16:10:56.852Z'},
                            { "value": 900, "time": '2025-09-12T18:10:56.852Z'},
                            { "value": 800, "time": '2025-09-12T20:10:56.852Z'},
                            { "value": 700, "time": '2025-09-13T09:10:56.852Z'},
                            { "value": 700, "time": '2025-09-13T11:10:56.852Z'},
                            { "value": 700, "time": '2025-09-13T13:10:56.852Z'},
                        ],
                    },
                ],
            },
        )

    return st.dialog(title=f"Table: {table_name}")(show_dialog)()
