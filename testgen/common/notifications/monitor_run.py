import logging

from testgen.common.models import with_database_session
from testgen.common.models.notification_settings import (
    MonitorNotificationSettings,
    MonitorNotificationTrigger,
)
from testgen.common.models.project import Project
from testgen.common.models.settings import PersistedSetting
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_result import TestResult
from testgen.common.models.test_run import TestRun
from testgen.common.notifications.notifications import BaseNotificationTemplate
from testgen.utils import log_and_swallow_exception

LOG = logging.getLogger("testgen")


class MonitorEmailTemplate(BaseNotificationTemplate):

    def get_subject_template(self) -> str:
        return (
            "[TestGen] Monitors Alert: {{summary.table_groups_name}}"
            "{{#if summary.table_name}} | {{summary.table_name}}{{/if}}"
            ' | {{total_anomalies}} {{pluralize total_anomalies "anomaly" "anomalies"}}'
        )

    def get_title_template(self):
        return "Monitors Alert: {{summary.table_groups_name}}"

    def get_main_content_template(self):
        return """
            <div class="summary">
              <table
                role="presentation"
                cellpadding="2"
                cellspacing="0"
                border="0">
                <tr>
                  <td class="summary__label">Project</td>
                  <td class="summary__value">{{summary.project_name}}</td>
                </tr>
                <tr>
                  <td class="summary__label">Table Group</td>
                  <td class="summary__value"><b>{{summary.table_groups_name}}</b></td>
                </tr>
                {{#if summary.table_name}}
                <tr>
                  <td class="summary__label">Table</td>
                  <td class="summary__value"><b>{{summary.table_name}}</b></td>
                </tr>
                {{/if}}
                <tr>
                  <td class="summary__label">Time</td>
                  <td class="summary__value">{{format_dt summary.test_endtime}}</td>
                </tr>
              </table>
            </div>
            <div class="summary">
              <table
                role="presentation"
                cellpadding="0"
                cellspacing="0"
                border="0">
                <tr>
                  <td class="summary__title">Anomalies Summary</td>
                  <td align="right">
                    <a class="link" href="{{view_in_testgen_url}}" target="_blank">View on TestGen &gt;</a>
                  </td>
                </tr>
                <tr><td><div style="height: 8px;"></div></td></tr>

                <tr>
                  <td width="1" style="white-space: nowrap;">
                    <table border="0" cellpadding="0" cellspacing="0" style="width: auto;">
                      <tbody>
                        <tr>
                          {{#each anomaly_counts}}
                            {{>anomaly_tag .}}
                          {{/each}}
                        </tr>
                      </tbody>
                    </table>
                  </td>
                </tr>
              </table>
            </div>
            <div class="summary">
              <table
                role="presentation"
                cellpadding="2"
                cellspacing="0"
                border="0">
                <tr class="text-caption">
                  <td>Table</td>
                  <td>Monitor</td>
                  <td>Details</td>
                </tr>
                {{#each anomalies}}
                <tr>
                  <td>{{truncate 30 table_name}}</td>
                  <td>{{type}}</code></td>
                  <td>{{details}}</td>
                </tr>
                {{/each}}

                <tr>
                  <td></td>
                  <td colspan="2" class="summary__caption">
                    {{#if truncated}}
                    + {{truncated}} more
                    {{/if}}
                  </td>
                </tr>
              </table>
            </div>
        """

    def get_anomaly_tag_template(self):
        return """
            <td valign="middle" style="padding-right: 24px;">
              <table border="0" cellpadding="0" cellspacing="0" role="presentation">
                <tr>
                  <td valign="middle">
                    <div style="{{#if count}}background-color: #EF5350; min-width: 15px; padding: 0px 5px; border-radius: 10px; text-align: center; line-height: 20px;{{else}}background-color: #9CCC65; width: 20px; height: 20px; border-radius: 50%; text-align: center; line-height: 21px;{{/if}} color: #ffffff; font-weight: bold; font-size: 13px;">
                      {{#if count}}{{count}}{{else}}&#10003;{{/if}}
                    </div>
                  </td>
                  <td valign="middle" style="color: #111111; padding-left: 8px;">{{type}}</td>
                </tr>
              </table>
            </td>
        """

    def get_extra_css_template(self) -> str:
        return """
          .tg-summary-bar {
            width: 350px;
            border-radius: 4px;
            overflow: hidden;
          }

          .tg-summary-bar td {
            height: 10px;
            padding: 0;
            line-height: 10px;
            font-size: 0;
          }

          .tg-summary-bar--caption {
            margin-top: 4px;
            color: var(--caption-text-color);
            font-size: 13px;
            font-style: italic;
            line-height: 1;
          }

          .tg-summary-bar--legend {
            width: auto;
            margin-right: 8px;
          }

          .tg-summary-bar--legend-dot {
            margin-right: 2px;
            font-style: normal;
          }
        """


@log_and_swallow_exception
@with_database_session
def send_monitor_notifications(test_run: TestRun, result_list_ct=20):
    notifications = list(MonitorNotificationSettings.select(
        enabled=True,
        test_suite_id=test_run.test_suite_id,
    ))
    if not notifications:
        return

    triggers = {MonitorNotificationTrigger.on_anomalies}
    notifications = [ns for ns in notifications if ns.trigger in triggers]
    if not notifications:
        return

    table_group, = TableGroup.select_where(TableGroup.monitor_test_suite_id == test_run.test_suite_id)
    if not table_group:
        return

    project = Project.get(table_group.project_code)
    for notification in notifications:
        table_name = notification.settings.get("table_name")
        test_results = list(TestResult.select_where(
            TestResult.test_run_id == test_run.id,
            TestResult.result_code == 0,
            (TestResult.table_name == table_name) if table_name else True,
        ))

        if len(test_results) <= 0:
            continue

        anomalies = []
        anomaly_counts = { label: 0 for _, label in _TEST_TYPE_LABELS.items()}
        for test_result in test_results:
            label = _TEST_TYPE_LABELS.get(test_result.test_type)
            anomaly_counts[label] = (anomaly_counts.get(label) or 0) + 1
            details = test_result.message or "N/A"
            
            if test_result.test_type == "Freshness_Trend":
                parts = details.split(". ", 1)
                message = parts[1].rstrip(".") if len(parts) > 1 else None
                prefix = "Table updated" if "detected: Yes" in details else "No table update"
                details = f"{prefix} - {message}" if message else prefix
            elif test_result.test_type == "Metric_Trend":
                label = f"{label}: {test_result.column_names}"

            anomalies.append({
                "table_name": test_result.table_name or "N/A",
                "type": label,
                "details": details,
            })

        view_in_testgen_url = "".join(
            (
                PersistedSetting.get("BASE_URL", ""),
                "/monitors?project_code=",
                str(table_group.project_code),
                "&table_group_id=",
                str(table_group.id),
                "&table_name_filter=" if table_name else "",
                table_name if table_name else "",
                "&source=email",
            )
        )
        try:
            MonitorEmailTemplate().send(
                notification.recipients,
                {
                    "summary": {
                        "test_endtime": test_run.test_endtime,
                        "table_groups_name": table_group.table_groups_name,
                        "project_name": project.project_name,
                        "table_name": table_name,
                    },
                    "total_anomalies": len(test_results),
                    "anomaly_counts": [
                        {"type": key, "count": value}
                        for key, value in anomaly_counts.items()
                    ],
                    "anomalies": anomalies[:result_list_ct],
                    "truncated": max(len(anomalies) - result_list_ct, 0),
                    "view_in_testgen_url": view_in_testgen_url,
                },
            )
        except Exception:
            LOG.exception("Failed sending monitor email notifications")


_TEST_TYPE_LABELS = {
    "Freshness_Trend": "Freshness",
    "Volume_Trend": "Volume",
    "Schema_Drift": "Schema",
    "Metric_Trend": "Metric",
}
